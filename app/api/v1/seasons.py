"""Temporadas + Hall of Fame (SDD 11). Lecturas autenticadas; el showcase público es del SDD 12."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player
from app.core.db import get_session
from app.models import Player, Season
from app.schemas import HallOfFameEntryOut, SeasonOut, SeasonRankingEntryOut
from app.services import seasons as svc

router = APIRouter()


def _season_out(s: Season) -> SeasonOut:
    return SeasonOut(
        id=s.id, seq=s.seq, name=s.name, starts_at=s.starts_at, ends_at=s.ends_at, status=s.status
    )


@router.get("")
async def list_seasons(
    _: Player = Depends(get_current_player), session: AsyncSession = Depends(get_session)
):
    """Temporada actual + recientes (para countdown e historial)."""
    await svc.ensure_active_season(session)
    await session.commit()
    current = await svc.current_season(session)
    recent = (
        await session.execute(select(Season).order_by(Season.seq.desc()).limit(10))
    ).scalars()
    return {
        "current": _season_out(current) if current else None,
        "recent": [_season_out(s) for s in recent],
    }


@router.get("/current/ranking", response_model=list[SeasonRankingEntryOut])
async def current_ranking(
    _: Player = Depends(get_current_player), session: AsyncSession = Depends(get_session)
):
    ranking = await svc.season_ranking(session, 100)
    return [
        SeasonRankingEntryOut(rank=rank, player_id=p.id, username=p.username, score=score)
        for rank, p, score in ranking
    ]


@router.get("/hall-of-fame", response_model=list[HallOfFameEntryOut])
async def hall_of_fame(
    season_id: int | None = None,
    _: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    rows = await svc.hall_of_fame(session, season_id)
    return [
        HallOfFameEntryOut(
            season_id=r.season_id, rank=r.rank, username=r.username,
            points=r.points, awarded_at=r.awarded_at,
        )
        for r in rows
    ]
