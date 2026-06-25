"""Mercado y comercio (SDD 42, Fase 1): comprar/vender minerales a precios POR PLANETA.

Precios **derivados** (no hardcodeados): precio = base × escasez, donde escasez = 1/abundancia del
planeta (SDD 13). Barato donde abunda, caro donde escasea; los premium (sin abundancia) son los más
caros. Pagás en **energía**. Requiere un edificio `market` activo en una base tuya en ese planeta
(la "estructura para copiar el mercado en ese planeta"). v1: el stock es el pool del jugador; el
inventario por-planeta es la Fase 2 (SDD 42 §9).
"""
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import Base_, Building, Player
from app.services.economy import get_or_create_stock
from app.services.energy import spend_energy
from app.services.physics import effective_energy_regen


class MarketError(Exception):
    pass


def mineral_price(planet_key: str, mineral_key: str) -> float:
    """Precio de compra (energía/unidad) de un mineral en un planeta: base × escasez local.
    Escasez = 1/abundancia; un mineral que NO está en la tabla del planeta (p.ej. premium como
    He-3) se trata como muy escaso → caro (no usamos el default 1.0 de planet_abundance)."""
    s = get_settings()
    planet = get_content().planets.get(planet_key, {})
    ab = planet.get("abundance", {}).get(mineral_key)   # None si no se da naturalmente ahí
    eff = s.market_scarcity_floor if ab is None else max(ab, s.market_scarcity_floor)
    return round(s.market_mineral_base_energy / eff, 2)


def prices(planet_key: str) -> dict[str, dict]:
    """Tabla de precios del planeta para la UI/IA: {mineral: {buy, sell}}."""
    s = get_settings()
    out = {}
    for m in get_content().minerals:
        buy = mineral_price(planet_key, m)
        out[m] = {"buy": buy, "sell": round(buy * s.market_sell_spread, 2)}
    return out


async def _has_market(session: AsyncSession, player: Player, planet_key: str) -> bool:
    """¿El jugador tiene un `market` activo en una base en ese planeta?"""
    res = await session.execute(
        select(Building)
        .join(Base_, Building.base_id == Base_.id)
        .where(Base_.player_id == player.id, Base_.planet_key == planet_key,
               Building.building_key == "market", Building.status == "active")
    )
    return res.scalars().first() is not None


async def buy(
    session: AsyncSession, player: Player, planet_key: str, mineral_key: str, qty: int
) -> dict:
    s = get_settings()
    now = datetime.now(UTC)
    qty = int(qty)
    if qty <= 0:
        raise MarketError("Cantidad inválida.")
    if mineral_key not in get_content().minerals:
        raise MarketError(f"Mineral desconocido: {mineral_key}")
    if not await _has_market(session, player, planet_key):
        raise MarketError(f"Necesitás un mercado activo en {planet_key}.")

    cost = mineral_price(planet_key, mineral_key) * qty
    if not spend_energy(player, cost, now, effective_energy_regen(player, s), s.energy_max):
        raise MarketError(f"Energía insuficiente (cuesta {round(cost, 1)}).")
    (await get_or_create_stock(session, player.id, mineral_key, planet_key)).amount += qty

    from app.services.journal import record
    await record(session, "market_buy", player.id,
                 planet=planet_key, mineral=mineral_key, qty=qty, energy=round(cost, 1))
    return {"bought": qty, "mineral": mineral_key, "energy_spent": round(cost, 1),
            "energy": round(player.energy, 1)}


async def sell(
    session: AsyncSession, player: Player, planet_key: str, mineral_key: str, qty: int
) -> dict:
    s = get_settings()
    qty = int(qty)
    if qty <= 0:
        raise MarketError("Cantidad inválida.")
    if not await _has_market(session, player, planet_key):
        raise MarketError(f"Necesitás un mercado activo en {planet_key}.")
    stock = await get_or_create_stock(session, player.id, mineral_key, planet_key)
    if stock.amount < qty:
        raise MarketError(f"No tenés {qty} de {mineral_key} (tenés {stock.amount:g}).")

    gain = mineral_price(planet_key, mineral_key) * s.market_sell_spread * qty
    stock.amount -= qty
    player.energy = min(s.energy_max, player.energy + gain)
    player.energy_updated_at = datetime.now(UTC)

    from app.services.journal import record
    await record(session, "market_sell", player.id,
                 planet=planet_key, mineral=mineral_key, qty=qty, energy=round(gain, 1))
    return {"sold": qty, "mineral": mineral_key, "energy_gained": round(gain, 1),
            "energy": round(player.energy, 1)}


