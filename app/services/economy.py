"""Resource stocks + lazy mine collection + build finalization."""
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.models import Base_, Building, Player, ResourceStock
from app.services.production import compute_mine_output


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    """SQLite drops tzinfo; treat naive timestamps as UTC for safe comparison."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def get_or_create_stock(
    session: AsyncSession, player_id: int, mineral_key: str
) -> ResourceStock:
    res = await session.execute(
        select(ResourceStock).where(
            ResourceStock.player_id == player_id, ResourceStock.mineral_key == mineral_key
        )
    )
    stock = res.scalar_one_or_none()
    if stock is None:
        stock = ResourceStock(player_id=player_id, mineral_key=mineral_key, amount=0.0)
        session.add(stock)
        await session.flush()
    return stock


async def player_stocks(session: AsyncSession, player_id: int) -> dict[str, float]:
    res = await session.execute(
        select(ResourceStock).where(ResourceStock.player_id == player_id)
    )
    return {s.mineral_key: s.amount for s in res.scalars()}


async def _player_buildings(session: AsyncSession, player_id: int) -> list[Building]:
    res = await session.execute(
        select(Building)
        .join(Base_, Building.base_id == Base_.id)
        .where(Base_.player_id == player_id)
    )
    return list(res.scalars())


async def finalize_due_builds(
    session: AsyncSession, player: Player, now: datetime | None = None
) -> int:
    """Activate buildings whose timer elapsed. Returns count finalized."""
    from app.services.notifications import notify

    now = now or _now()
    count = 0
    for b in await _player_buildings(session, player.id):
        if b.status == "building" and _aware(b.completes_at) <= now:
            b.status = "active"
            if get_content().buildings[b.building_key]["category"] == "mine":
                b.last_collected_at = b.completes_at
            await notify(
                session, player.id, "building_done", f"Edificio listo: {b.building_key}",
                {"building": b.building_key, "base_id": b.base_id},
            )
            count += 1
    return count


async def collect_mines(
    session: AsyncSession, player: Player, now: datetime | None = None
) -> dict[str, float]:
    """Credit minerals from all active mines to the player's stocks (lazy)."""
    from app.services.effects import multiplier

    now = now or _now()
    content = get_content()
    prod_mult = await multiplier(session, player.id, "production", now)
    gained: dict[str, float] = {}
    for b in await _player_buildings(session, player.id):
        spec = content.buildings[b.building_key]
        if b.status != "active" or spec["category"] != "mine" or not b.production_mineral:
            continue
        since = _aware(b.last_collected_at or b.completes_at)
        abundance = content.planet_abundance(player.planet_key, b.production_mineral)
        output = compute_mine_output(since, now, spec.get("base_output_per_hour", 0), abundance)
        amount = output * prod_mult
        if amount <= 0:
            continue
        stock = await get_or_create_stock(session, player.id, b.production_mineral)
        stock.amount += amount
        b.last_collected_at = now
        gained[b.production_mineral] = gained.get(b.production_mineral, 0.0) + amount
    return gained
