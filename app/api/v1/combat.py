import json

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player
from app.core.config import get_settings
from app.core.db import get_session
from app.core.redis import get_redis, rate_limited
from app.models import CombatLog, Player
from app.schemas import AttackMissionOut, AttackRequest, CombatLogOut
from app.services.combat import CombatError, recall_mission, start_attack

router = APIRouter()


@router.post("/attack", response_model=AttackMissionOut, status_code=status.HTTP_201_CREATED)
async def do_attack(
    body: AttackRequest,
    player: Player = Depends(get_current_player),
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
        mission = await start_attack(session, player, body.target_base_id, body.force)
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
    player: Player = Depends(get_current_player),
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
