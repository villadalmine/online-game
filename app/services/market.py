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
