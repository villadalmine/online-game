"""Feed de batallas (historial de combates) compartido por el panel general y el de admin.

Deriva de `CombatLog` (ya persistido) — no guarda nada nuevo. **No expone unidades ni bajas**
(SDD 35: la composición/fuerza de un ejército es intel que se consigue espiando, no mirando el
feed); sí muestra quién atacó a quién, de qué planeta a cuál, el resultado y el botín (minerales).
"""
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Base_, CombatLog, Player


async def battles_feed(session: AsyncSession, limit: int = 50) -> list[dict]:
    rows = (await session.execute(
        select(CombatLog).order_by(CombatLog.created_at.desc()).limit(limit)
    )).scalars().all()
    pids = {r.attacker_id for r in rows} | {r.defender_id for r in rows}
    players: dict[int, dict] = {}
    if pids:
        for p in (await session.execute(select(Player).where(Player.id.in_(pids)))).scalars():
            players[p.id] = {"username": p.username, "is_npc": p.is_npc, "planet": p.planet_key}
    bids = {r.target_base_id for r in rows}
    base_planet: dict[int, str] = {}
    if bids:
        for b in (await session.execute(select(Base_).where(Base_.id.in_(bids)))).scalars():
            base_planet[b.id] = b.planet_key
    out: list[dict] = []
    for r in rows:
        d = json.loads(r.details or "{}")
        atk = players.get(r.attacker_id, {})
        dfn = players.get(r.defender_id, {})
        winner_id = r.attacker_id if r.outcome == "attacker" else (
            r.defender_id if r.outcome == "defender" else None)
        out.append({
            "id": r.id,
            "created_at": r.created_at,
            "attacker": atk.get("username", f"#{r.attacker_id}"),
            "attacker_is_npc": atk.get("is_npc", False),
            "defender": dfn.get("username", f"#{r.defender_id}"),
            "defender_is_npc": dfn.get("is_npc", False),
            "from_planet": atk.get("planet"),                # origen (planeta del atacante)
            "to_planet": base_planet.get(r.target_base_id),  # destino (base atacada)
            "outcome": r.outcome,                            # attacker | defender | draw
            "winner_id": winner_id,
            "loot_total": round(sum((d.get("loot") or {}).values()), 2),  # minerales (no unidades)
        })
    return out
