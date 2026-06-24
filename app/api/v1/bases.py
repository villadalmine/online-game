from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import lock_current_player
from app.core.db import get_session
from app.models import Base_, Player
from app.schemas import BuildingOut, BuildRequest, TrainingOrderOut, TrainRequest
from app.services.build import BuildError, start_build
from app.services.training import TrainingError, start_training

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
