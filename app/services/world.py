"""World events: a public, read-only feed of notable things happening in the galaxy.
Derived from already-persisted data (battles + alliances) — no extra storage."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alliance, CombatLog, Player


def _battle_message(attacker: str, defender: str, outcome: str, base_id: int) -> str:
    verb = {
        "attacker": f"⚔ {attacker} conquistó a {defender}",
        "defender": f"🛡 {defender} repelió el ataque de {attacker}",
        "draw": f"⚔ {attacker} y {defender} empataron",
    }.get(outcome, f"⚔ {attacker} atacó a {defender}")
    return f"{verb} (base #{base_id})"


async def world_events(session: AsyncSession, limit: int = 30) -> list[dict]:
    """The most recent battles and alliance formations, newest-first."""
    logs = (
        (await session.execute(select(CombatLog).order_by(CombatLog.id.desc()).limit(limit)))
        .scalars()
        .all()
    )
    ids = {x.attacker_id for x in logs} | {x.defender_id for x in logs}
    names: dict[int, str] = {}
    if ids:
        rows = (await session.execute(select(Player).where(Player.id.in_(ids)))).scalars()
        names = {p.id: p.username for p in rows}

    events: list[dict] = []
    for log in logs:
        events.append(
            {
                "type": "battle",
                "message": _battle_message(
                    names.get(log.attacker_id, "?"),
                    names.get(log.defender_id, "?"),
                    log.outcome,
                    log.target_base_id,
                ),
                "created_at": log.created_at,
            }
        )

    alliances = (
        (await session.execute(select(Alliance).order_by(Alliance.id.desc()).limit(limit)))
        .scalars()
        .all()
    )
    for a in alliances:
        events.append(
            {
                "type": "alliance",
                "message": f"🤝 Se formó la alianza [{a.tag}] {a.name}",
                "created_at": a.created_at,
            }
        )

    events.sort(key=lambda e: e["created_at"], reverse=True)
    return events[:limit]
