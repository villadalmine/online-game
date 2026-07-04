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
from app.core import metrics
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


async def ai_learning(session: AsyncSession, player: Player) -> dict:
    """SDD 78: la IA APRENDE con la experiencia. xp = nº de jugadas del autopiloto (del journal); la
    calidad EFECTIVA sube con la experiencia (log, con tope). Sin migración (deriva del journal)."""
    from sqlalchemy import func

    from app.models import GameEvent
    xp = (await session.execute(
        select(func.count()).select_from(GameEvent).where(
            GameEvent.player_id == player.id, GameEvent.type == "ai_autopilot")
    )).scalar() or 0
    base_q = float((_level_spec(player.ai_level or 0) or {}).get("quality", 0.0))
    bonus = min(0.5, 0.06 * math.log10(1 + int(xp)))   # hasta +0.5 de calidad por experiencia
    return {"xp": int(xp), "quality_base": round(base_q, 2),
            "quality_eff": round(min(1.6, base_q + bonus), 2)}


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
    # SDD 78: el APRENDIZAJE modula qué tan "afilada" juega la IA (calidad efectiva x experiencia).
    q = float((await ai_learning(session, player)).get("quality_eff", 0.5))
    total = 0
    if "workers" in scope:
        total += await _auto_workers(session, player, settings, q)
    if "mines" in scope:
        total += await _auto_mines(session, player)
    if "trade" in scope:
        total += await _auto_trade(session, player, settings)
    if "colonize" in scope:
        total += await _auto_colonize(session, player)
    if "defend" in scope:                       # SDD 78: fortifica bases sin defensa
        total += await _auto_defend(session, player)
    if "research" in scope:                     # SDD 78: investiga tecnología útil
        total += await _auto_research(session, player)
    if "diplomacy" in scope:                    # SDD 78: negocia nucleares entrantes
        total += await _auto_diplomacy(session, player)
    if "spy" in scope:                          # SDD 78 v3: espía rivales antes de atacar
        total += await _auto_spy(session, player)
    if "expedition" in scope:                   # SDD 78 v4: expediciones a lunas
        total += await _auto_expedition(session, player)
    if "attack" in scope:
        total += await _auto_attack(session, player, settings, q)
    return total


async def _home_base(session: AsyncSession, player: Player) -> Base_ | None:
    for b in (await session.execute(
        select(Base_).where(Base_.player_id == player.id)
    )).scalars():
        if b.planet_key == player.planet_key:
            return b
    return None


async def _auto_workers(
    session: AsyncSession, player: Player, settings, quality: float = 0.5
) -> int:
    """Mantener las minas STAFFEADAS: auto-entrena obreros para cubrir el déficit. El cap por tick
    ESCALA con la calidad efectiva (SDD 78: una IA más entrenada staffea más rápido)."""
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
        cap = max(1, round(settings.ai_autopilot_worker_cap * (0.5 + quality)))   # SDD 78: aprende
        to_train = min(cap, max(0, need))
        if to_train <= 0:
            return 0
        home = await _home_base(session, player)
        if home is None:
            return 0
        await start_training(session, player, home, "worker", to_train)
        from app.services.journal import record
        metrics.AI_AUTOPILOT.inc(action="staff_workers")
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
            metrics.AI_AUTOPILOT.inc(action="build_mine")
            await record(session, "ai_autopilot", player.id, action="build_mine", mineral=mineral)
            return 1
        return 0
    except Exception:
        return 0


async def _auto_defend(session: AsyncSession, player: Player) -> int:
    """SDD 78: construir 1 torreta en una base SIN defensa activa (que no se pierdan colonias)."""
    try:
        from app.models import Base_, Building
        from app.services.build import start_build
        content = get_content()
        bases = (await session.execute(
            select(Base_).where(Base_.player_id == player.id)
        )).scalars().all()
        if not bases:
            return 0
        active = (await session.execute(
            select(Building.base_id, Building.building_key).where(
                Building.base_id.in_([b.id for b in bases]), Building.status == "active")
        )).all()
        defd = {bid for bid, bk in active
                if content.buildings.get(bk, {}).get("defense_power", 0) > 0}
        for b in bases:
            if b.id not in defd:
                await start_build(session, player, b, "turret")   # falla si no alcanza el material
                from app.services.journal import record
                metrics.AI_AUTOPILOT.inc(action="defend")
                await record(session, "ai_autopilot", player.id, action="defend", base_id=b.id)
                return 1
        return 0
    except Exception:
        return 0


