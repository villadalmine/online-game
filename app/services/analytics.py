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


async def combat_summary(
    session: AsyncSession, player_id: int, hours: float = 24.0
) -> dict:
    """SDD 71: cómo van MIS ataques y defensas (del `CombatLog`, per-jugador) en la ventana.
    Ataque: yo soy `attacker_id` (gané si outcome=='attacker'). Defensa: yo soy `defender_id`
    (gané si outcome=='defender'). Devuelve totales + botín ganado/perdido + serie por hora."""
    from app.models import CombatLog
    now = datetime.now(UTC)
    since = now - timedelta(hours=hours)
    rows = list((await session.execute(
        select(CombatLog).where(
            CombatLog.created_at >= since,
            CombatLog.outcome.in_(("attacker", "defender", "draw")),
            (CombatLog.attacker_id == player_id) | (CombatLog.defender_id == player_id),
        ).order_by(CombatLog.created_at)
    )).scalars())
    out = {"atk_won": 0, "atk_lost": 0, "def_won": 0, "def_lost": 0,
           "loot_gained": 0.0, "loot_lost": 0.0}
    buckets = max(1, min(24, int(hours)))          # ~1 barra por hora (tope 24)
    span = (hours * 3600.0) / buckets
    series = [{"atk": 0, "def": 0} for _ in range(buckets)]
    for r in rows:
        iam_atk = r.attacker_id == player_id
        try:
            loot = sum(float(v) for v in json.loads(r.details or "{}").get("loot", {}).values())
        except (ValueError, TypeError):
            loot = 0.0
        idx = min(buckets - 1, int(((_aware(r.created_at) - since).total_seconds()) / span))
        if iam_atk:
            series[idx]["atk"] += 1
            if r.outcome == "attacker":
                out["atk_won"] += 1
                out["loot_gained"] += loot
            elif r.outcome == "defender":
                out["atk_lost"] += 1
        else:   # yo defiendo
            series[idx]["def"] += 1
            if r.outcome == "defender":
                out["def_won"] += 1
            elif r.outcome == "attacker":
                out["def_lost"] += 1
                out["loot_lost"] += loot
    out["loot_gained"] = round(out["loot_gained"], 1)
    out["loot_lost"] = round(out["loot_lost"], 1)
    out["series"] = series
    return out


async def ai_activity(
    session: AsyncSession, player_id: int, hours: float = 24.0
) -> dict:
    """SDD 69: qué hicieron TUS robots (autopiloto de vida artificial) en la ventana, del journal
    (`ai_autopilot`, payload `action`/`qty`). Desglose por acción → 'cómo labura tu IA' in-app,
    sin depender de Grafana (per-jugador, del mismo journal que ya alimenta la métrica global)."""
    now = datetime.now(UTC)
    since = now - timedelta(hours=hours)
    rows = list((await session.execute(
        select(GameEvent.payload).where(
            GameEvent.player_id == player_id, GameEvent.type == "ai_autopilot",
            GameEvent.created_at >= since,
        )
    )).all())
    by_action: dict[str, dict] = {}
    for (payload,) in rows:
        try:
            p = json.loads(payload or "{}")
        except (ValueError, TypeError):
            p = {}
        a = str(p.get("action") or "otro")
        d = by_action.setdefault(a, {"count": 0, "qty": 0})
        d["count"] += 1
        try:
            d["qty"] += int(p.get("qty") or 0)
        except (ValueError, TypeError):
            pass
    return {"total": len(rows), "by_action": by_action}


async def llm_usage(
    session: AsyncSession, player_id: int, hours: float = 24.0
) -> dict:
    """SDD 71: TU uso de IA (asistente) en la ventana, del journal (`advisor_ask`, payload `mode`).
    Desglosa por ruta gpu/cloud/byok/hack + serie por hora. Es tu consumo real de GPU (per-jugador,
    sin el problema de las 3 réplicas del /metrics del proceso)."""
    now = datetime.now(UTC)
    since = now - timedelta(hours=hours)
    rows = list((await session.execute(
        select(GameEvent.created_at, GameEvent.payload).where(
            GameEvent.player_id == player_id, GameEvent.type == "advisor_ask",
            GameEvent.created_at >= since,
        )
    )).all())
    by_mode: dict[str, int] = {}
    buckets = max(1, min(24, int(hours)))
    span = (hours * 3600.0) / buckets
    series = [0 for _ in range(buckets)]
    for at, payload in rows:
        try:
            mode = (json.loads(payload or "{}").get("mode")) or "gpu"
        except (ValueError, TypeError):
            mode = "gpu"
        by_mode[mode] = by_mode.get(mode, 0) + 1
        idx = min(buckets - 1, int(((_aware(at) - since).total_seconds()) / span))
        series[idx] += 1
    return {"total": len(rows), "by_mode": by_mode, "series": series}
