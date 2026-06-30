"""Personal AI assistant endpoints (SDD 2): advise the player and the capped emergency hack."""
from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player, lock_current_player
from app.core.config import get_settings
from app.core.db import get_session
from app.core.redis import get_redis, rate_limited
from app.models import Player
from app.schemas import (
    AdvisorAskRequest,
    AdvisorHackRequest,
    AdvisorHackResult,
    AdvisorMessageOut,
    AdvisorReply,
    AssistEnergyResult,
)
from app.services import advisor

router = APIRouter()


@router.post("/ask", response_model=AdvisorReply)
async def ask(
    body: AdvisorAskRequest,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
    redis: Redis | None = Depends(get_redis),
):
    # Rate-limit por jugador (SDD 9): la IA es serial (una GPU = una cola); protege contra
    # el pico de "todos preguntan a la vez". El LLM siempre tiene fallback determinista.
    limit = get_settings().advisor_rate_limit_per_min
    if await rate_limited(redis, f"rl:advisor:{player.id}", limit, 60):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Demasiadas consultas al asistente; espera un momento.",
        )
    try:
        return await advisor.ask(
            session, player, body.message, mode=body.model_mode,
            byok_key=body.byok_key, byok_model=body.byok_model, byok_base_url=body.byok_base_url,
        )
    except advisor.AdvisorError as e:
        raise HTTPException(e.status, str(e)) from e


@router.post("/hack", response_model=AdvisorHackResult)
async def hack(
    body: AdvisorHackRequest,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await advisor.grant_hack(session, player, body.target, body.target_mineral)
    except advisor.AdvisorError as e:
        raise HTTPException(e.status, str(e)) from e


@router.post("/assist-energy", response_model=AssistEnergyResult)
async def assist_energy(
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Energía de nivelado por ranking (SDD 40): los 3 últimos llenan el pool; el resto +100."""
    try:
        return await advisor.grant_assist_energy(session, player)
    except advisor.AdvisorError as e:
        raise HTTPException(e.status, str(e)) from e


@router.get("/messages", response_model=list[AdvisorMessageOut])
async def messages(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    return await advisor.list_messages(session, player)
