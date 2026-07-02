"""SDD 64: cavar el búnker y construir habitaciones subterráneas."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import lock_current_player
from app.core.db import get_session
from app.models import Player
from app.schemas import BunkerBuildRequest, BunkerDigRequest, BunkerRaidRequest
from app.services.bunkers import BunkerError, build_room, dig, raid

router = APIRouter()


@router.post("/dig", status_code=status.HTTP_201_CREATED)
async def do_dig(
    body: BunkerDigRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    try:
        b = await dig(session, player, body.base_id)
    except BunkerError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return {"id": b.id, "base_id": b.base_id}


@router.post("/build-room", status_code=status.HTTP_201_CREATED)
async def do_build_room(
    body: BunkerBuildRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    try:
        r = await build_room(session, player, body.base_id, body.room_key, body.cell)
    except BunkerError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return {"id": r.id, "room_key": r.room_key, "cell": r.cell, "status": r.status}


@router.post("/raid", status_code=status.HTTP_201_CREATED)
async def do_raid(
    body: BunkerRaidRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """SDD 64: sabotaje al búnker de un rival mapeado (gas | rats | water)."""
    try:
        result = await raid(session, player, body.target_id, body.action)
    except BunkerError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return result
