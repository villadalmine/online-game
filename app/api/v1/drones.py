import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player, lock_current_player
from app.core.db import get_session
from app.models import Player
from app.schemas import (
    DroneLaunchRequest,
    DroneSimOut,
    DroneSimRequest,
    DroneSquadronOut,
)
from app.services.drones import DroneError, launch_drones, recall_drones, simulate_drones

router = APIRouter()


@router.post("/simulate", response_model=DroneSimOut)
async def drones_simulate(
    body: DroneSimRequest,
    player: Player = Depends(get_current_player),
):
    """Calculadora determinista (SDD 50): cuánto dura un escuadrón y cuántos derriban, dada la
    capacidad antiaérea del rival, tu energía y tu regen por tick."""
    sim = simulate_drones(
        body.force, body.antiair, body.energy, body.regen_per_tick, body.max_ticks
    )
    return DroneSimOut(
        survive_ticks=sim.survive_ticks,
        eta_energy_ticks=sim.eta_energy_ticks, eta_turrets_ticks=sim.eta_turrets_ticks,
        drain_per_tick=round(sim.drain_per_tick, 2), intel_quality=sim.intel_quality,
        attack_per_tick=round(sim.attack_per_tick, 2),
        losses=sim.losses, survivors=sim.survivors,
    )


@router.post("/launch", response_model=DroneSquadronOut, status_code=status.HTTP_201_CREATED)
async def do_launch(
    body: DroneLaunchRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Despacha un escuadrón de drones a una base del MISMO planeta (SDD 50)."""
    if player.race_key is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Primero completa el onboarding.")
    try:
        squad = await launch_drones(
            session, player, body.factory_base_id, body.target_base_id,
            body.force, body.max_ticks,
        )
    except DroneError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return DroneSquadronOut(
        id=squad.id, target_base_id=squad.target_base_id, planet_key=squad.planet_key,
        force=json.loads(squad.force), status=squad.status, ticks_done=squad.ticks_done,
    )


@router.post("/{squad_id}/recall", response_model=DroneSquadronOut)
async def do_recall(
    squad_id: int,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Trae un escuadrón de vuelta; los sobrevivientes vuelven al stock."""
    try:
        squad = await recall_drones(session, player, squad_id)
    except DroneError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return DroneSquadronOut(
        id=squad.id, target_base_id=squad.target_base_id, planet_key=squad.planet_key,
        force=json.loads(squad.force), status=squad.status, ticks_done=squad.ticks_done,
    )