async def _auto_diplomacy(session: AsyncSession, player: Player) -> int:
    """SDD 78: ante un NUCLEAR entrante, si tenés government + diplomacy, ofrecé un tributo modesto
    (10% de tu estructural, tope 2000) para que lo cancelen — como hace la NPC, pero para tu IA."""
    try:
        import json

        from app.models import StrikeMission
        from app.services.economy import planet_stocks
        from app.services.strike import offer_tribute
        rows = (await session.execute(
            select(StrikeMission).where(
                StrikeMission.defender_id == player.id, StrikeMission.status == "outbound")
        )).scalars().all()
        for m in rows:
            if m.tribute or "nuclear_missile" not in json.loads(m.force):
                continue
            here = await planet_stocks(session, player.id, player.planet_key)
            struct = get_content().resolve_role(player.race_key, "structural")
            amt = round(min(here.get(struct, 0.0) * 0.1, 2000.0))
            if amt < 100:
                continue
            await offer_tribute(session, player, m.id, {struct: amt}, 0.0)   # valida gov+diplomacy
            metrics.AI_AUTOPILOT.inc(action="diplomacy")
            from app.services.journal import record
            await record(session, "ai_autopilot", player.id, action="diplomacy", mission_id=m.id)
            return 1
        return 0
    except Exception:
        return 0


async def _auto_spy(session: AsyncSession, player: Player) -> int:
    """SDD 78 v3: lanzar un satélite espía a un rival que AÚN no espiás (conocer su defensa)."""
    try:
        if not get_settings().satellites_enabled:
            return 0
        from app.services.training import player_units
        if (await player_units(session, player.id)).get("spy_satellite", 0) < 1:
            return 0
        from app.models import SatelliteMission
        from app.services.satellites import launch
        already = {m.target_id for m in (await session.execute(
            select(SatelliteMission).where(SatelliteMission.owner_id == player.id,
                                           SatelliteMission.kind == "spy"))).scalars()}
        rows = (await session.execute(
            select(Player).where(Player.id != player.id, Player.race_key.is_not(None))
        )).scalars().all()
        for foe in rows:
            if foe.id in already:
                continue
            if player.alliance_id and foe.alliance_id == player.alliance_id:
                continue
            if not foe.is_npc and foe.galaxy_instance_id != player.galaxy_instance_id:
                continue
            await launch(session, player, "spy_satellite", foe.id)
            metrics.AI_AUTOPILOT.inc(action="spy")
            from app.services.journal import record
            await record(session, "ai_autopilot", player.id, action="spy", target_id=foe.id)
            return 1
        return 0
    except Exception:
        return 0


async def _auto_expedition(session: AsyncSession, player: Player) -> int:
    """SDD 78 v4: mandar 1 expedición a una luna de tu galaxia que no tengas ya en viaje (bonus de
    dioses). start_expedition valida unidad requerida + energía → si no puede, prueba otra luna."""
    try:
        from app.models import ExpeditionOrder
        from app.services.expedition import start_expedition
        content = get_content()
        active = {e.moon_key for e in (await session.execute(
            select(ExpeditionOrder).where(ExpeditionOrder.player_id == player.id,
                                          ExpeditionOrder.status == "traveling"))).scalars()}
        for mk in content.moons:
            if mk in active or content.moon_galaxy(mk) != player.galaxy_key:
                continue
            try:
                await start_expedition(session, player, mk)
                metrics.AI_AUTOPILOT.inc(action="expedition")
                from app.services.journal import record
                await record(session, "ai_autopilot", player.id, action="expedition", moon=mk)
                return 1
            except Exception:
                continue
        return 0
    except Exception:
        return 0


async def _own_attack_winrate(session: AsyncSession, player: Player) -> tuple[int, float]:
    """SDD 78 v3: win-rate de los últimos ataques propios (la IA aprende de sus batallas)."""
    from app.models import CombatLog
    rows = (await session.execute(
        select(CombatLog).where(CombatLog.attacker_id == player.id)
        .order_by(CombatLog.id.desc()).limit(10)
    )).scalars().all()
    if not rows:
        return 0, 1.0
    wins = sum(1 for r in rows if r.outcome == "attacker")
    return len(rows), wins / len(rows)


