from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player
from app.core.db import get_session
from app.models import Base_, Player
from app.schemas import OnboardRequest, PlayerStateOut, PlayerSummaryOut, RankingEntryOut
from app.services.onboarding import OnboardingError, onboard_player
from app.services.scoring import player_score
from app.services.state import advance, snapshot

router = APIRouter()


@router.get("/ranking", response_model=list[RankingEntryOut])
async def ranking(
    _: Player = Depends(get_current_player), session: AsyncSession = Depends(get_session)
):
    """Leaderboard: score = edificios + poder militar + minerales + techs + victorias."""
    res = await session.execute(select(Player).where(Player.race_key.is_not(None)))
    entries = [(await player_score(session, p), p) for p in res.scalars()]
    entries.sort(key=lambda x: x[0], reverse=True)
    return [
        RankingEntryOut(
            rank=i + 1, id=p.id, username=p.username, race_key=p.race_key,
            is_npc=p.is_npc, score=score,
        )
        for i, (score, p) in enumerate(entries)
    ]


@router.get("", response_model=list[PlayerSummaryOut])
async def list_players(
    _: Player = Depends(get_current_player), session: AsyncSession = Depends(get_session)
):
    """Scoreboard: all onboarded players (incl. NPCs) with a base to target."""
    res = await session.execute(select(Player).where(Player.race_key.is_not(None)))
    out: list[PlayerSummaryOut] = []
    for p in res.scalars():
        bres = await session.execute(select(Base_.id).where(Base_.player_id == p.id).limit(1))
        out.append(
            PlayerSummaryOut(
                id=p.id,
                username=p.username,
                race_key=p.race_key,
                planet_key=p.planet_key,
                is_npc=p.is_npc,
                home_base_id=bres.scalar_one_or_none(),
                alliance_id=p.alliance_id,
            )
        )
    return out


@router.get("/me", response_model=PlayerStateOut)
async def get_me(
    player: Player = Depends(get_current_player), session: AsyncSession = Depends(get_session)
):
    if player.race_key is not None:
        await advance(session, player)
    return await snapshot(session, player)


@router.post("/onboard", response_model=PlayerStateOut, status_code=status.HTTP_201_CREATED)
async def onboard(
    body: OnboardRequest,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    try:
        await onboard_player(session, player, body.galaxy_key, body.planet_key, body.race_key)
    except OnboardingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return await snapshot(session, player)