async def player_market_planets(session: AsyncSession, player: Player) -> list[str]:
    """Planetas donde el jugador tiene un mercado activo (para la UI)."""
    res = await session.execute(
        select(Base_.planet_key)
        .join(Building, Building.base_id == Base_.id)
        .where(Base_.player_id == player.id,
               Building.building_key == "market", Building.status == "active")
    )
    return sorted({p for p in res.scalars()})


# --------------------------------------------------------------------------- #
# Transporte de minerales entre planetas (SDD 42 Fase 2)
# --------------------------------------------------------------------------- #
async def start_transport(
    session: AsyncSession, player: Player, from_planet: str, to_planet: str, cargo: dict[str, int]
):
    """Despacha un envío de minerales de `from_planet` a `to_planet`. Requiere naves de carga
    suficientes (capacidad `cargo` por nave). Consume carga del origen + naves; al llegar acredita
    al destino y devuelve las naves (process_transport_missions)."""
    import json
    from datetime import timedelta

    from app.models import TransportMission
    from app.services.combat import travel_seconds
    from app.services.economy import planet_stocks
    from app.services.training import get_or_create_unit_stock, player_units

    now = datetime.now(UTC)
    cargo = {k: int(v) for k, v in cargo.items() if v and int(v) > 0}
    if not cargo:
        raise MarketError("No hay carga para transportar.")
    if from_planet == to_planet:
        raise MarketError("Origen y destino son el mismo planeta.")
    if from_planet not in get_content().planets and from_planet not in get_content().moons:
        raise MarketError(f"Origen desconocido: {from_planet}")

    here = await planet_stocks(session, player.id, from_planet)
    for m, q in cargo.items():
        if here.get(m, 0.0) < q:
            raise MarketError(f"No tenés {q} de {m} en {from_planet} (tenés {here.get(m, 0.0):g}).")

    capacity = get_content().units.get("cargo_ship", {}).get("stats", {}).get("cargo", 0)
    total = sum(cargo.values())
    ships_needed = -(-total // capacity) if capacity else 1   # ceil
    have_ships = (await player_units(session, player.id)).get("cargo_ship", 0)
    if have_ships < ships_needed:
        raise MarketError(f"Necesitás {ships_needed} nave(s) de carga (tenés {have_ships}).")

    for m, q in cargo.items():   # la carga sale del origen ya
        (await get_or_create_stock(session, player.id, m, from_planet)).amount -= q
    (await get_or_create_unit_stock(session, player.id, "cargo_ship")).quantity -= ships_needed

    travel = travel_seconds(from_planet, to_planet)
    mission = TransportMission(
        player_id=player.id, from_planet=from_planet, to_planet=to_planet,
        cargo=json.dumps(cargo), ships=ships_needed, status="outbound",
        arrives_at=now + timedelta(seconds=travel),
    )
    session.add(mission)
    await session.flush()
    from app.services.journal import record
    await record(session, "transport_launched", player.id,
                 from_planet=from_planet, to_planet=to_planet, cargo=cargo, ships=ships_needed)
    return mission


async def process_transport_missions(
    session: AsyncSession, now: datetime | None = None, player_id: int | None = None
) -> int:
    """Entrega los transportes que llegaron: acredita la carga al destino y devuelve las naves."""
    import json

    from app.models import TransportMission
    from app.services.training import get_or_create_unit_stock

    now = now or datetime.now(UTC)
    conds = [TransportMission.status == "outbound"]
    if player_id is not None:
        conds.append(TransportMission.player_id == player_id)
    res = await session.execute(select(TransportMission).where(*conds))
    done = 0
    for m in res.scalars():
        arr = m.arrives_at if m.arrives_at.tzinfo else m.arrives_at.replace(tzinfo=UTC)
        if arr > now:
            continue
        for mineral, qty in json.loads(m.cargo).items():
            (await get_or_create_stock(session, m.player_id, mineral, m.to_planet)).amount += qty
        (await get_or_create_unit_stock(session, m.player_id, "cargo_ship")).quantity += m.ships
        m.status = "done"
        done += 1
    return done


# --------------------------------------------------------------------------- #
# Hub galáctico con precios dinámicos por oferta/demanda (SDD 42 Fase 3)
# --------------------------------------------------------------------------- #
def hub_intrinsic(mineral_key: str) -> float:
    """Valor intrínseco del mineral en el hub (sin abundancia local: usa la media de todos los
    planetas → los premium, que no se dan en ninguno, valen más)."""
    s = get_settings()
    present = [
        p.get("abundance", {}).get(mineral_key)
        for p in get_content().planets.values()
        if p.get("abundance", {}).get(mineral_key) is not None
    ]
    avg = (sum(present) / len(present)) if present else 0.0
    eff = s.market_scarcity_floor if avg <= 0 else max(avg, s.market_scarcity_floor)
    return round(s.market_mineral_base_energy / eff, 2)


async def _hub_row(session: AsyncSession, galaxy_key: str, mineral_key: str):
    from app.models import MarketPrice
    row = (await session.execute(
        select(MarketPrice).where(
            MarketPrice.galaxy_key == galaxy_key, MarketPrice.mineral_key == mineral_key
        )
    )).scalar_one_or_none()
    if row is None:
        row = MarketPrice(galaxy_key=galaxy_key, mineral_key=mineral_key,
                          price=hub_intrinsic(mineral_key))
        session.add(row)
        await session.flush()
    return row


async def hub_prices(session: AsyncSession, galaxy_key: str) -> dict[str, float]:
    return {m: (await _hub_row(session, galaxy_key, m)).price for m in get_content().minerals}


async def hub_prices_all(session: AsyncSession) -> dict[str, dict[str, float]]:
    """Precios del hub de CADA galaxia (consulta inter-galaxia, SDD 42)."""
    return {g: await hub_prices(session, g) for g in get_content().galaxies}


def _clamp_hub(price: float, mineral_key: str) -> float:
    band = get_settings().market_hub_band
    intr = hub_intrinsic(mineral_key)
    return round(max(intr / band, min(intr * band, price)), 2)


async def hub_trade(
    session: AsyncSession, player: Player, mineral_key: str, qty: int, side: str
) -> dict:
    """Comprar/vender en el hub de tu galaxia al precio dinámico. Requiere una nave de carga para
    traer/llevar los bienes; pagás/cobrás energía; el precio se mueve con tu operación."""
    from app.services.training import player_units

    s = get_settings()
    now = datetime.now(UTC)
    qty = int(qty)
    if qty <= 0:
        raise MarketError("Cantidad inválida.")
    if mineral_key not in get_content().minerals:
        raise MarketError(f"Mineral desconocido: {mineral_key}")
    galaxy = player.galaxy_key
    if not galaxy:
        raise MarketError("No estás en ninguna galaxia.")
    if (await player_units(session, player.id)).get("cargo_ship", 0) < 1:
        raise MarketError("Necesitás una nave de carga para operar en el hub.")

    row = await _hub_row(session, galaxy, mineral_key)
    home = player.planet_key
    if side == "buy":
        cost = row.price * qty
        if not spend_energy(player, cost, now, effective_energy_regen(player, s), s.energy_max):
            raise MarketError(f"Energía insuficiente (cuesta {round(cost, 1)}).")
        (await get_or_create_stock(session, player.id, mineral_key, home)).amount += qty
        row.price = _clamp_hub(row.price * (1 + s.market_hub_impact * qty), mineral_key)
        result = {"bought": qty, "energy_spent": round(cost, 1)}
    else:  # sell
        stock = await get_or_create_stock(session, player.id, mineral_key, home)
        if stock.amount < qty:
            raise MarketError(f"No tenés {qty} de {mineral_key} en {home}.")
        gain = row.price * s.market_sell_spread * qty
        stock.amount -= qty
        player.energy = min(s.energy_max, player.energy + gain)
        player.energy_updated_at = now
        row.price = _clamp_hub(row.price * (1 - s.market_hub_impact * qty), mineral_key)
        result = {"sold": qty, "energy_gained": round(gain, 1)}
    row.updated_at = now

    from app.services.journal import record
    await record(session, f"hub_{side}", player.id,
                 galaxy=galaxy, mineral=mineral_key, qty=qty, price=round(row.price, 2))
    return {**result, "mineral": mineral_key, "price": round(row.price, 2),
            "energy": round(player.energy, 1)}


async def revert_hub_prices(session: AsyncSession) -> int:
    """Reversión lenta de los precios del hub hacia su intrínseco (oferta/demanda se calma)."""
    from app.models import MarketPrice
    s = get_settings()
    rows = (await session.execute(select(MarketPrice))).scalars().all()
    for row in rows:
        intr = hub_intrinsic(row.mineral_key)
        row.price = _clamp_hub(row.price + (intr - row.price) * s.market_hub_reversion,
                               row.mineral_key)
    return len(rows)
