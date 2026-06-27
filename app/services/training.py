"""Train units: spend energy + minerals (resolved per-race), enqueue with a timer.

Mirrors services/build.py — same lazy pattern. Completed batches land in UnitStock.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import Base_, Building, Player, TrainingOrder, UnitStock
from app.services.economy import collect_mines, finalize_due_builds
from app.services.energy import energy_shortfall_msg, spend_energy
from app.services.physics import effective_energy_max, effective_energy_regen


class TrainingError(Exception):
    pass


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def get_or_create_unit_stock(
    session: AsyncSession, player_id: int, unit_key: str
) -> UnitStock:
    res = await session.execute(
        select(UnitStock).where(UnitStock.player_id == player_id, UnitStock.unit_key == unit_key)
    )
    stock = res.scalar_one_or_none()
    if stock is None:
        stock = UnitStock(player_id=player_id, unit_key=unit_key, quantity=0)
        session.add(stock)
        await session.flush()
    return stock


async def player_units(session: AsyncSession, player_id: int) -> dict[str, int]:
    res = await session.execute(select(UnitStock).where(UnitStock.player_id == player_id))
    return {s.unit_key: s.quantity for s in res.scalars()}


async def _player_training_orders(session: AsyncSession, player_id: int) -> list[TrainingOrder]:
    res = await session.execute(
        select(TrainingOrder)
        .join(Base_, TrainingOrder.base_id == Base_.id)
        .where(Base_.player_id == player_id)
    )
    return list(res.scalars())


async def finalize_due_training(
    session: AsyncSession, player: Player, now: datetime | None = None
) -> int:
    """Deliver finished training batches into UnitStock. Returns units delivered."""
    from app.services.notifications import notify

    now = now or datetime.now(UTC)
    delivered = 0
    for order in await _player_training_orders(session, player.id):
        if order.status == "training" and _aware(order.completes_at) <= now:
            stock = await get_or_create_unit_stock(session, player.id, order.unit_key)
            stock.quantity += order.quantity
            order.status = "done"
            await notify(
                session, player.id, "training_done",
                f"{order.quantity} {order.unit_key} entrenados",
                {"unit": order.unit_key, "quantity": order.quantity},
            )
            delivered += order.quantity
    if delivered:
        from app.services.stats import bump
        await bump(session, player.id, units_trained=delivered)
    return delivered


async def _building_active(session: AsyncSession, base_id: int, building_key: str) -> bool:
    res = await session.execute(
        select(Building).where(
            Building.base_id == base_id,
            Building.building_key == building_key,
            Building.status == "active",
        )
    )
    return res.first() is not None


async def start_training(
    session: AsyncSession, player: Player, base: Base_, unit_key: str, quantity: int
) -> TrainingOrder:
    content = get_content()
    settings = get_settings()
    now = datetime.now(UTC)

    spec = content.units.get(unit_key)
    if spec is None:
        raise TrainingError(f"Unidad desconocida: {unit_key}")
    if base.player_id != player.id:
        raise TrainingError("La base no pertenece al jugador.")
    if quantity < 1:
        raise TrainingError("La cantidad debe ser >= 1.")

    required = spec.get("requires")
    if required and not await _building_active(session, base.id, required):
        raise TrainingError(f"Requiere el edificio activo: {required}")
    rtech = spec.get("requires_tech")   # SDD 1: árbol de tech — la unidad pide una investigación
    if rtech:
        from app.services.research import researched_techs
        if rtech not in await researched_techs(session, player.id):
            raise TrainingError(f"Requiere investigar: {rtech}")

    # Restricciones físicas del planeta (SDD 13): aviones necesitan atmósfera, barcos agua líquida.
    # Se evalúa el planeta de la BASE donde se entrena (puede ser una colonia), no el de origen.
    planet = content.planets.get(base.planet_key, {})
    if spec.get("requires_atmosphere") and planet.get("atmosphere", "none") == "none":
        raise TrainingError(f"{unit_key} necesita atmósfera; {base.planet_key} no tiene.")
    if spec.get("requires_liquid_water") and not planet.get("has_liquid_water", False):
        raise TrainingError(f"{unit_key} necesita agua líquida; {base.planet_key} no tiene.")

    # Bring economy + queues up to date before charging.
    await finalize_due_builds(session, player, now)
    await collect_mines(session, player, now)
    await finalize_due_training(session, player, now)

    # SDD 46: chequeo de plazas de alojamiento ANTES de gastar (flag housing_enforced, default off).
    if settings.housing_enforced:
        from app.services.housing import (
            can_train,
            houses_for_domain,
            housing_capacity,
            housing_occupancy,
            unit_domain,
            unit_size,
        )
        abk = [
            bk for (bk,) in (await session.execute(
                select(Building.building_key)
                .join(Base_, Building.base_id == Base_.id)
                .where(Base_.player_id == player.id, Building.status == "active")
            )).all()
        ]
        queued: dict[str, int] = {}
        for o in await _player_training_orders(session, player.id):
            if o.status == "training":
                queued[o.unit_key] = queued.get(o.unit_key, 0) + o.quantity
        cap = housing_capacity(abk)
        occ = housing_occupancy(await player_units(session, player.id), queued)
        domain = unit_domain(unit_key)
        free = cap.get(domain, 0) - occ.get(domain, 0)
        if not can_train(unit_key, quantity, free):
            builders = houses_for_domain(domain) or ["(ninguno)"]
            raise TrainingError(
                f"No hay plazas de {domain} (libres {max(0, free)}, necesitás "
                f"{quantity * unit_size(unit_key)}). Construí/ampliá: {', '.join(builders)}."
            )

    energy_cost = spec.get("energy_cost", 0) * quantity
    regen = effective_energy_regen(player, settings)
    if not spend_energy(player, energy_cost, now, regen, effective_energy_max(player, settings)):
        raise TrainingError(energy_shortfall_msg(energy_cost, player.energy, regen))

    unit_cost = content.unit_cost_in_minerals(player.race_key, unit_key)
    cost = {m: amt * quantity for m, amt in unit_cost.items()}
    # SDD 42: se entrena con el material DEL PLANETA de la base.
    from app.services.economy import get_or_create_stock, planet_stocks
    here = await planet_stocks(session, player.id, base.planet_key)
    for mineral, amount in cost.items():
        if here.get(mineral, 0.0) < amount:
            raise TrainingError(
                f"Falta {mineral} en {base.planet_key} (necesita {amount:g}, "
                f"tenés {here.get(mineral, 0.0):g} ahí)."
            )
    for mineral, amount in cost.items():
        stock = await get_or_create_stock(session, player.id, mineral, base.planet_key)
        stock.amount -= amount

    order = TrainingOrder(
        base_id=base.id,
        unit_key=unit_key,
        quantity=quantity,
        status="training",
        completes_at=now + timedelta(seconds=spec.get("train_seconds", 0) * quantity),
    )
    session.add(order)
    await session.flush()
    from app.services.journal import record
    await record(session, "train_queued", player.id,
                 unit=unit_key, quantity=quantity, base_id=base.id)
    return order