async def _auto_research(session: AsyncSession, player: Player) -> int:
    """SDD 78: investigar la próxima tecnología asequible de economía/defensa (la más barata)."""
    try:
        from app.services.research import researched_techs, start_research
        content = get_content()
        have = await researched_techs(session, player.id)
        cats = ("economy", "military", "underground", "espionage", "colonization")
        cands = [t for k, t in content.technologies.items()
                 if k not in have and t.get("category") in cats
                 and (not t.get("requires_tech") or t["requires_tech"] in have)]
        cands.sort(key=lambda t: sum((t.get("cost") or {}).values()))
        for t in cands[:4]:                     # probá las más baratas; start_research valida
            try:
                await start_research(session, player, t["key"])
                from app.services.journal import record
                metrics.AI_AUTOPILOT.inc(action="research")
                await record(session, "ai_autopilot", player.id, action="research", tech=t["key"])
                return 1
            except Exception:
                continue
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
                    metrics.AI_AUTOPILOT.inc(action="sell_surplus")
                    await record(session, "ai_autopilot", player.id, action="sell_surplus",
                                 mineral=top[0], qty=qty)
                    return 1
        return 0
    except Exception:
        return 0


async def _auto_attack(
    session: AsyncSession, player: Player, settings, quality: float = 0.5
) -> int:
    """Sub-fase 3: ataque autónomo. Solo ataca a un rival que SUPERA claramente (poder de ataque >
    defensa estimada × margen). El margen se AFILA con la calidad efectiva (SDD 78: una IA entrenada
    se anima a peleas más ajustadas, como un jugador con experiencia). Deja RESERVA en casa.
    Reusa los estimadores de la NPC + `start_attack` (que aplica topes SDD 55, protección, energía →
    si no se puede, corta). 1 ataque por tick. El botón STOP ya se chequeó arriba."""
    try:
        from app.services.combat import start_attack
        from app.services.npc import _base_defense_estimate, _force_attack_power
        from app.services.training import player_units, units_at_base
        home = await _home_base(session, player)
        if home is None:
            return 0
        combat_keys = ("soldier", "tank", "aircraft")
        mine = (await units_at_base(session, player.id, home.id)) if settings.garrison_enabled \
            else (await player_units(session, player.id))
        reserve = settings.ai_attack_reserve
        # fuerza a enviar = (1-reserva) de cada unidad de combate; deja el resto para defender.
        force = {k: int(mine.get(k, 0) * (1.0 - reserve)) for k in combat_keys}
        force = {k: v for k, v in force.items() if v > 0}
        if not force:
            return 0
        my_power = _force_attack_power(force)
        # candidatos: bases de otros jugadores (start_attack filtra aliado/novato/galaxia/etc).
        rows = (await session.execute(
            select(Base_).join(Player, Base_.player_id == Player.id).where(
                Base_.player_id != player.id)
        )).scalars().all()
        best = None
        best_def = 0.0
        margin = max(1.05, settings.ai_attack_margin - (quality - 0.5) * 0.6)   # SDD 78: aprende
        n, wr = await _own_attack_winrate(session, player)   # SDD 78 v3: aprende de sus batallas
        if n >= 4 and wr < 0.4:
            margin += 0.5                                    # viene perdiendo → ataca más cauta
        for b in rows:
            defense = await _base_defense_estimate(session, b)
            beatable = my_power > defense * margin
            if beatable and (best is None or defense > best_def):
                best, best_def = b, defense   # el más fuerte que igual superás (mejor botín)
        if best is None:
            return 0
        await start_attack(session, player, best.id, force, source_base_id=home.id)
        from app.services.journal import record
        metrics.AI_AUTOPILOT.inc(action="attack")
        await record(session, "ai_autopilot", player.id, action="attack",
                     target_base_id=best.id, force=force)
        return 1
    except Exception:
        return 0   # CombatError (topes/protección/energía) u otro → no ataca este tick


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
            metrics.AI_AUTOPILOT.inc(action="colonize")
            await record(session, "ai_autopilot", player.id, action="colonize", planet=pk)
            return 1
        return 0
    except Exception:
        return 0
