import json

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player, lock_current_player
from app.core.config import get_settings
from app.core.db import get_session
from app.core.redis import get_redis, rate_limited
from app.models import CombatLog, Player
from app.schemas import (
    AttackMissionOut,
    AttackRequest,
    CombatLogOut,
    CombatPlanOut,
    CombatPlanRequest,
    CombatSimOut,
    CombatSimRequest,
    StrikeMissionOut,
    StrikeRequest,
    StrikeSimOut,
    StrikeSimRequest,
    TributeRequest,
)
from app.services.combat import CombatError, recall_mission, resolve_combat, start_attack
from app.services.combat_calc import PlanError, plan_attack
from app.services.strike import (
    StrikeError,
    accept_tribute,
    offer_tribute,
    simulate_strike,
    start_strike,
)

router = APIRouter()


@router.post("/simulate", response_model=CombatSimOut)
async def simulate(
    body: CombatSimRequest,
    player: Player = Depends(get_current_player),
):
    """Calculadora determinista (SDD 34): mismo `resolve_combat` que el combate real."""
    r = resolve_combat(
        body.attacker_force,
        body.defender_force,
        body.attacker_atk_mult,
        body.defender_def_mult,
        body.defender_flat_defense,
    )
    return CombatSimOut(
        outcome=r.outcome,
        attack_score=round(r.attack_score, 2),
        defense_score=round(r.defense_score, 2),
        attacker_losses=r.attacker_losses,
        defender_losses=r.defender_losses,
    )


@router.post("/plan", response_model=CombatPlanOut)
async def plan(
    body: CombatPlanRequest,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Plan contra una base real estimando su defensa **desde tu intel** (espiá primero)."""
    try:
        return CombatPlanOut(**await plan_attack(session, player, body.target_base_id, body.margin))
    except PlanError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/attack", response_model=AttackMissionOut, status_code=status.HTTP_201_CREATED)
async def do_attack(
    body: AttackRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
    redis: Redis | None = Depends(get_redis),
):
    """Despacha una flota. El combate se resuelve al llegar (ver /players/me)."""
    if player.race_key is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Primero completa el onboarding.")
    limit = get_settings().attack_rate_limit_per_min
    if await rate_limited(redis, f"rl:attack:{player.id}", limit, 60):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados ataques; espera un momento."
        )
    try:
        mission = await start_attack(
            session, player, body.target_base_id, body.force, body.source_base_id
        )
    except CombatError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    import json as _json

    return AttackMissionOut(
        id=mission.id,
        target_base_id=mission.target_base_id,
        force=_json.loads(mission.force),
        status=mission.status,
        arrives_at=mission.arrives_at,
    )


@router.post("/missions/{mission_id}/recall", response_model=AttackMissionOut)
async def recall(
    mission_id: int,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Retira una flota en vuelo de ida; vuelve con toda la fuerza, sin combate."""
    try:
        mission = await recall_mission(session, player, mission_id)
    except CombatError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    import json as _json

    return AttackMissionOut(
        id=mission.id,
        target_base_id=mission.target_base_id,
        force=_json.loads(mission.force),
        status=mission.status,
        arrives_at=mission.arrives_at,
        returns_at=mission.returns_at,
    )


@router.post("/strike/simulate", response_model=StrikeSimOut)
async def strike_simulate(
    body: StrikeSimRequest,
    player: Player = Depends(get_current_player),
):
    """Calculadora determinista (SDD 49): mismo `simulate_strike` que la salva real. Pasá la
    capacidad antimisil del rival (Σ intercept_power de torretas) y ves qué impacta/intercepta."""
    r = simulate_strike(body.force, body.intercept_capacity, body.atk_mult)
    return StrikeSimOut(
        impacted=r.impacted, intercepted=r.intercepted, damage=r.damage, area=r.area
    )


@router.post("/strike", response_model=StrikeMissionOut, status_code=status.HTTP_201_CREATED)
async def do_strike(
    body: StrikeRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Lanza una salva de misiles a una base enemiga del MISMO planeta (SDD 49)."""
    if player.race_key is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Primero completa el onboarding.")
    try:
        mission = await start_strike(
            session, player, body.launcher_base_id, body.target_base_id, body.force
        )
    except StrikeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return StrikeMissionOut(
        id=mission.id, launcher_base_id=mission.launcher_base_id,
        target_base_id=mission.target_base_id, force=json.loads(mission.force),
        status=mission.status, arrives_at=mission.arrives_at,
    )


@router.post("/strike/{mission_id}/tribute")
async def strike_tribute(
    mission_id: int,
    body: TributeRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """SDD 67: el defensor ofrece tributo para cancelar un misil nuclear entrante."""
    try:
        m = await offer_tribute(session, player, mission_id, body.minerals, body.energy)
    except StrikeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return {"mission_id": m.id, "tribute": json.loads(m.tribute)}


@router.post("/strike/{mission_id}/accept-tribute")
async def strike_accept_tribute(
    mission_id: int,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """SDD 67: el atacante acepta el tributo y cancela su misil nuclear."""
    try:
        result = await accept_tribute(session, player, mission_id)
    except StrikeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return result


@router.get("/reports", response_model=list[CombatLogOut])
async def reports(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    res = await session.execute(
        select(CombatLog)
        .where(or_(CombatLog.attacker_id == player.id, CombatLog.defender_id == player.id))
        .order_by(CombatLog.created_at.desc())
        .limit(50)
    )
    return [
        CombatLogOut(
            id=log.id,
            attacker_id=log.attacker_id,
            defender_id=log.defender_id,
            target_base_id=log.target_base_id,
            outcome=log.outcome,
            details=json.loads(log.details),
            created_at=log.created_at,
        )
        for log in res.scalars()
    ]


@router.get("/battles")
async def all_battles(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Feed público de TODAS las batallas (no solo las tuyas): quién atacó a quién, de qué planeta
    a cuál, y quién ganó. SDD 35: sin unidades/bajas (se consigue espiando, no mirando el feed)."""
    from app.services.battles import battles_feed
    return await battles_feed(session, limit=80)
