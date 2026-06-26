import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.core.db import get_session
from app.core.redis import get_redis
from app.models import CombatLog, GameEvent, Player
from app.schemas import AdminPlayerEdit
from app.services import presence
from app.worker import run_tick

router = APIRouter()


@router.get("/npc-stats")
async def npc_stats(
    admin: Player = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    """Snapshot por NPC para entender CÓMO juega la IA (SDD): score, postura, mezcla de acciones
    (del journal), récord de combate y últimas jugadas. Complementa las métricas Prometheus
    (game_npc_actions_total / game_npc_decisions_total) con una vista puntual sin Grafana."""
    from app.services.scoring import player_score
    npcs = (await session.execute(
        select(Player).where(Player.is_npc.is_(True)).order_by(Player.id)
    )).scalars().all()
    out = []
    for n in npcs:
        actions = dict((await session.execute(
            select(GameEvent.type, func.count())
            .where(GameEvent.player_id == n.id).group_by(GameEvent.type)
        )).all())
        # combate: como atacante y como defensor
        atk = dict((await session.execute(
            select(CombatLog.outcome, func.count())
            .where(CombatLog.attacker_id == n.id).group_by(CombatLog.outcome)
        )).all())
        dfd = dict((await session.execute(
            select(CombatLog.outcome, func.count())
            .where(CombatLog.defender_id == n.id).group_by(CombatLog.outcome)
        )).all())
        wins = atk.get("attacker", 0) + dfd.get("defender", 0)
        losses = atk.get("defender", 0) + dfd.get("attacker", 0)
        try:
            mem = json.loads(n.npc_memory or "[]")
        except Exception:
            mem = []
        out.append({
            "id": n.id, "username": n.username, "race": n.race_key,
            "score": await player_score(session, n),
            "posture": n.npc_posture, "strategy": n.npc_strategy,
            "actions": actions,                       # {build: N, train: N, attack: N, ...}
            "combat": {"wins": wins, "losses": losses,
                       "battles": wins + losses},
            "recent": mem[-8:] if isinstance(mem, list) else [],
        })
    return out


@router.get("/players")
async def list_players(
    status_: str | None = Query(default=None, alias="status"),
    admin: Player = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    """Jugadores (con email) para moderar (SDD 14). `?status=pending` filtra. Solo admin."""
    q = select(Player).where(Player.is_npc.is_(False))
    if status_:
        q = q.where(Player.status == status_)
    rows = (await session.execute(q.order_by(Player.id))).scalars().all()
    return [
        {"id": p.id, "username": p.username, "email": p.email,
         "status": p.status, "is_admin": p.is_admin, "approved_at": p.approved_at}
        for p in rows
    ]


async def _moderate(session: AsyncSession, admin: Player, player_id: int, new_status: str) -> dict:
    target = await session.get(Player, player_id)
    if target is None or target.is_npc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Jugador no encontrado.")
    target.status = new_status
    if new_status == "active":
        target.approved_at = datetime.now(UTC)
        target.approved_by = admin.id
    from app.services.notifications import notify
    msg = {"active": "Tu cuenta fue aprobada, ¡a jugar!",
           "rejected": "Tu solicitud de cuenta fue rechazada.",
           "suspended": "Tu cuenta fue suspendida."}.get(new_status, "Estado actualizado.")
    await notify(session, target.id, "account_status", msg, {"status": new_status})
    await session.commit()
    return {"id": target.id, "status": target.status}


@router.post("/players/{player_id}/approve")
async def approve_player(
    player_id: int, admin: Player = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    """Activa una cuenta pendiente (SDD 14): status=active + notifica al jugador. Solo admin."""
    return await _moderate(session, admin, player_id, "active")


@router.post("/players/{player_id}/reject")
async def reject_player(
    player_id: int, admin: Player = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    return await _moderate(session, admin, player_id, "rejected")


@router.post("/players/{player_id}/suspend")
async def suspend_player(
    player_id: int, admin: Player = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    return await _moderate(session, admin, player_id, "suspended")


@router.post("/players/{player_id}/edit")
async def edit_player(
    player_id: int, body: AdminPlayerEdit,
    admin: Player = Depends(get_current_admin), session: AsyncSession = Depends(get_session),
):
    """ABM (Modificación): cambiar username/email/status. Valida unicidad. Solo admin."""
    target = await session.get(Player, player_id)
    if target is None or target.is_npc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Jugador no encontrado.")
    if body.username and body.username != target.username:
        clash = (await session.execute(
            select(Player.id).where(Player.username == body.username)
        )).first()
        if clash:
            raise HTTPException(status.HTTP_409_CONFLICT, "Ese usuario ya existe.")
        target.username = body.username
    if body.email is not None:
        email = body.email.strip().lower() or None
        if email and email != (target.email or ""):
            clash = (await session.execute(
                select(Player.id).where(Player.email == email)
            )).first()
            if clash:
                raise HTTPException(status.HTTP_409_CONFLICT, "Ese email ya tiene cuenta.")
        target.email = email
    if body.status:
        if body.status not in ("active", "pending", "suspended", "rejected"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Estado inválido.")
        target.status = body.status
    await session.commit()
    return {"id": target.id, "username": target.username, "email": target.email,
            "status": target.status}


@router.delete("/players/{player_id}")
async def delete_player(
    player_id: int, admin: Player = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    """ABM (Baja): borra una cuenta y todo su imperio (cascade). No te podés borrar a vos ni a otro
    admin (sacale admin primero). Solo admin."""
    target = await session.get(Player, player_id)
    if target is None or target.is_npc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Jugador no encontrado.")
    if target.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No te podés borrar a vos mismo.")
    if target.is_admin:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No se puede borrar a otro admin.")
    username = target.username
    await session.delete(target)
    await session.commit()
    return {"deleted": player_id, "username": username}


@router.post("/players/{player_id}/reset-password")
async def reset_password(
    player_id: int, admin: Player = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    """SDD 14: el admin no puede VER una password (está hasheada), pero sí RESETEARLA. Genera una
    temporal, la guarda hasheada y la devuelve UNA vez para pasársela al jugador (que la cambia en
    Perfil). Alternativa para el dueño: entrar con código por email (OTP) y cambiarla."""
    import secrets

    from app.core.security import hash_password
    target = await session.get(Player, player_id)
    if target is None or target.is_npc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Jugador no encontrado.")
    temp = secrets.token_urlsafe(9)
    target.password_hash = hash_password(temp)
    from app.services.notifications import notify
    await notify(session, target.id, "password_reset",
                 "El admin reseteó tu contraseña; entrá con la temporal y cambiala en Perfil.")
    await session.commit()
    return {"id": target.id, "username": target.username, "temp_password": temp}


@router.get("/online")
async def online_players(
    _: Player = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
    redis: Redis | None = Depends(get_redis),
):
    """Lista de jugadores online (usernames). Solo admin (SDD 21)."""
    ids = await presence.online_ids(redis)
    if not ids:
        return {"count": 0, "players": []}
    rows = (
        await session.execute(select(Player.username).where(Player.id.in_(ids)))
    ).scalars().all()
    return {"count": len(rows), "players": sorted(rows)}


@router.post("/tick")
async def trigger_tick(
    _: Player = Depends(get_current_admin), session: AsyncSession = Depends(get_session)
):
    """Run one world tick now (NPC turns + advance all queues).

    Handy for the demo/CLI and tests so you don't have to wait for the CronJob.
    """
    return await run_tick(session)


@router.post("/season/close")
async def close_season(
    _: Player = Depends(get_current_admin), session: AsyncSession = Depends(get_session)
):
    """Cierra YA la temporada activa (snapshot al Hall of Fame) y abre la siguiente. Admin/tests."""
    from app.services.seasons import close_current_now

    closed = await close_current_now(session)
    await session.commit()
    return {"closed": closed}
