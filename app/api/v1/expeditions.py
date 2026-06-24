from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player, lock_current_player
from app.content.registry import get_content
from app.core.db import get_session
from app.models import Player
from app.schemas import ExpeditionOrderOut, ExpeditionRequest
from app.services.expedition import ExpeditionError, start_expedition

router = APIRouter()


@router.get("/moons")
async def reachable_moons(player: Player = Depends(get_current_player)):
    """Moons the player can reach (those in their galaxy)."""
    if player.galaxy_key is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Primero completa el onboarding.")
    content = get_content()
    return [
        moon
        for key, moon in content.moons.items()
        if content.moon_galaxy(key) == player.galaxy_key
    ]


@router.post("", response_model=ExpeditionOrderOut, status_code=status.HTTP_201_CREATED)
async def launch(
    body: ExpeditionRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    if player.race_key is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Primero completa el onboarding.")
    try:
        order = await start_expedition(session, player, body.moon_key)
    except ExpeditionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return ExpeditionOrderOut(id=order.id, moon_key=order.moon_key, completes_at=order.completes_at)
