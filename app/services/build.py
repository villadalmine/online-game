"""Start construction: spend energy + minerals (resolved per-race), enqueue with a timer."""
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import Base_, Building, Player
from app.services.economy import collect_mines, finalize_due_builds
from app.services.energy import spend_energy
from app.services.physics import effective_energy_regen, gravity_build_multiplier


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

    if spec["category"] == "mine":
        if target_mineral is None:
            raise BuildError("Una mina requiere 'target_mineral'.")
        if target_mineral not in content.minerals:
            raise BuildError(f"Mineral desconocido: {target_mineral}")

    # Bring economy up to date before charging.
    await finalize_due_builds(session, player, now)
    await collect_mines(session, player, now)

    # Charge energy (also applies regen).
    if not spend_energy(
        player,
        spec.get("energy_cost", 0),
        now,
        effective_energy_regen(player, settings),
        settings.energy_max,
    ):
        raise BuildError("Energia insuficiente.")

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
        production_mineral=target_mineral if spec["category"] == "mine" else None,
    )
    session.add(building)
    await session.flush()
    from app.services.journal import record
    await record(session, "build_queued", player.id,
                 building=building_key, mineral=target_mineral, base_id=base.id)
    return building
