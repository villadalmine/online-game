"""SDD 51 — Analítica por jugador: muestreo de estado + series temporales para gráficos in-app.

`sample_player()` guarda una foto del estado (energía/stock/unidades/score) con throttle (lazy, sin
cron), llamada desde `state.advance`. Las consultas (`history`, `event_counts`) alimentan el modal
"📈 Tu historia" y, vía SQL datasource, Grafana. Los EVENTOS ya salen del journal (SDD 38); esto
cubre el ESTADO, que no es un evento. Determinista, sin LLM.
"""
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import GameEvent, Player, PlayerSample


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def sample_player(session: AsyncSession, player: Player, now: datetime | None = None) -> bool:
    """Guarda una muestra del estado del jugador si pasó `analytics_sample_seconds` desde la última.
    Devuelve True si muestreó. Se llama al final de state.advance (estado ya al día)."""
    s = get_settings()
    if not s.analytics_enabled:
        return False
    now = now or datetime.now(UTC)
    last = (await session.execute(
        select(func.max(PlayerSample.at)).where(PlayerSample.player_id == player.id)
    )).scalar_one_or_none()
    if last is not None and (now - _aware(last)).total_seconds() < s.analytics_sample_seconds:
        return False

    from app.services.economy import player_stocks
    from app.services.physics import effective_energy_max
    from app.services.scoring import player_score
    from app.services.training import player_units

    stocks = await player_stocks(session, player.id)
    units = await player_units(session, player.id)
    session.add(PlayerSample(
        player_id=player.id, at=now,
        energy=round(player.energy, 2), energy_max=round(effective_energy_max(player, s), 2),
        stock_total=round(sum(stocks.values()), 2), units_total=int(sum(units.values())),
        score=int(await player_score(session, player)),
        stocks_json=json.dumps({k: round(v, 2) for k, v in stocks.items()}),
        units_json=json.dumps(units),
    ))
    return True


async def history(
    session: AsyncSession, player_id: int, hours: float = 24.0, max_points: int = 240
) -> list[dict]:
    """Serie temporal del estado (últimas `hours`), downsampleada a ~`max_points` puntos."""
    now = datetime.now(UTC)
    rows = list((await session.execute(
        select(PlayerSample)
        .where(PlayerSample.player_id == player_id,
               PlayerSample.at >= now - timedelta(hours=hours))
        .order_by(PlayerSample.at)
    )).scalars())
    step = max(1, len(rows) // max_points)
    out = []
    for i, r in enumerate(rows):
        if i % step and i != len(rows) - 1:
            continue
        out.append({
            "at": r.at.isoformat(), "energy": r.energy, "energy_max": r.energy_max,
            "stock_total": r.stock_total, "units_total": r.units_total, "score": r.score,
        })
    return out


async def event_counts(
    session: AsyncSession, player_id: int, hours: float = 24.0
) -> dict[str, int]:
    """Conteo de acciones por tipo (del journal, SDD 38) en la ventana → barras de 'qué hiciste'."""
    now = datetime.now(UTC)
    rows = (await session.execute(
        select(GameEvent.type, func.count())
        .where(GameEvent.player_id == player_id,
               GameEvent.created_at >= now - timedelta(hours=hours))
        .group_by(GameEvent.type)
    )).all()
    return {t: int(n) for t, n in rows}
