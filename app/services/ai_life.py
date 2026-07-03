"""SDD 69 Fase 4 — Vida artificial del búnker: research por niveles + autopiloto de robots.

Vos "desarrollás la inteligencia" subiendo `Player.ai_level` (gastás electrónica del búnker +
minerales avanzados). Cada nivel habilita un `autonomy_scope` (workers → mines → trade → colonize →
attack) — se implementa por sub-fases. `run_ai_autopilot` corre en el tick (patrón del proyecto) y
por ahora hace la sub-fase 1: mantener las minas STAFFEADAS con obreros (auto-entrena, acotado).

Todo detrás de flags (`artificial_life_enabled` para subir de nivel, `bunker_autonomy_enabled` para
que el autopiloto actúe). Reusa la economía existente (no reinventa)."""
from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import Base_, Bunker, Player


class AiLifeError(Exception):
    pass


def _level_spec(level: int) -> dict | None:
    for lv in get_content().ai_levels:
        if int(lv["level"]) == level:
            return lv
    return None


def ai_state(player: Player) -> dict:
    """Estado de la vida artificial para el snapshot: nivel actual, alcance de autonomía,
    y el costo/spec del PRÓXIMO nivel (si hay)."""
    cur = _level_spec(player.ai_level) if player.ai_level else None
    nxt = _level_spec((player.ai_level or 0) + 1)
    content = get_content()
    return {
        "level": player.ai_level or 0,
        "autopilot_on": bool(getattr(player, "ai_autopilot_on", True)),   # botón de parada
        "scope": (cur or {}).get("autonomy_scope", []),
        "speed": (cur or {}).get("speed_efficiency", 1.0),
        "quality": (cur or {}).get("quality", 0.0),
        "next": None if nxt is None else {
            "level": nxt["level"], "name": nxt.get("name", ""),
            "electronics": nxt.get("electronics", 0),
            "cost": content.resolve_cost(player.race_key, nxt.get("cost", {})),
            "scope": nxt.get("autonomy_scope", []),
        },
        "max": len(content.ai_levels),
    }


async def _total_electronics(session: AsyncSession, player_id: int) -> tuple[float, list[Bunker]]:
    bunkers = list((await session.execute(
        select(Bunker).where(Bunker.player_id == player_id).order_by(Bunker.id)
    )).scalars())
    return sum(b.electronics for b in bunkers), bunkers


async def evolve_ai(session: AsyncSession, player: Player) -> dict:
    """Sube 1 nivel la vida artificial: gasta la electrónica del búnker + minerales avanzados del
    planeta natal. Requiere la tech `artificial_life` y un búnker."""
    settings = get_settings()
    if not settings.artificial_life_enabled:
        raise AiLifeError("La vida artificial está desactivada en este mundo.")
    from app.services.research import researched_techs
    if "artificial_life" not in await researched_techs(session, player.id):
        raise AiLifeError("Requiere investigar: artificial_life.")
    nxt = _level_spec((player.ai_level or 0) + 1)
    if nxt is None:
        raise AiLifeError("La vida artificial ya está en su nivel máximo.")
    # electrónica al día antes de cobrar
    from app.services.bunkers import advance_bunker
    await advance_bunker(session, player)
    total_e, bunkers = await _total_electronics(session, player.id)
    if not bunkers:
        raise AiLifeError("Necesitás un búnker para desarrollar la IA.")
    need_e = float(nxt.get("electronics", 0))
    if total_e < need_e:
        raise AiLifeError(f"Electrónica insuficiente ({total_e:.0f}/{need_e:.0f}). Producila con "
                          "salas de investigación / laboratorio atómico.")
    content = get_content()
    cost = content.resolve_cost(player.race_key, nxt.get("cost", {}))
    from app.services.economy import get_or_create_stock, planet_stocks
    here = await planet_stocks(session, player.id, player.planet_key)
    for mineral, amount in cost.items():
        if here.get(mineral, 0.0) < amount:
            raise AiLifeError(f"Falta {mineral} en {player.planet_key} (necesita {amount:g}).")
    # cobrar: minerales del natal + electrónica de los búnkeres (en orden)
    for mineral, amount in cost.items():
        (await get_or_create_stock(session, player.id, mineral, player.planet_key)).amount -= amount
    left = need_e
    for b in bunkers:
        take = min(b.electronics, left)
        b.electronics -= take
        left -= take
        if left <= 0:
            break
    player.ai_level = int(player.ai_level or 0) + 1
    from app.services.journal import record
    await record(session, "ai_evolve", player.id, level=player.ai_level,
                 scope=nxt.get("autonomy_scope", []))
    await session.flush()
    return {"level": player.ai_level, "scope": nxt.get("autonomy_scope", [])}


async def run_ai_autopilot(session: AsyncSession, player: Player) -> int:
    """Autopiloto de robots (corre en el tick). Ejecuta las tareas del `autonomy_scope` del nivel,
    cada una acotada y con su try/except (una que falle no frena a las otras). Devuelve el nº de
    acciones. Respeta el INTERRUPTOR del jugador (`ai_autopilot_on`) — parada de emergencia.
    Scopes: workers (staffing) · mines (auto-construir) · trade (vender excedente) · colonize
    (auto-colonizar) · attack (sub-fase 3, pendiente)."""
    settings = get_settings()
    if not settings.bunker_autonomy_enabled or not (player.ai_level or 0):
        return 0
    if not getattr(player, "ai_autopilot_on", True):
        return 0   # el jugador lo paró (botón de emergencia)
    scope = (_level_spec(player.ai_level) or {}).get("autonomy_scope", [])
    total = 0
    if "workers" in scope:
        total += await _auto_workers(session, player, settings)
    if "mines" in scope:
        total += await _auto_mines(session, player)
    if "trade" in scope:
        total += await _auto_trade(session, player, settings)
    if "colonize" in scope:
        total += await _auto_colonize(session, player)
    return total


