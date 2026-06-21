from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player
from app.core.db import get_session
from app.models import Player
from app.schemas import WorldEventOut
from app.services.world import world_events

router = APIRouter()


@router.get("/events", response_model=list[WorldEventOut])
async def events(
    _: Player = Depends(get_current_player), session: AsyncSession = Depends(get_session)
):
    """Feed público de eventos de la galaxia (batallas y alianzas formadas)."""
    return await world_events(session)
