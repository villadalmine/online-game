"""Métricas de por vida + showcase público (SDD 12).

`bump` incrementa contadores en los procesadores existentes (combate, build, train, research,
expedición, minería). El historial de temporadas sale del `HallOfFame` (SDD 11). Las lecturas
públicas (`/public/*`) exponen solo agregados + username (nunca email).
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Base_, CombatLog, HallOfFame, Player, PlayerStats
from app.services.scoring import player_score

_COUNTERS = (
    "battles_won", "battles_lost", "attacks_launched", "buildings_built", "units_trained",
    "research_completed", "expeditions_completed", "resources_mined", "resources_looted",
    "resources_lost",
)


async def get_or_create(session: AsyncSession, player_id: int) -> PlayerStats:
    st = await session.get(PlayerStats, player_id)
    if st is None:
        st = PlayerStats(player_id=player_id)
        session.add(st)
        await session.flush()
    return st


async def bump(session: AsyncSession, player_id: int, **counters: float) -> None:
    """Suma a los contadores indicados (crea la fila si no existe). No commitea."""
    st = await get_or_create(session, player_id)
    for key, val in counters.items():
        if val:
            setattr(st, key, (getattr(st, key) or 0) + val)


def stats_dict(st: PlayerStats | None) -> dict:
    return {k: (getattr(st, k) if st else 0) for k in _COUNTERS}


async def season_history(session: AsyncSession, player_id: int) -> list[HallOfFame]:
    res = await session.execute(
        select(HallOfFame)
        .where(HallOfFame.player_id == player_id)
        .order_by(HallOfFame.season_id.desc())
    )
    return list(res.scalars())


async def leaderboard(session: AsyncSession, limit: int = 20) -> list[tuple[int, Player, int]]:
    res = await session.execute(
        select(Player).where(Player.is_npc.is_(False), Player.race_key.is_not(None))
    )
    scored = [(await player_score(session, p), p) for p in res.scalars()]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(i + 1, p, s) for i, (s, p) in enumerate(scored[:limit])]


async def global_stats(session: AsyncSession) -> dict:
    from app.services.seasons import current_season

    players = (
        await session.execute(
            select(func.count())
            .select_from(Player)
            .where(Player.is_npc.is_(False), Player.race_key.is_not(None))
        )
    ).scalar_one()
    empires = (
        await session.execute(select(func.count()).select_from(Base_))
    ).scalar_one()
    battles = (
        await session.execute(select(func.count()).select_from(CombatLog))
    ).scalar_one()
    minerals_mined = (
        await session.execute(select(func.coalesce(func.sum(PlayerStats.resources_mined), 0)))
    ).scalar_one()
    return {
        "players": int(players),
        "empires": int(empires),
        "battles": int(battles),
        "minerals_mined": round(float(minerals_mined), 1),
        "season": await current_season(session),
    }


async def player_profile(session: AsyncSession, username: str) -> dict | None:
    player = (
        await session.execute(select(Player).where(Player.username == username))
    ).scalar_one_or_none()
    if player is None or player.race_key is None:
        return None
    st = await session.get(PlayerStats, player.id)
    history = await season_history(session, player.id)
    return {
        "username": player.username,
        "race_key": player.race_key,
        "planet_key": player.planet_key,
        "is_npc": player.is_npc,
        "score": await player_score(session, player),
        "stats": stats_dict(st),
        "seasons_played": len(history),
        "best_rank": min((h.rank for h in history), default=None),
        "hof_count": len(history),
        "season_history": history,
    }
