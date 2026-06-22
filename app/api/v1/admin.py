from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player
from app.core.db import get_session
from app.models import Player
from app.worker import run_tick

router = APIRouter()


@router.post("/tick")
async def trigger_tick(
    _: Player = Depends(get_current_player), session: AsyncSession = Depends(get_session)
):
    """Run one world tick now (NPC turns + advance all queues).

    Handy for the demo/CLI and tests so you don't have to wait for the CronJob.
    """
    return await run_tick(session)


@router.post("/season/close")
async def close_season(
    _: Player = Depends(get_current_player), session: AsyncSession = Depends(get_session)
):
    """Cierra YA la temporada activa (snapshot al Hall of Fame) y abre la siguiente. Admin/tests."""
    from app.services.seasons import close_current_now

    closed = await close_current_now(session)
    await session.commit()
    return {"closed": closed}
