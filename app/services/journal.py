"""Journal de eventos append-only (SDD 38): un solo punto que **registra y mide**.

`record()` agrega un `GameEvent` (orden total por `id`) y bumpea la métrica Prometheus del tipo
→ medir todo en Grafana + exportar la partida a YAML + reproducirla (replay determinista).
No commitea: corre en la misma transacción que la acción (consistencia: si la acción se revierte,
el evento también).
"""
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.config import get_settings
from app.models import GameEvent


async def record(
    session: AsyncSession, type_: str, player_id: int | None = None, **payload
) -> None:
    session.add(GameEvent(
        type=type_, player_id=player_id, payload=json.dumps(payload),
        version=get_settings().app_version,   # SDD 41: tag de versión para segmentar el meta
    ))
    metrics.JOURNAL_EVENTS.inc(kind=type_)


async def list_events(
    session: AsyncSession, player_id: int | None = None, since: int = 0, limit: int = 200
) -> list[GameEvent]:
    """Eventos en orden (seq). `player_id=None` = toda la partida (uso admin/export)."""
    stmt = select(GameEvent).where(GameEvent.id > since)
    if player_id is not None:
        stmt = stmt.where(GameEvent.player_id == player_id)
    stmt = stmt.order_by(GameEvent.id).limit(min(max(limit, 1), 5000))
    return list((await session.execute(stmt)).scalars())


def to_dict(ev: GameEvent) -> dict:
    return {
        "seq": ev.id,
        "at": ev.created_at,
        "player_id": ev.player_id,
        "type": ev.type,
        "payload": json.loads(ev.payload or "{}"),
    }
