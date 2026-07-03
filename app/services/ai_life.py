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
    """Autopiloto de robots (corre en el tick). Sub-fase 1: si el nivel incluye `workers`, mantiene
    las minas STAFFEADAS auto-entrenando obreros (acotado por `ai_autopilot_worker_cap` y por lo que
    haya en cola). Devuelve cuántos obreros encargó. Silencioso ante cualquier fallo (no rompe el
    tick). Sub-fases próximas: mines/trade/colonize/attack."""
    settings = get_settings()
    if not settings.bunker_autonomy_enabled or not (player.ai_level or 0):
        return 0
    spec = _level_spec(player.ai_level) or {}
    scope = spec.get("autonomy_scope", [])
    if "workers" not in scope:
        return 0
    try:
        from app.services.economy import _player_buildings, mining_staffing
        from app.services.training import start_training
        content = get_content()
        buildings = await _player_buildings(session, player.id)
        _staff, available, required = await mining_staffing(session, player.id, buildings, content)
        deficit = required - available    # slots sin cubrir (en unidades de mining_power)
        if deficit <= 0:
            return 0
        mining_power = content.units.get("worker", {}).get("mining_power", 1) or 1
        # obreros ya en cola (no re-pedir de más).
        from app.models import TrainingOrder
        pending = (await session.execute(
            select(TrainingOrder).join(Base_, TrainingOrder.base_id == Base_.id).where(
                Base_.player_id == player.id, TrainingOrder.unit_key == "worker",
                TrainingOrder.status == "training")
        )).scalars().all()
        pending_qty = sum(o.quantity for o in pending)
        need = math.ceil(deficit / mining_power) - pending_qty
        to_train = min(settings.ai_autopilot_worker_cap, max(0, need))
        if to_train <= 0:
            return 0
        # entrenar en el mundo natal (el HQ siempre está ahí).
        home = next((b for b in await _bases(session, player.id)
                     if b.planet_key == player.planet_key), None)
        if home is None:
            return 0
        await start_training(session, player, home, "worker", to_train)
        from app.services.journal import record
        await record(session, "ai_autopilot", player.id, action="staff_workers", qty=to_train)
        return to_train
    except Exception:
        return 0   # afford/housing/energía/etc → el autopiloto simplemente no actúa este tick


async def _bases(session: AsyncSession, player_id: int) -> list[Base_]:
    return list((await session.execute(
        select(Base_).where(Base_.player_id == player_id)
    )).scalars())
