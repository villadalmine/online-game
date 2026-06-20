"""Player scoring, shared by the player ranking and the alliance ranking."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.models import Base_, Building, CombatLog, Player, PlayerTech, ResourceStock, UnitStock


async def player_score(session: AsyncSession, player: Player) -> int:
    content = get_content()
    buildings = (await session.execute(
        select(Building).join(Base_, Building.base_id == Base_.id)
        .where(Base_.player_id == player.id)
    )).scalars().all()
    units = (await session.execute(
        select(UnitStock).where(UnitStock.player_id == player.id)
    )).scalars().all()
    minerals = (await session.execute(
        select(ResourceStock).where(ResourceStock.player_id == player.id)
    )).scalars().all()
    techs = (await session.execute(
        select(PlayerTech).where(PlayerTech.player_id == player.id)
    )).scalars().all()
    wins = (await session.execute(
        select(CombatLog).where(CombatLog.attacker_id == player.id, CombatLog.outcome == "attacker")
    )).scalars().all()
    power = sum(
        u.quantity * content.units.get(u.unit_key, {}).get("stats", {}).get("attack", 0)
        for u in units
    )
    return (
        len(buildings) * 5
        + int(power)
        + int(sum(m.amount for m in minerals) / 50)
        + len(techs) * 30
        + len(wins) * 15
    )
