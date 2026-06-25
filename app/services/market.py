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


async def _window_traded(
    session: AsyncSession, player_id: int, planet_key: str, mineral_key: str, since
) -> tuple[float, float]:
    """(comprado, vendido) de un mineral en un planeta dentro de la ventana (desde el journal)."""
    import json

    from app.models import GameEvent
    rows = (await session.execute(
        select(GameEvent).where(
            GameEvent.player_id == player_id,
            GameEvent.type.in_(("market_buy", "market_sell")),
            GameEvent.created_at >= since,
        )
    )).scalars()
    bought = sold = 0.0
    for e in rows:
        p = json.loads(e.payload or "{}")
        if p.get("planet") == planet_key and p.get("mineral") == mineral_key:
            if e.type == "market_buy":
                bought += p.get("qty", 0)
            else:
                sold += p.get("qty", 0)
    return bought, sold


async def _check_rate_limit(
    session: AsyncSession, player: Player, planet_key: str, mineral_key: str,
    qty: int, side: str, stock_now: float,
) -> None:
    """Anti-abuso (SDD 42): en el mercado del MUNDO NATAL, por ventana de 2h, no vendas más del
    30% ni compres más del 20% de tus tenencias (parejo, sin dumping/reventa). Rolling = resetea."""
    if planet_key != player.planet_key:
        return  # la regla del % es solo del mundo natal; las colonias se rigen por transporte
    from datetime import timedelta
    s = get_settings()
    since = datetime.now(UTC) - timedelta(seconds=s.market_window_seconds)
    bought, sold = await _window_traded(session, player.id, planet_key, mineral_key, since)
    base = max(0.0, stock_now + sold - bought)   # tenencias al inicio de la ventana
    if side == "sell":
        cap = s.market_sell_pct * base
        if sold + qty > cap:
            raise MarketError(
                f"Límite 2h: vendés hasta {int(s.market_sell_pct * 100)}% de tus tenencias de "
                f"{mineral_key} (te quedan {max(0, int(cap - sold))})."
            )
    else:
        cap = s.market_buy_pct * base + s.market_buy_floor
        if bought + qty > cap:
            raise MarketError(
                f"Límite 2h: comprás hasta {int(s.market_buy_pct * 100)}% de tus tenencias "
                f"(anti-reventa); te quedan {max(0, int(cap - bought))} de {mineral_key}."
            )


