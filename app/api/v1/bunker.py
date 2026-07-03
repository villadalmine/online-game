"""SDD 64: cavar el búnker y construir habitaciones subterráneas."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import lock_current_player
from app.core.db import get_session
from app.models import Player
from app.schemas import (
    BunkerBuildRequest,
    BunkerDigRequest,
    BunkerEvacuateRequest,
    BunkerRaidRequest,
    BunkerVaultRequest,
    QuantumTeleportRequest,
    RepopulateRequest,
)
from app.services.bunkers import (
    BunkerError,
    build_room,
    dig,
    dig_deeper,
    evacuate,
    quantum_teleport,
    raid,
    repopulate,
    stash,
    withdraw,
)

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


@router.post("/dig-deeper", status_code=status.HTTP_201_CREATED)
async def do_dig_deeper(
    body: BunkerDigRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """SDD 69 Fase 1: excavar para agrandar la grilla del búnker (+1 lado)."""
    try:
        b = await dig_deeper(session, player, body.base_id)
    except BunkerError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return {"id": b.id, "base_id": b.base_id, "grid_level": b.grid_level}


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


@router.post("/stash", status_code=status.HTTP_201_CREATED)
async def do_stash(
    body: BunkerVaultRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """SDD 69: guardar mineral de la superficie en la bóveda (a salvo del saqueo)."""
    try:
        result = await stash(session, player, body.base_id, body.mineral, body.amount)
    except BunkerError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return result


@router.post("/withdraw", status_code=status.HTTP_201_CREATED)
async def do_withdraw(
    body: BunkerVaultRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """SDD 69: sacar mineral de la bóveda a la superficie."""
    try:
        result = await withdraw(session, player, body.base_id, body.mineral, body.amount)
    except BunkerError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return result


@router.post("/teleport", status_code=status.HTTP_201_CREATED)
async def do_teleport(
    body: QuantumTeleportRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """SDD 76: teletransportar electrónica de un búnker a otro (necesita Puerta cuántica activa)."""
    try:
        result = await quantum_teleport(
            session, player, body.from_base_id, body.to_base_id, body.amount
        )
    except BunkerError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return result


@router.post("/evolve-ai", status_code=status.HTTP_201_CREATED)
async def do_evolve_ai(
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """SDD 69 Fase 4: subir 1 nivel la vida artificial (gasta electrónica + minerales)."""
    from app.services.ai_life import AiLifeError, evolve_ai
    try:
        result = await evolve_ai(session, player)
    except AiLifeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return result


@router.post("/ai-autopilot")
async def do_ai_autopilot(
    body: dict,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """SDD 69 Fase 4: prender/parar el autopiloto (botón de emergencia). body: {on: bool}."""
    player.ai_autopilot_on = bool(body.get("on", True))
    await session.commit()
    return {"autopilot_on": player.ai_autopilot_on}


@router.post("/evacuate", status_code=status.HTTP_201_CREATED)
async def do_evacuate(
    body: BunkerEvacuateRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """SDD 69 Fase 3: evacuar → fundar una colonia (colony_ship) y sembrarla desde la bóveda."""
    try:
        result = await evacuate(session, player, body.base_id, body.target_planet, body.minerals)
    except BunkerError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return result


@router.post("/repopulate", status_code=status.HTTP_201_CREATED)
async def do_repopulate(
    body: RepopulateRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """SDD 64 v2: gastá electrónica del búnker para reconstruir un set de edificios."""
    try:
        result = await repopulate(session, player, body.base_id, body.set_key)
    except BunkerError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return result


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
