from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import lock_current_player
from app.core.db import get_session
from app.models import Base_, Player
from app.schemas import (
    BuildingOut,
    BuildRequest,
    MoveTroopsRequest,
    TrainingOrderOut,
    TrainRequest,
    TroopMoveOut,
)
from app.services.build import BuildError, start_build
from app.services.training import TrainingError, start_training
from app.services.troops import TroopError, start_move

router = APIRouter()


async def _load_owned_base(base_id: int, player: Player, session) -> Base_:
    if player.race_key is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Primero completa el onboarding.")
    base = await session.get(Base_, base_id)
    if base is None or base.player_id != player.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Base no encontrada")
    return base


@router.post("/{base_id}/build", response_model=BuildingOut, status_code=status.HTTP_201_CREATED)
async def build(
    base_id: int,
    body: BuildRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    base = await _load_owned_base(base_id, player, session)
    try:
        building = await start_build(
            session, player, base, body.building_key, body.target_mineral
        )
    except BuildError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return BuildingOut(
        id=building.id,
        building_key=building.building_key,
        level=building.level,
        status=building.status,
        production_mineral=building.production_mineral,
        completes_at=building.completes_at,
    )


@router.post(
    "/{base_id}/train", response_model=TrainingOrderOut, status_code=status.HTTP_201_CREATED
)
async def train(
    base_id: int,
    body: TrainRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    base = await _load_owned_base(base_id, player, session)
    try:
        order = await start_training(session, player, base, body.unit_key, body.quantity)
    except TrainingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return TrainingOrderOut(
        id=order.id,
        base_id=order.base_id,
        unit_key=order.unit_key,
        quantity=order.quantity,
        completes_at=order.completes_at,
    )


@router.post(
    "/{base_id}/move-troops", response_model=TroopMoveOut, status_code=status.HTTP_201_CREATED
)
async def move_troops(
    base_id: int,
    body: MoveTroopsRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """SDD 62: mover tropas de esta base a otra base propia (guarnición)."""
    await _load_owned_base(base_id, player, session)
    try:
        move = await start_move(session, player, base_id, body.to_base_id, body.units)
    except TroopError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    import json as _json
    return TroopMoveOut(
        id=move.id, from_base_id=move.from_base_id, to_base_id=move.to_base_id,
        units=_json.loads(move.units), status=move.status, arrives_at=move.arrives_at,
    )
