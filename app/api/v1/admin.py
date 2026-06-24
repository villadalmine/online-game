from fastapi import APIRouter, Depends
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
