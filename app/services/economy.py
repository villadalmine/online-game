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
    session: AsyncSession, player_id: int, mineral_key: str, planet_key: str
) -> ResourceStock:
    """Stock de un mineral EN UN PLANETA (SDD 42 Fase 2). `planet_key` es obligatorio: el material
    vive donde está. El agregado por jugador se obtiene con `player_stocks`."""
    res = await session.execute(
        select(ResourceStock).where(
            ResourceStock.player_id == player_id,
            ResourceStock.mineral_key == mineral_key,
            ResourceStock.planet_key == planet_key,
        )
    )
    stock = res.scalar_one_or_none()
    if stock is None:
        stock = ResourceStock(
            player_id=player_id, mineral_key=mineral_key, planet_key=planet_key, amount=0.0
        )
        session.add(stock)
        await session.flush()
    return stock


async def player_stocks(session: AsyncSession, player_id: int) -> dict[str, float]:
    """Agregado por jugador: suma de cada mineral en TODOS sus planetas (backward-compat para
    UI/scoring/asistente). Para un planeta puntual usar `planet_stocks`."""
    res = await session.execute(
        select(ResourceStock).where(ResourceStock.player_id == player_id)
    )
    out: dict[str, float] = {}
    for s in res.scalars():
        out[s.mineral_key] = out.get(s.mineral_key, 0.0) + s.amount
    return out


async def planet_stocks(
    session: AsyncSession, player_id: int, planet_key: str
) -> dict[str, float]:
    """Stock del jugador EN UN PLANETA (SDD 42 Fase 2)."""
    res = await session.execute(
        select(ResourceStock).where(
            ResourceStock.player_id == player_id, ResourceStock.planet_key == planet_key
        )
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
    buildings = await _player_buildings(session, player.id)
    for b in buildings:
        if b.status == "building" and _aware(b.completes_at) <= now:
            b.status = "active"
            if get_content().buildings[b.building_key]["category"] == "mine":
                b.last_collected_at = b.completes_at
            await notify(
                session, player.id, "building_done", f"Edificio listo: {b.building_key}",
                {"building": b.building_key, "base_id": b.base_id},
            )
            count += 1
    # Cacheo de plantas de energía activas (suben tope/regen). Se recomputa siempre: este paso corre
    # antes de toda operación de energía (es el primer paso de cada acción y del advance).
    player.active_power_plants = sum(
        1 for b in buildings if b.status == "active" and b.building_key == "power_plant"
    )
    if count:
        from app.services.stats import bump
        await bump(session, player.id, buildings_built=count)
    return count


async def collect_mines(
    session: AsyncSession, player: Player, now: datetime | None = None
) -> dict[str, float]:
    """Credit minerals from all active mines to the player's stocks (lazy)."""
    from app.services.effects import multiplier

    now = now or _now()
    content = get_content()
    prod_mult = await multiplier(session, player.id, "production", now)
    # SDD 37: cada mina produce según el planeta de SU base (no el natal); las colonias además
    # llevan el modificador de habitabilidad. El mundo natal queda idéntico (compat no se aplica).
    from app.core.config import get_settings
    from app.services.colonization import compat
    from app.services.research import researched_techs
    bres = await session.execute(select(Base_).where(Base_.player_id == player.id))
    base_info = {b.id: (b.planet_key, b.base_type) for b in bres.scalars()}
    home = player.planet_key
    has_colony = any(p != home or bt == "orbital" for p, bt in base_info.values())
    techs = await researched_techs(session, player.id) if has_colony else ()
    orbital_yield = get_settings().orbital_yield
    colony_mult: dict[str, float] = {}
    gained: dict[str, float] = {}
    for b in await _player_buildings(session, player.id):
        spec = content.buildings[b.building_key]
        if b.status != "active" or spec["category"] != "mine" or not b.production_mineral:
            continue
        planet, btype = base_info.get(b.base_id, (home, "surface"))
        since = _aware(b.last_collected_at or b.completes_at)
        if btype == "lunar":   # base lunar: rinde los `grants` de la luna (He-3, hielo…) / 100
            grants = content.moons.get(planet, {}).get("grants", {})
            abundance = grants.get(b.production_mineral, 0) / 100.0
        else:
            abundance = content.planet_abundance(planet, b.production_mineral)
        output = compute_mine_output(since, now, spec.get("base_output_per_hour", 0), abundance)
        amount = output * prod_mult
        if btype in ("orbital", "lunar"):   # robots: rinde fijo, sin habitabilidad
            amount *= orbital_yield
        elif planet != home:     # colonia de superficie: rinde según habitabilidad raza×planeta
            if planet not in colony_mult:
                colony_mult[planet] = compat(
                    player.race_key, planet, techs
                )["modifiers"]["production"]
            amount *= colony_mult[planet]
        if amount <= 0:
            continue
        # SDD 42: la mina acredita al stock DE SU PLANETA (no a un pool global).
        stock = await get_or_create_stock(session, player.id, b.production_mineral, planet)
        stock.amount += amount
        b.last_collected_at = now
        gained[b.production_mineral] = gained.get(b.production_mineral, 0.0) + amount
    total = sum(gained.values())
    if total > 0:
        from app.services.stats import bump
        await bump(session, player.id, resources_mined=total)
    return gained
