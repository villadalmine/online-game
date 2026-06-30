"""SDD 61: lanzar/retirar satélites + ver el mapa de enemigos."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player, lock_current_player
from app.core.db import get_session
from app.models import Player
from app.schemas import SatelliteLaunchRequest
from app.services.satellites import SatelliteError, launch, recall, satellites_state

router = APIRouter()


@router.post("/launch", status_code=status.HTTP_201_CREATED)
async def do_launch(
    body: SatelliteLaunchRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    try:
        sat = await launch(session, player, body.unit_key, body.target_id)
    except SatelliteError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return {"id": sat.id, "kind": sat.kind, "target_id": sat.target_id,
            "shield_grade": sat.shield_grade, "energy": sat.energy}


@router.post("/{sat_id}/recall")
async def do_recall(
    sat_id: int,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    try:
        sat = await recall(session, player, sat_id)
    except SatelliteError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return {"id": sat.id, "status": sat.status}


@router.get("/intel")
async def intel(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Mapa de enemigos descubierto por tus satélites espía (% + bases/unidades)."""
    sats, maps = await satellites_state(session, player)
    return {"satellites": sats, "enemy_maps": maps}
