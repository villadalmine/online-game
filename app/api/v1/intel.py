"""Espionaje e inteligencia (SDD 35): mandar espías + leer la intel acumulada por objetivo."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player, lock_current_player
from app.core.db import get_session
from app.models import Player
from app.schemas import IntelReportOut, SpyMissionOut, SpyRequest
from app.services.espionage import SpyError, player_intel, start_spy

router = APIRouter()


@router.post("/spy", response_model=SpyMissionOut, status_code=status.HTTP_201_CREATED)
async def spy(
    body: SpyRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Despacha espías a una base objetivo. La intel se genera al llegar (ver GET /intel)."""
    if player.race_key is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Primero completa el onboarding.")
    try:
        m = await start_spy(session, player, body.target_base_id, body.spies)
    except SpyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return SpyMissionOut(
        id=m.id, target_base_id=m.target_base_id, status=m.status, arrives_at=m.arrives_at
    )


@router.get("/intel", response_model=list[IntelReportOut])
async def intel(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Inteligencia acumulada del jugador sobre sus objetivos (con confianza por antigüedad)."""
    return [IntelReportOut(**r) for r in await player_intel(session, player)]


@router.get("/intel/{target_id}", response_model=IntelReportOut)
async def intel_detail(
    target_id: int,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    for r in await player_intel(session, player):
        if r["target_id"] == target_id:
            return IntelReportOut(**r)
    raise HTTPException(
        status.HTTP_404_NOT_FOUND, "Sin inteligencia de ese objetivo (espialo primero)."
    )
