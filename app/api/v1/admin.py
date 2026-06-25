from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.core.db import get_session
from app.core.redis import get_redis
from app.models import Player
from app.services import presence
from app.worker import run_tick

router = APIRouter()


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
