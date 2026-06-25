"""Moon expeditions: send a mission to a god's moon; on return it delivers premium
resources and grants a temporary boon. Same lazy-by-timestamp pattern as build/train.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import ActiveBoon, ExpeditionOrder, Player
from app.services.economy import collect_mines, finalize_due_builds, get_or_create_stock
from app.services.energy import spend_energy
from app.services.physics import effective_energy_regen
from app.services.training import finalize_due_training, player_units


class ExpeditionError(Exception):
    pass


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def _player_expeditions(session: AsyncSession, player_id: int) -> list[ExpeditionOrder]:
    res = await session.execute(
        select(ExpeditionOrder).where(ExpeditionOrder.player_id == player_id)
    )
    return list(res.scalars())


async def finalize_due_expeditions(
    session: AsyncSession, player: Player, now: datetime | None = None
) -> int:
    """Deliver finished expeditions: grant resources + create the god's boon."""
    now = now or datetime.now(UTC)
    content = get_content()
    finished = 0
    for order in await _player_expeditions(session, player.id):
        if order.status != "traveling" or _aware(order.completes_at) > now:
            continue
        moon = content.moons.get(order.moon_key, {})
        for mineral, amount in moon.get("grants", {}).items():
            stock = await get_or_create_stock(session, player.id, mineral)
            stock.amount += float(amount)
        boon = moon.get("boon")
        if boon:
            session.add(
                ActiveBoon(
                    player_id=player.id,
                    source_moon=order.moon_key,
                    effect=boon["effect"],
                    magnitude=float(boon["magnitude"]),
                    expires_at=now + timedelta(seconds=boon.get("duration_seconds", 0)),
                )
            )
        order.status = "done"
        from app.services.notifications import notify

        await notify(
            session, player.id, "expedition_returned",
            f"Expedicion a {order.moon_key} de vuelta",
            {"moon": order.moon_key, "grants": moon.get("grants", {}), "boon": moon.get("boon")},
        )
        finished += 1
    if finished:
        from app.services.stats import bump
        await bump(session, player.id, expeditions_completed=finished)
    return finished


async def start_expedition(session: AsyncSession, player: Player, moon_key: str) -> ExpeditionOrder:
    content = get_content()
    settings = get_settings()
    now = datetime.now(UTC)

    moon = content.moons.get(moon_key)
    if moon is None:
        raise ExpeditionError(f"Luna desconocida: {moon_key}")
    if content.moon_galaxy(moon_key) != player.galaxy_key:
        raise ExpeditionError("Esa luna no esta en tu galaxia.")

    exp = moon.get("expedition", {})
    required_unit = exp.get("requires_unit")

    # Bring economy + queues up to date before charging.
    await finalize_due_builds(session, player, now)
    await collect_mines(session, player, now)
    await finalize_due_training(session, player, now)
    await finalize_due_expeditions(session, player, now)

    if required_unit:
        units = await player_units(session, player.id)
        if units.get(required_unit, 0) < 1:
            raise ExpeditionError(f"Requiere al menos 1 {required_unit} para viajar.")

    if not spend_energy(
        player,
        exp.get("energy_cost", 0),
        now,
        effective_energy_regen(player, settings),
        settings.energy_max,
    ):
        raise ExpeditionError("Energia insuficiente para la expedicion.")

    order = ExpeditionOrder(
        player_id=player.id,
        moon_key=moon_key,
        status="traveling",
        completes_at=now + timedelta(seconds=exp.get("duration_seconds", 0)),
    )
    session.add(order)
    await session.flush()
    from app.services.journal import record
    await record(session, "expedition_launched", player.id, moon=moon_key)
    return order
