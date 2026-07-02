"""Start construction: spend energy + minerals (resolved per-race), enqueue with a timer."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import Base_, Building, Player
from app.services.economy import collect_mines, finalize_due_builds
from app.services.energy import energy_shortfall_msg, spend_energy
from app.services.physics import (
    effective_energy_max,
    effective_energy_regen,
    gravity_build_multiplier,
)


class BuildError(Exception):
    pass


async def start_build(
    session: AsyncSession,
    player: Player,
    base: Base_,
    building_key: str,
    target_mineral: str | None = None,
) -> Building:
    content = get_content()
    settings = get_settings()
    now = datetime.now(UTC)

    spec = content.buildings.get(building_key)
    if spec is None:
        raise BuildError(f"Edificio desconocido: {building_key}")
    if base.player_id != player.id:
        raise BuildError("La base no pertenece al jugador.")

    # SDD 1: árbol de tech — el edificio puede pedir otro edificio activo en la base y/o una tech.
    required = spec.get("requires")
    if required and required != "headquarters":
        active = (await session.execute(
            select(Building.id).where(
                Building.base_id == base.id, Building.building_key == required,
                Building.status == "active",
            )
        )).first()
        if active is None:
            raise BuildError(f"Requiere el edificio activo: {required}")
    rtech = spec.get("requires_tech")
    if rtech:
        from app.services.research import researched_techs
        if rtech not in await researched_techs(session, player.id):
            raise BuildError(f"Requiere investigar: {rtech}")

    # mina (qué extrae) y silo (qué almacena, SDD 47) eligen un mineral al construirse.
    needs_mineral = spec["category"] in ("mine", "storage")
    if needs_mineral:
        if target_mineral is None:
            raise BuildError(f"{building_key} requiere 'target_mineral'.")
        if target_mineral not in content.minerals:
            raise BuildError(f"Mineral desconocido: {target_mineral}")

    # Bring economy up to date before charging.
    await finalize_due_builds(session, player, now)
    await collect_mines(session, player, now)

    # Charge energy (also applies regen).
    regen = effective_energy_regen(player, settings)
    need_e = spec.get("energy_cost", 0)
    if not spend_energy(player, need_e, now, regen, effective_energy_max(player, settings)):
        # spend_energy ya aplicó regen, así que player.energy es el valor actual.
        raise BuildError(energy_shortfall_msg(need_e, player.energy, regen))

    # Charge minerals (role-based cost resolved to this race's minerals).
    cost = content.building_cost_in_minerals(player.race_key, building_key)
    # Eventos "happy hour" (SDD 36): build_cost < 1 abarata la construcción.
    from app.services.events import build_cost_multiplier
    cm = await build_cost_multiplier(session, now)
    # Colonia/órbita (SDD 37 v2): construir en mundos hostiles o en órbita cuesta más.
    if base.planet_key != player.planet_key or base.base_type == "orbital":
        if base.base_type == "orbital":
            cm *= 1.5
        else:
            from app.services.colonization import compat
            from app.services.research import researched_techs
            techs = await researched_techs(session, player.id)
            cm *= compat(player.race_key, base.planet_key, techs)["modifiers"]["build_cost"]
    if cm != 1.0:
        cost = {m: a * cm for m, a in cost.items()}
    # SDD 42: el material tiene que estar EN EL PLANETA de la base; si no, hay que transportarlo.
    from app.services.economy import get_or_create_stock, planet_stocks
    here = await planet_stocks(session, player.id, base.planet_key)
    for mineral, amount in cost.items():
        if here.get(mineral, 0.0) < amount:
            raise BuildError(
                f"Falta {mineral} en {base.planet_key} (necesita {amount:g}, "
                f"tenés {here.get(mineral, 0.0):g} ahí). Transportá material a ese planeta."
            )
    for mineral, amount in cost.items():
        stock = await get_or_create_stock(session, player.id, mineral, base.planet_key)
        stock.amount -= amount

    build_seconds = spec.get("build_seconds", 0) * gravity_build_multiplier(
        player.planet_key, settings
    )
    building = Building(
        base_id=base.id,
        building_key=building_key,
        status="building",
        completes_at=now + timedelta(seconds=build_seconds),
        production_mineral=target_mineral if needs_mineral else None,
    )
    session.add(building)
    await session.flush()
    from app.services.journal import record
    await record(session, "build_queued", player.id,
                 building=building_key, mineral=target_mineral, base_id=base.id)
    return building


async def _owned_building(session, player, building_id):
    b = await session.get(Building, building_id)
    if b is None:
        raise BuildError("Edificio no encontrado.")
    base = await session.get(Base_, b.base_id)
    if base is None or base.player_id != player.id:
        raise BuildError("Ese edificio no es tuyo.")
    return b, base


async def _charge(session, player, base, cost, energy_cost):
    """SDD 66: cobra energía + minerales (del planeta de la base), como start_build."""
    settings = get_settings()
    now = datetime.now(UTC)
    await collect_mines(session, player, now)
    if not spend_energy(player, energy_cost, now, effective_energy_regen(player, settings),
                        effective_energy_max(player, settings)):
        raise BuildError(energy_shortfall_msg(energy_cost, player.energy,
                                              effective_energy_regen(player, settings)))
    from app.services.economy import get_or_create_stock, planet_stocks
    here = await planet_stocks(session, player.id, base.planet_key)
    for m, a in cost.items():
        if here.get(m, 0.0) < a:
            raise BuildError(f"Falta {m} en {base.planet_key} (necesita {a:g}).")
    for m, a in cost.items():
        (await get_or_create_stock(session, player.id, m, base.planet_key)).amount -= a


async def repair_building(session: AsyncSession, player: Player, building_id: int) -> Building:
    """SDD 66: repara un edificio averiado a 100 de condición; cuesta proporcional al daño."""
    if not get_settings().building_condition_enabled:
        raise BuildError("La reparación de edificios está desactivada.")
    content = get_content()
    b, base = await _owned_building(session, player, building_id)
    if b.condition >= 100:
        raise BuildError("Ese edificio está sano.")
    dmg = (100.0 - b.condition) / 100.0
    frac = dmg * get_settings().building_repair_cost_fraction
    base_cost = content.building_cost_in_minerals(player.race_key, b.building_key)
    cost = {m: a * frac for m, a in base_cost.items()}
    espec = content.buildings.get(b.building_key, {})
    await _charge(session, player, base, cost, espec.get("energy_cost", 0) * frac)
    b.condition = 100.0
    await session.flush()
    return b


async def demolish_building(session: AsyncSession, player: Player, building_id: int) -> dict:
    """SDD 66: demolición propia — devuelve `building_salvage_fraction` del costo. Nunca HQ/mina."""
    content = get_content()
    b, base = await _owned_building(session, player, building_id)
    cat = content.buildings.get(b.building_key, {}).get("category")
    if b.building_key == "headquarters" or cat in ("core", "mine"):
        raise BuildError("No podés demoler la base central ni una mina.")
    from app.services.economy import get_or_create_stock
    salvage = {}
    frac = get_settings().building_salvage_fraction
    for m, a in content.building_cost_in_minerals(player.race_key, b.building_key).items():
        got = a * frac
        (await get_or_create_stock(session, player.id, m, base.planet_key)).amount += got
        salvage[m] = round(got, 1)
    key = b.building_key
    await session.delete(b)
    await session.flush()
    return {"demolished": key, "salvage": salvage}


async def upgrade_building(
    session: AsyncSession, player: Player, building_id: int, kind: str
) -> Building:
    """SDD 66: mejora un edificio (defense/antimissile) → sube `level`; costo crece por nivel."""
    content = get_content()
    b, base = await _owned_building(session, player, building_id)
    if b.status != "active":
        raise BuildError("El edificio todavía no está activo.")
    ups = content.buildings.get(b.building_key, {}).get("upgrade") or {}
    if kind not in ups:
        raise BuildError(f"Ese edificio no admite la mejora '{kind}'.")
    lvl = (b.level or 1)
    mult = get_settings().building_upgrade_cost_mult * lvl
    base_cost = content.building_cost_in_minerals(player.race_key, b.building_key)
    cost = {m: a * mult for m, a in base_cost.items()}
    espec = content.buildings.get(b.building_key, {})
    await _charge(session, player, base, cost, espec.get("energy_cost", 0) * mult)
    b.level = lvl + 1
    await session.flush()
    from app.services.journal import record
    await record(session, "building_upgraded", player.id, building=b.building_key,
                 kind=kind, level=b.level)
    return b
