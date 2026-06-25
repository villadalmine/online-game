"""Meta-insights (SDD 41): el meta aprendido de las partidas (win-rates por composición)."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player
from app.core.db import get_session
from app.models import Player
from app.services.insights import get_insights

router = APIRouter()


@router.get("/insights")
async def insights(
    _: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Insights agregados del meta (datos reales). Base para el panel 📈 Meta y la IA."""
    return await get_insights(session)
