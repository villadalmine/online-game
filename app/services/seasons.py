"""Temporadas (SDD 11): mundo persistente + ventanas de tiempo con ganadores y Hall of Fame.

Al cerrar una temporada se toma una foto del ranking (por `scoring.player_score`), los top N
entran al `HallOfFame` (persiste para siempre) y se abre la siguiente. **El imperio no se toca.**
El leaderboard "en vivo" se computa con `player_score` (como el ranking existente); los puntos de
temporada acumulables quedan como follow-up.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import HallOfFame, Player, Season
from app.services.scoring import player_score


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def current_season(session: AsyncSession) -> Season | None:
    res = await session.execute(
        select(Season).where(Season.status == "active").order_by(Season.seq.desc()).limit(1)
    )
    return res.scalar_one_or_none()


async def ensure_active_season(session: AsyncSession, now: datetime | None = None) -> Season:
    """Devuelve la temporada activa; si no hay, crea la siguiente (seq+1)."""
    now = now or datetime.now(UTC)
    active = await current_season(session)
    if active is not None:
        return active
    settings = get_settings()
    max_seq = (await session.execute(select(func.max(Season.seq)))).scalar() or 0
    seq = int(max_seq) + 1
    season = Season(
        seq=seq,
        name=f"Temporada {seq}",
        starts_at=now,
        ends_at=now + timedelta(days=settings.season_days),
        status="active",
    )
    session.add(season)
    await session.flush()
    return season


async def season_ranking(session: AsyncSession, limit: int = 100) -> list[tuple[int, Player, int]]:
    """Ranking en vivo (humanos con imperio) por player_score, como (rank, player, score)."""
    res = await session.execute(
        select(Player).where(Player.is_npc.is_(False), Player.race_key.is_not(None))
    )
    scored = [(await player_score(session, p), p) for p in res.scalars()]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(i + 1, p, s) for i, (s, p) in enumerate(scored[:limit])]


async def _close_one(session: AsyncSession, season: Season, now: datetime) -> int:
    """Cierra una temporada: snapshot del top N al Hall of Fame + status=closed. Devuelve N."""
    from app.services.notifications import notify

    top = get_settings().season_hall_of_fame_top
    ranking = await season_ranking(session, top)
    for rank, player, score in ranking:
        session.add(
            HallOfFame(
                season_id=season.id,
                player_id=player.id,
                username=player.username,
                rank=rank,
                points=score,
            )
        )
        # avisá a cada premiado (llega por notificaciones + SSE)
        await notify(
            session, player.id, "season_end",
            f"🏆 {season.name} cerró — terminaste #{rank} (entrás al Hall of Fame).",
            {"season_id": season.id, "rank": rank, "points": score},
        )
    season.status = "closed"
    await session.flush()
    return len(ranking)


async def close_due_seasons(session: AsyncSession, now: datetime | None = None) -> int:
    """Cierra temporadas vencidas y abre la siguiente. Devuelve cuántas cerró."""
    now = now or datetime.now(UTC)
    res = await session.execute(select(Season).where(Season.status == "active"))
    closed = 0
    for season in res.scalars():
        if _aware(season.ends_at) <= now:
            await _close_one(session, season, now)
            closed += 1
    if closed:
        await ensure_active_season(session, now)
    return closed


async def close_current_now(session: AsyncSession) -> int:
    """Fuerza el cierre de la temporada activa ya (admin/tests) y abre la siguiente."""
    now = datetime.now(UTC)
    active = await current_season(session)
    if active is None:
        return 0
    await _close_one(session, active, now)
    await ensure_active_season(session, now)
    return 1


async def hall_of_fame(
    session: AsyncSession, season_id: int | None = None, limit: int = 50
) -> list[HallOfFame]:
    stmt = select(HallOfFame)
    if season_id is not None:
        stmt = stmt.where(HallOfFame.season_id == season_id)
    stmt = stmt.order_by(HallOfFame.season_id.desc(), HallOfFame.rank.asc()).limit(limit)
    return list((await session.execute(stmt)).scalars())
