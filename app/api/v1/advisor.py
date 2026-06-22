"""Personal AI assistant endpoints (SDD 2): advise the player and the capped emergency hack."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player
from app.core.db import get_session
from app.models import Player
from app.schemas import (
    AdvisorAskRequest,
    AdvisorHackRequest,
    AdvisorHackResult,
    AdvisorMessageOut,
    AdvisorReply,
)
from app.services import advisor

router = APIRouter()


@router.post("/ask", response_model=AdvisorReply)
async def ask(
    body: AdvisorAskRequest,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await advisor.ask(session, player, body.message)
    except advisor.AdvisorError as e:
        raise HTTPException(e.status, str(e)) from e


@router.post("/hack", response_model=AdvisorHackResult)
async def hack(
    body: AdvisorHackRequest,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await advisor.grant_hack(session, player, body.target)
    except advisor.AdvisorError as e:
        raise HTTPException(e.status, str(e)) from e


@router.get("/messages", response_model=list[AdvisorMessageOut])
async def messages(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    return await advisor.list_messages(session, player)
