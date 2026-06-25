"""Meta-insights (SDD 41): mina el journal (SDD 38) para que la IA aprenda el meta real.

Determinista (SQL/agregación), no entrena nada. Calcula win-rates por composición desde
`battle_resolved` y los guarda en `MetaInsight` (upsert por key). El asistente y los NPCs leen
`meta_summary_text` → juegan/aconsejan con datos. Tolerante a cambios del juego: agrupa por las
claves que hay en los datos (no hardcodea unidades) y cada evento está versionado (SDD 41) para
poder segmentar por ruleset cuando cambie el balance.
"""
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import GameEvent, MetaInsight


async def _upsert(session: AsyncSession, key: str, payload: dict, sample_n: int) -> None:
    row = await session.get(MetaInsight, key)
    if row is None:
        row = MetaInsight(key=key)
        session.add(row)
    row.payload = json.dumps(payload)
    row.sample_n = sample_n
    row.updated_at = datetime.now(UTC)


async def compute_meta(
    session: AsyncSession, now: datetime | None = None, version: str | None = None
) -> dict:
    """Recalcula el meta desde `battle_resolved`. `version` opcional para segmentar por ruleset
    (None = todas). v1 recorre todo; con escala se ventana/incrementa por `seq` (ver SDD 41 §5)."""
    now = now or datetime.now(UTC)
    stmt = select(GameEvent).where(GameEvent.type == "battle_resolved")
    if version:
        stmt = stmt.where(GameEvent.version == version)
    total = wins = 0
    by_unit: dict[str, list[int]] = {}   # unidad dominante -> [wins, n]
    for e in (await session.execute(stmt)).scalars():
        p = json.loads(e.payload or "{}")
        force = p.get("force") or {}
        if not force:
            continue
        won = p.get("outcome") == "attacker"
        total += 1
        wins += 1 if won else 0
        dominant = max(force, key=lambda k: force[k])   # tolerante: cualquier clave de unidad
        wn = by_unit.setdefault(dominant, [0, 0])
        wn[0] += 1 if won else 0
        wn[1] += 1

    await _upsert(session, "attack_winrate",
                  {"rate": round(wins / total, 3) if total else None, "n": total}, total)
    await _upsert(session, "winrate_by_unit",
                  {u: {"rate": round(w / n, 3), "n": n} for u, (w, n) in by_unit.items()}, total)
    await _upsert(session, "_computed_at", {"at": now.isoformat()}, total)
    return {"battles": total}


async def should_recompute(session: AsyncSession, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    row = await session.get(MetaInsight, "_computed_at")
    if row is None:
        return True
    try:
        last = datetime.fromisoformat(json.loads(row.payload)["at"])
    except Exception:
        return True
    last = last if last.tzinfo else last.replace(tzinfo=UTC)
    return (now - last).total_seconds() >= get_settings().meta_compute_interval_seconds


async def get_insights(session: AsyncSession) -> dict:
    rows = (await session.execute(select(MetaInsight))).scalars()
    return {
        r.key: {
            "payload": json.loads(r.payload or "{}"),
            "n": r.sample_n,
            "updated_at": r.updated_at,
        }
        for r in rows
    }


async def meta_summary_text(session: AsyncSession) -> str:
    """Texto corto del meta para el prompt del LLM (vacío si no hay datos suficientes)."""
    rows = {r.key: json.loads(r.payload or "{}")
            for r in (await session.execute(select(MetaInsight))).scalars()}
    aw = rows.get("attack_winrate", {})
    if not aw.get("rate"):
        return ""
    parts = [f"los ataques ganan {round(aw['rate'] * 100)}% (n={aw.get('n', 0)})"]
    by_unit = rows.get("winrate_by_unit", {})
    top = sorted(by_unit.items(), key=lambda kv: -kv[1]["rate"])[:3]
    if top:
        parts.append("mejores flotas por unidad dominante: " + ", ".join(
            f"{u} {round(v['rate'] * 100)}% (n={v['n']})" for u, v in top))
    return "Meta actual (datos reales de partidas): " + "; ".join(parts) + "."
