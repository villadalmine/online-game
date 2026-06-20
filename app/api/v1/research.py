from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player
from app.core.db import get_session
from app.models import Player
from app.schemas import ResearchOrderOut, ResearchRequest
from app.services.research import ResearchError, start_research

router = APIRouter()


@router.post("", response_model=ResearchOrderOut, status_code=status.HTTP_201_CREATED)
async def research(
    body: ResearchRequest,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    if player.race_key is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Primero completa el onboarding.")
    try:
        order = await start_research(session, player, body.tech_key)
    except ResearchError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return ResearchOrderOut(id=order.id, tech_key=order.tech_key, completes_at=order.completes_at)
