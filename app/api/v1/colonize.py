"""Colonización (SDD 37, v1): el grafo de opciones raza×planeta para tu imperio (read-only)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player
from app.core.db import get_session
from app.models import Player
from app.schemas import ColonizeOptionOut
from app.services.colonization import options

router = APIRouter()


@router.get("/options", response_model=list[ColonizeOptionOut])
async def colonize_options(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Para tu raza, el veredicto de cada planeta de tu galaxia (great/ok/poor/impossible) con
    modifiers y el porqué. Es el grafo para decidir a dónde expandirse."""
    if player.race_key is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Primero completá el onboarding.")
    return [ColonizeOptionOut(**o) for o in options(player.race_key, player.galaxy_key)]