async def _count_buildings(session: AsyncSession, player_id: int, building_key: str) -> int:
    """Cuántos edificios `building_key` activos tiene el jugador (en todas sus bases)."""
    from sqlalchemy import func
    return (await session.execute(
        select(func.count(Building.id))
        .join(Base_, Building.base_id == Base_.id)
        .where(Base_.player_id == player_id,
               Building.building_key == building_key, Building.status == "active")
    )).scalar_one()


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
    held = (await get_or_create_stock(session, player.id, mineral_key, planet_key)).amount
    await _check_rate_limit(session, player, planet_key, mineral_key, qty, "buy", held)

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
    await _check_rate_limit(session, player, planet_key, mineral_key, qty, "sell", stock.amount)

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
    session: AsyncSession, player: Player, from_planet: str, to_planet: str,
    cargo: dict[str, int], escort: dict[str, int] | None = None,
):
    """Despacha un envío de minerales de `from_planet` a `to_planet`. Requiere naves de carga
    suficientes (capacidad `cargo` por nave). Consume carga del origen + naves; al llegar acredita
    al destino y devuelve las naves (process_transport_missions). Opcionalmente lleva una `escort`
    de unidades militares que defiende el convoy de los piratas (ver raid_convoys)."""
    import json
    from datetime import timedelta

    from app.models import TransportMission
    from app.services.combat import travel_seconds
    from app.services.economy import planet_stocks
    from app.services.training import get_or_create_unit_stock, player_units

    now = datetime.now(UTC)
    cargo = {k: int(v) for k, v in cargo.items() if v and int(v) > 0}
    escort = {k: int(v) for k, v in (escort or {}).items() if v and int(v) > 0}
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

    # Anti-abuso (SDD 42): ≤ N naves de carga despachadas por ventana de 2h (rolling = resetea).
    from datetime import timedelta as _td

    from app.models import GameEvent
    s = get_settings()
    since = now - _td(seconds=s.market_window_seconds)
    sent = sum(
        json.loads(e.payload or "{}").get("ships", 0)
        for e in (await session.execute(select(GameEvent).where(
            GameEvent.player_id == player.id, GameEvent.type == "transport_launched",
            GameEvent.created_at >= since,
        ))).scalars()
    )
    hangars = await _count_buildings(session, player.id, "hangar")
    cap = s.market_transport_ships_per_window + hangars * s.market_transport_ships_per_hangar
    if sent + ships_needed > cap:
        raise MarketError(
            f"Límite 2h: hasta {cap} naves de carga (construí hangares para más); "
            f"despachaste {int(sent)}. Las demás esperan en el hangar."
        )

    if escort:   # la escolta debe estar disponible (unidades militares, no naves de carga)
        owned = await player_units(session, player.id)
        for u, q in escort.items():
            if u == "cargo_ship":
                raise MarketError("Las naves de carga no escoltan; usá unidades militares.")
            if owned.get(u, 0) < q:
                raise MarketError(f"No tenés {q} de {u} para escoltar (tenés {owned.get(u, 0)}).")

    for m, q in cargo.items():   # la carga sale del origen ya
        (await get_or_create_stock(session, player.id, m, from_planet)).amount -= q
    (await get_or_create_unit_stock(session, player.id, "cargo_ship")).quantity -= ships_needed
    for u, q in escort.items():   # la escolta también parte (vuelve si sobrevive)
        (await get_or_create_unit_stock(session, player.id, u)).quantity -= q

    travel = travel_seconds(from_planet, to_planet)
    mission = TransportMission(
        player_id=player.id, from_planet=from_planet, to_planet=to_planet,
        cargo=json.dumps(cargo), escort=json.dumps(escort), ships=ships_needed, status="outbound",
        arrives_at=now + timedelta(seconds=travel),
    )
    session.add(mission)
    await session.flush()
    from app.services.journal import record
    await record(session, "transport_launched", player.id,
                 from_planet=from_planet, to_planet=to_planet, cargo=cargo,
                 ships=ships_needed, escort=escort)
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
        for unit, qty in json.loads(m.escort or "{}").items():   # la escolta superviviente vuelve
            (await get_or_create_unit_stock(session, m.player_id, unit)).quantity += qty
        m.status = "done"
        done += 1
    return done


# --------------------------------------------------------------------------- #
# Piratería: convoyes interceptados; la escolta militar los defiende (SDD 42 §8)
# --------------------------------------------------------------------------- #
def _raid_outcome(escort: dict[str, int], total_cargo: int, s) -> tuple[str, dict[str, int], float]:
    """Resuelve un asalto pirata a un convoy (misma lógica de pérdidas por proporción de poder que
    resolve_combat). Devuelve (resultado, bajas_de_escolta, fracción_de_carga_robada)."""
    from app.services.combat import _force_power

    pirate = s.pirate_strength * total_cargo
    defense = _force_power(escort, "defense")
    total = pirate + defense
    if pirate <= 0 or total <= 0:
        return ("safe", {}, 0.0)
    loss_ratio = pirate / total
    losses = {
        k: min(q, round(q * loss_ratio)) for k, q in escort.items() if round(q * loss_ratio) > 0
    }
    if defense >= pirate:
        return ("defended", losses, 0.0)   # la escolta repele; algunas bajas, carga intacta
    stolen = min(s.pirate_loss_cap, (pirate - defense) / pirate)
    return ("raided", losses, stolen)


