"""Endpoints PÚBLICOS sin auth (SDD 12): alimentan el showcase de la página de login.

Solo agregados + username (nunca email ni datos de cuenta). Pensados para cachear (SDD 7)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas import (
    GlobalStatsOut,
    HallOfFameEntryOut,
    PlayerStatsOut,
    PublicLeaderboardEntryOut,
    PublicProfileOut,
    SeasonOut,
)
from app.services import stats as svc
from app.services.seasons import hall_of_fame

router = APIRouter()


@router.get("/stats", response_model=GlobalStatsOut)
async def global_stats(session: AsyncSession = Depends(get_session)):
    g = await svc.global_stats(session)
    s = g.pop("season")
    season = (
        SeasonOut(id=s.id, seq=s.seq, name=s.name, starts_at=s.starts_at,
                  ends_at=s.ends_at, status=s.status)
        if s else None
    )
    return GlobalStatsOut(season=season, **g)


@router.get("/leaderboard", response_model=list[PublicLeaderboardEntryOut])
async def leaderboard(session: AsyncSession = Depends(get_session)):
    return [
        PublicLeaderboardEntryOut(rank=rank, username=p.username, race_key=p.race_key, score=score)
        for rank, p, score in await svc.leaderboard(session, 20)
    ]


@router.get("/hall-of-fame", response_model=list[HallOfFameEntryOut])
async def public_hof(season_id: int | None = None, session: AsyncSession = Depends(get_session)):
    rows = await hall_of_fame(session, season_id)
    return [
        HallOfFameEntryOut(season_id=r.season_id, rank=r.rank, username=r.username,
                           points=r.points, awarded_at=r.awarded_at)
        for r in rows
    ]


@router.get("/players/{username}", response_model=PublicProfileOut)
async def public_profile(username: str, session: AsyncSession = Depends(get_session)):
    prof = await svc.player_profile(session, username)
    if prof is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Jugador no encontrado")
    prof["stats"] = PlayerStatsOut(**prof["stats"])
    prof["season_history"] = [
        HallOfFameEntryOut(season_id=h.season_id, rank=h.rank, username=h.username,
                           points=h.points, awarded_at=h.awarded_at)
        for h in prof["season_history"]
    ]
    return PublicProfileOut(**prof)