async def _home_base(session: AsyncSession, player: Player) -> Base_ | None:
    for b in (await session.execute(
        select(Base_).where(Base_.player_id == player.id)
    )).scalars():
        if b.planet_key == player.planet_key:
            return b
    return None


async def _auto_workers(session: AsyncSession, player: Player, settings) -> int:
    """Mantener las minas STAFFEADAS: auto-entrena obreros para cubrir el déficit (acotado por
    `ai_autopilot_worker_cap` y por lo que ya haya en cola)."""
    try:
        from app.models import TrainingOrder
        from app.services.economy import _player_buildings, mining_staffing
        from app.services.training import start_training
        content = get_content()
        buildings = await _player_buildings(session, player.id)
        _staff, available, required = await mining_staffing(session, player.id, buildings, content)
        deficit = required - available
        if deficit <= 0:
            return 0
        mining_power = content.units.get("worker", {}).get("mining_power", 1) or 1
        pending = (await session.execute(
            select(TrainingOrder).join(Base_, TrainingOrder.base_id == Base_.id).where(
                Base_.player_id == player.id, TrainingOrder.unit_key == "worker",
                TrainingOrder.status == "training")
        )).scalars().all()
        need = math.ceil(deficit / mining_power) - sum(o.quantity for o in pending)
        to_train = min(settings.ai_autopilot_worker_cap, max(0, need))
        if to_train <= 0:
            return 0
        home = await _home_base(session, player)
        if home is None:
            return 0
        await start_training(session, player, home, "worker", to_train)
        from app.services.journal import record
        await record(session, "ai_autopilot", player.id, action="staff_workers", qty=to_train)
        return to_train
    except Exception:
        return 0


async def _auto_mines(session: AsyncSession, player: Player) -> int:
    """Levantar 1 mina por tick de un mineral que la raza usa y que AÚN no minás en el natal
    (para que 'toda la exploración minera de todos los tipos esté al día')."""
    try:
        from app.services.build import start_build
        from app.services.economy import _player_buildings
        content = get_content()
        home = await _home_base(session, player)
        if home is None:
            return 0
        mined = {b.production_mineral for b in await _player_buildings(session, player.id)
                 if content.buildings.get(b.building_key, {}).get("category") == "mine"
                 and b.base_id == home.id and b.production_mineral}
        roles = content.races.get(player.race_key, {}).get("resource_roles", {}) or {}
        want = [m for m in dict.fromkeys(roles.values()) if m and m not in mined]
        for mineral in want:
            await start_build(session, player, home, "mine", mineral)   # falla si no alcanza
            from app.services.journal import record
            await record(session, "ai_autopilot", player.id, action="build_mine", mineral=mineral)
            return 1
        return 0
    except Exception:
        return 0


async def _auto_trade(session: AsyncSession, player: Player, settings) -> int:
    """Vender EXCEDENTE (conservador): si tenés un mercado y un mineral muy por encima del umbral,
    vendé un poco por energía. No toca minerales por debajo del umbral (no vende lo necesario)."""
    try:
        from app.services.market import player_market_planets, sell
        planets = await player_market_planets(session, player)
        if not planets:
            return 0
        from app.services.economy import planet_stocks
        for planet in planets:
            stocks = await planet_stocks(session, player.id, planet)
            top = max(stocks.items(), key=lambda kv: kv[1], default=(None, 0))
            if top[0] and top[1] >= settings.ai_trade_surplus_threshold:
                surplus = int(top[1] - settings.ai_trade_surplus_threshold)
                qty = min(settings.ai_trade_sell_qty, surplus)
                if qty > 0:
                    await sell(session, player, planet, top[0], qty)
                    from app.services.journal import record
                    await record(session, "ai_autopilot", player.id, action="sell_surplus",
                                 mineral=top[0], qty=qty)
                    return 1
        return 0
    except Exception:
        return 0


async def _auto_colonize(session: AsyncSession, player: Player) -> int:
    """Con una `colony_ship`, colonizar 1 planeta habitable no colonizado (auto-expansión;
    la colonia después mina y trae material). Acotado a 1 por tick; found_colony valida todo."""
    try:
        from app.services.colonization import compat, found_colony
        from app.services.research import researched_techs
        from app.services.training import player_units
        if (await player_units(session, player.id)).get("colony_ship", 0) < 1:
            return 0
        content = get_content()
        techs = await researched_techs(session, player.id)
        mine = {b.planet_key for b in (await session.execute(
            select(Base_).where(Base_.player_id == player.id))).scalars()}
        for pk in content.planets:
            if pk in mine:
                continue
            if player.galaxy_key and content.planet_galaxy.get(pk) != player.galaxy_key:
                continue
            if not compat(player.race_key, pk, techs).get("can_colonize"):
                continue
            await found_colony(session, player, pk, mode="surface", vehicle="colony_ship")
            from app.services.journal import record
            await record(session, "ai_autopilot", player.id, action="colonize", planet=pk)
            return 1
        return 0
    except Exception:
        return 0
