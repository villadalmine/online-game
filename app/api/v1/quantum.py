"""SDD 87: desactivar una infección de bomba cuántica (tropas | rescate | tech cuántica)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import lock_current_player
from app.core.db import get_session
from app.models import Player
from app.services.quantum import (
    QuantumError,
    disarm_with_quantum,
    disarm_with_ransom,
    disarm_with_troops,
)

router = APIRouter()


async def _disarm(fn, body: dict, player: Player, session: AsyncSession) -> dict:
    try:
        base_id = int(body.get("base_id"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Falta base_id.") from exc
    try:
        r = await fn(session, player, base_id)
    except QuantumError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return r


@router.post("/disarm/troops")
async def disarm_troops(body: dict, player: Player = Depends(lock_current_player),
                        session: AsyncSession = Depends(get_session)):
    """Purga el gusano mandando tropas (consume soldados de la base)."""
    return await _disarm(disarm_with_troops, body, player, session)


@router.post("/disarm/ransom")
async def disarm_ransom(body: dict, player: Player = Depends(lock_current_player),
                        session: AsyncSession = Depends(get_session)):
    """Paga el chantaje (transfiere recursos al atacante)."""
    return await _disarm(disarm_with_ransom, body, player, session)


@router.post("/disarm/quantum")
async def disarm_quantum(body: dict, player: Player = Depends(lock_current_player),
                         session: AsyncSession = Depends(get_session)):
    """Con `quantum_warfare`: desactiva gratis, pero deja fuga de info hasta poner un inhibidor."""
    return await _disarm(disarm_with_quantum, body, player, session)