async def raid_convoys(
    session: AsyncSession, now: datetime | None = None, force: bool = False
) -> int:
    """Tick del mundo: con prob. `pirate_raid_chance`, los piratas emboscan convoyes en vuelo. La
    `escort` los defiende; si pierden, roban hasta `pirate_loss_cap` de la carga (perdida) y la
    escolta sufre bajas. `force=True` salta el dado (para tests/admin)."""
    import json
    import random

    from app.models import TransportMission
    s = get_settings()
    now = now or datetime.now(UTC)
    res = await session.execute(
        select(TransportMission).where(TransportMission.status == "outbound")
    )
    raided = 0
    from app.services.journal import record
    for m in res.scalars():
        if not force and random.random() > s.pirate_raid_chance:
            continue
        escort = json.loads(m.escort or "{}")
        cargo = json.loads(m.cargo or "{}")
        total = sum(cargo.values())
        result, losses, stolen_frac = _raid_outcome(escort, total, s)
        if result == "safe":
            continue
        for u, lost in losses.items():   # las bajas de escolta no vuelven
            escort[u] = max(0, escort.get(u, 0) - lost)
        m.escort = json.dumps({k: v for k, v in escort.items() if v > 0})
        if result == "raided":
            stolen = {k: int(q * stolen_frac) for k, q in cargo.items() if int(q * stolen_frac) > 0}
            for k, q in stolen.items():
                cargo[k] -= q
            m.cargo = json.dumps(cargo)
            await record(session, "convoy_raided", m.player_id,
                         from_planet=m.from_planet, to_planet=m.to_planet,
                         stolen=stolen, escort_losses=losses)
            raided += 1
        else:   # defended
            await record(session, "convoy_defended", m.player_id,
                         from_planet=m.from_planet, to_planet=m.to_planet, escort_losses=losses)
    return raided


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


async def black_market(
    session: AsyncSession, player: Player, pay_mineral: str, pay_qty: int, get_mineral: str
) -> dict:
    """Mercado negro: **trueque** material-por-material (no se paga energía). Pagás con un mineral y
    recibís otro, valuados a los precios del hub de tu galaxia, pero con un *premium ilegal*
    (`black_market_rate` < 1) → siempre te dan menos que el cambio justo. Requiere una nave de carga
    (viajás con la mercancía) y no tiene los límites del mercado natal (el riesgo del contrabando).
    La carga sale y entra de tu planeta natal."""
    s = get_settings()
    pay_qty = int(pay_qty)
    if pay_qty <= 0:
        raise MarketError("Cantidad inválida.")
    if pay_mineral == get_mineral:
        raise MarketError("Elegí minerales distintos para el trueque.")
    mins = get_content().minerals
    if pay_mineral not in mins or get_mineral not in mins:
        raise MarketError("Mineral desconocido.")
    galaxy = player.galaxy_key
    if not galaxy:
        raise MarketError("No estás en ninguna galaxia.")
    from app.services.training import player_units
    if (await player_units(session, player.id)).get("cargo_ship", 0) < 1:
        raise MarketError("Necesitás una nave de carga para llegar al mercado negro.")

    home = player.planet_key
    stock = await get_or_create_stock(session, player.id, pay_mineral, home)
    if stock.amount < pay_qty:
        raise MarketError(
            f"No tenés {pay_qty} de {pay_mineral} en {home} (tenés {stock.amount:g})."
        )

    pay_price = (await _hub_row(session, galaxy, pay_mineral)).price
    get_price = (await _hub_row(session, galaxy, get_mineral)).price
    if get_price <= 0:
        raise MarketError("El mercado negro no cotiza ese mineral.")
    value = pay_price * pay_qty
    get_qty = int(value / get_price * s.black_market_rate)
    if get_qty <= 0:
        raise MarketError("El trueque no alcanza para 1 unidad. Subí la cantidad.")

    stock.amount -= pay_qty
    (await get_or_create_stock(session, player.id, get_mineral, home)).amount += get_qty

    from app.services.journal import record
    await record(session, "black_market", player.id, galaxy=galaxy,
                 pay_mineral=pay_mineral, pay_qty=pay_qty, get_mineral=get_mineral, get_qty=get_qty)
    return {"paid": pay_qty, "pay_mineral": pay_mineral, "received": get_qty,
            "get_mineral": get_mineral, "rate": s.black_market_rate}


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
