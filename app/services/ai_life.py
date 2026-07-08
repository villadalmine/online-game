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
        "brain_mode": (getattr(player, "ai_brain_mode", "rules") or "rules"),   # SDD 81
        "brain_stats": brain_stats_report(player),   # SDD 81 v2: rendimiento por ruta (readout)
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
            "quality_eff": round(min(1.6, base_q + bonus), 2),
            "posture": await ai_posture(session, player)}   # SDD 78 v7: postura aprendida


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
    # SDD 83: modo AGENTE — el LLM ejecuta acciones él mismo (tool-calling). Si hizo algo, este tick
    # lo maneja el agente; si no hizo nada o falló, cae al autopiloto determinista de abajo.
    mode = (getattr(player, "ai_brain_mode", "rules") or "rules").lower()
    if (mode == "agent" and settings.ai_agent_enabled
            and (player.ai_level or 0) >= settings.ai_brain_min_level):
        try:
            from app.services.ai_agent import run_agent_autopilot
            n = await run_agent_autopilot(session, player, settings)
            if n > 0:
                return n
        except Exception:
            pass
    scope = (_level_spec(player.ai_level) or {}).get("autonomy_scope", [])
    # SDD 78: el APRENDIZAJE modula qué tan "afilada" juega la IA (calidad efectiva x experiencia).
    q = float((await ai_learning(session, player)).get("quality_eff", 0.5))
    # SDD 81: la IA "desarrollada" puede PENSAR con el LLM (gpu/cloud/auto) qué priorizar.
    priority, prio_route = await _resolve_brain(session, player, scope)
    order = ["workers", "mines", "housing", "bunker", "trade", "colonize", "defend", "research",
             "diplomacy", "spy", "expedition", "repopulate", "attack"]
    if priority in order:                       # el LLM eligió → esa skill corre PRIMERO
        order = [priority] + [k for k in order if k != priority]
    total = 0
    for key in order:
        if key not in scope:
            continue
        before = total
        if key == "workers":
            total += await _auto_workers(session, player, settings, q)
        elif key == "mines":
            total += await _auto_mines(session, player)
        elif key == "housing":
            total += await _auto_housing(session, player)
        elif key == "bunker":
            total += await _auto_bunker(session, player)
        elif key == "trade":
            total += await _auto_trade(session, player, settings)
        elif key == "colonize":
            total += await _auto_colonize(session, player)
        elif key == "defend":
            total += await _auto_defend(session, player)
        elif key == "research":
            total += await _auto_research(session, player, scope)
        elif key == "diplomacy":
            total += await _auto_diplomacy(session, player)
        elif key == "spy":
            total += await _auto_spy(session, player)
        elif key == "expedition":
            total += await _auto_expedition(session, player)
        elif key == "repopulate":
            total += await _auto_repopulate(session, player)
        elif key == "attack":
            total += await _auto_attack(session, player, settings, q, use_meta="learn" in scope)
        # SDD 81 v5: el cerebro "APLICÓ" si el LLM eligió una skill VÁLIDA (aunque el juego no tenga
        # nada que hacer esa jugada) → readout no cae a 0%. El IMPACTO (acciones producidas) solo
        # PESA para que 'auto' prefiera la ruta que más rinde.
        if key == priority and prio_route:
            produced = total - before
            _record_brain(player, prio_route, "llm", weight=min(3.0, max(1.0, float(produced))))
    return total


async def _llm_pick_skill(
    session: AsyncSession, player: Player, scope: list, route: str
) -> str | None:
    """SDD 81: preguntale al LLM (por `route`) qué habilidad priorizar este turno. Devuelve una key
    del scope o None (→ reglas). Prompt chico, best-effort (cualquier fallo → None)."""
    try:
        import json

        from app.services.economy import player_stocks
        from app.services.llm import llm_chat
        content = get_content()
        skills = {s["key"]: (s.get("description") or "")[:70]
                  for s in content.ai_skills if s["key"] in scope}
        if not skills:
            return None
        st = await player_stocks(session, player.id)
        bases = len((await session.execute(
            select(Base_).where(Base_.player_id == player.id))).scalars().all())
        brief = {"minerales": {k: round(v) for k, v in list(st.items())[:6]},
                 "energia": round(player.energy), "bases": bases}
        sys = ("Sos el cerebro de una civilización autónoma en un juego de estrategia por turnos. "
               "Elegí UNA habilidad para priorizar ESTE turno. Respondé SOLO la key exacta "
               "(una palabra), nada más.")
        um = f"Habilidades: {json.dumps(skills, ensure_ascii=False)}\nEstado: {json.dumps(brief)}"
        reply = await llm_chat(
            [{"role": "system", "content": sys}, {"role": "user", "content": um}],
            max_tokens=12, route=route, kind="autopilot",   # SDD 81: su propio kind (no "npc")
            user=f"autopilot:{player.username}")
        pick = (reply or "").strip().strip('".,\n ').split()[0].lower() if reply else ""
        return pick if pick in scope else None
    except Exception:
        return None


def _brain_ratio(stats: dict, route: str) -> float:
    """SDD 81 v2: tasa de decisiones APLICADAS (llm) de una ruta, suavizada (Laplace) para no
    quedar pegada a la primera muestra. Sin datos → 0.5 (neutro, invita a probar)."""
    s = (stats or {}).get(route) or {}
    llm, fb = float(s.get("llm", 0)), float(s.get("fallback", 0))
    return (llm + 1.0) / (llm + fb + 2.0)


def brain_stats_report(player: Player) -> dict:
    """Rendimiento del cerebro por ruta para el snapshot/UI: aplicadas, fallback, tasa, muestras.
    Los conteos pueden ser fraccionarios (llevan decaimiento, ver `_record_brain`); se redondean."""
    import json
    try:
        stats = json.loads(getattr(player, "ai_brain_stats", "") or "{}")
    except Exception:
        stats = {}
    out = {}
    for route in ("gpu", "cloud"):
        s = stats.get(route) or {}
        llm, fb = float(s.get("llm", 0)), float(s.get("fallback", 0))
        n = llm + fb
        if n > 0.01:
            out[route] = {"applied": round(llm), "fallback": round(fb),
                          "n": round(n), "ratio": round(llm / n, 2)}
    return out


def _brain_budget_ok(player: Player, settings) -> bool:
    """SDD 81 v4: tope diario de llamadas LLM del cerebro por jugador (control de costo). Cuenta en
    `ai_brain_stats` bajo `_day`/`_calls` (sin migración; se resetea al cambiar el día). True = hay
    presupuesto (y consume 1); False = agotado → la IA cae a reglas ese turno. 0 = sin tope."""
    import json
    from datetime import UTC, datetime
    cap = int(getattr(settings, "ai_brain_llm_calls_per_day", 0) or 0)
    if cap <= 0:
        return True
    try:
        stats = json.loads(getattr(player, "ai_brain_stats", "") or "{}")
    except Exception:
        stats = {}
    today = datetime.now(UTC).date().isoformat()
    if stats.get("_day") != today:
        stats["_day"], stats["_calls"] = today, 0
    used = int(stats.get("_calls", 0))
    if used >= cap:
        player.ai_brain_stats = json.dumps(stats)   # persistí el reset del día aunque no haya cupo
        return False
    stats["_calls"] = used + 1
    player.ai_brain_stats = json.dumps(stats)
    return True


def _record_brain(player: Player, route: str, outcome: str, weight: float = 1.0) -> None:
    """SDD 81 v2/v5: registra el resultado de una decisión del cerebro (readout + auto-switch) + la
    métrica global. `outcome=llm` = la ruta ELIGIÓ una skill válida del scope (el cerebro aplicó);
    `fallback` = no supo elegir (LLM inalcanzable/basura) → cayó a reglas. El `weight` de un acierto
    PESA el impacto (acciones producidas, tope 3) para que 'auto' prefiera la ruta que más rinde.
    Aplica DECAIMIENTO (media móvil) para adaptarse a lo reciente, no arrastrar el historial."""
    import json
    metrics.AI_AUTOPILOT_BRAIN.inc(outcome=outcome, route=route)
    decay = get_settings().ai_brain_decay
    try:
        stats = json.loads(getattr(player, "ai_brain_stats", "") or "{}")
    except Exception:
        stats = {}
    s = stats.setdefault(route, {"llm": 0, "fallback": 0})
    s["llm"] = round(float(s.get("llm", 0)) * decay, 4)
    s["fallback"] = round(float(s.get("fallback", 0)) * decay, 4)
    # v4: el crédito de un acierto PESA el impacto (cuántas acciones produjo la skill, con tope);
    # un fallo suma 1. Así 'auto' prefiere la ruta cuyas decisiones RINDEN más (no solo "hacen").
    s[outcome] = round(float(s.get(outcome, 0)) + (weight if outcome == "llm" else 1.0), 4)
    player.ai_brain_stats = json.dumps(stats)   # reasignar → SQLAlchemy detecta el cambio (Text)


async def _resolve_brain(
    session: AsyncSession, player: Player, scope: list
) -> tuple[str | None, str | None]:
    """SDD 81: según `Player.ai_brain_mode` (rules|gpu|cloud|auto) la IA piensa con el LLM o reglas.
    v2: 'auto' es un BANDIT — prefiere la ruta con mejor tasa (por jugador), con exploración
    `ai_brain_explore`. Devuelve (skill_priorizada, ruta): la ruta que eligió se registra DESPUÉS,
    según si la skill produjo algo (calidad); las rutas que no eligen se marcan fallback acá. Solo
    desde `ai_brain_min_level` con el flag; ante todo fallo → (None, None) = reglas."""
    import random
    settings = get_settings()
    mode = (getattr(player, "ai_brain_mode", "rules") or "rules").lower()
    # 'agent' (SDD 83) tiene su propio camino en run_ai_autopilot; acá se comporta como reglas (el
    # despacho determinista es el fallback cuando el agente no hizo nada).
    if (not settings.ai_autopilot_brain_enabled or mode in ("rules", "agent")
            or (player.ai_level or 0) < settings.ai_brain_min_level):
        return None, None
    if mode == "auto":
        stats = {}
        try:
            import json
            stats = json.loads(getattr(player, "ai_brain_stats", "") or "{}")
        except Exception:
            stats = {}
        if random.random() < settings.ai_brain_explore:
            routes = ["gpu", "cloud"]
            random.shuffle(routes)                                   # explorar: probá cualquiera
        else:
            routes = sorted(["gpu", "cloud"], key=lambda r: _brain_ratio(stats, r), reverse=True)
    else:
        routes = [mode]
    for route in routes:
        if not _brain_budget_ok(player, settings):   # SDD 81 v4: sin cupo diario → reglas (costo)
            break
        pick = await _llm_pick_skill(session, player, scope, route)
        if pick:
            return pick, route          # el caller registra según la PRODUCTIVIDAD de la skill
        _record_brain(player, route, "fallback")   # esta ruta no supo elegir → miss inmediato
    return None, None


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
    """Levantar 1 mina por tick de un mineral que la raza usa y que AÚN no minás en ALGUNA base
    (natal primero, después colonias) — para que 'toda la exploración minera de todos los tipos esté
    al día' en TODAS las bases, no solo en la natal (antes se quedaba corto en las colonias)."""
    try:
        from app.services.build import start_build
        from app.services.economy import _player_buildings
        content = get_content()
        home = await _home_base(session, player)
        bases = (await session.execute(
            select(Base_).where(Base_.player_id == player.id))).scalars().all()
        bases = sorted(bases, key=lambda b: (home is None or b.id != home.id))   # natal primero
        blds = await _player_buildings(session, player.id)
        roles = content.races.get(player.race_key, {}).get("resource_roles", {}) or {}
        want = [m for m in dict.fromkeys(roles.values()) if m]
        for base in bases:
            mined = {b.production_mineral for b in blds
                     if content.buildings.get(b.building_key, {}).get("category") == "mine"
                     and b.base_id == base.id and b.production_mineral}
            for mineral in want:
                if mineral in mined:
                    continue
                try:
                    await start_build(session, player, base, "mine", mineral)   # falla si no da
                    from app.services.journal import record
                    metrics.AI_AUTOPILOT.inc(action="build_mine")
                    await record(session, "ai_autopilot", player.id, action="build_mine",
                                 mineral=mineral, base_id=base.id)
                    return 1
                except Exception:
                    continue
        return 0
    except Exception:
        return 0


async def _auto_housing(session: AsyncSession, player: Player) -> int:
    """SDD 78 v8: se da cuenta si a un dominio le faltan plazas (unidades sin lugar) y construye el
    edificio que aloja ese dominio en la base natal."""
    try:
        from app.services.build import start_build
        from app.services.economy import _player_buildings
        from app.services.housing import houses_for_domain, housing_report
        from app.services.training import player_units
        home = await _home_base(session, player)
        if home is None:
            return 0
        akeys = [b.building_key for b in await _player_buildings(session, player.id)
                 if b.status == "active"]
        rep = housing_report(akeys, await player_units(session, player.id), {})
        for d, c in rep.items():
            if c.get("free", 0) <= 0 and c.get("occupancy", 0) > 0:   # dominio lleno con unidades
                for bk in houses_for_domain(d):
                    try:
                        await start_build(session, player, home, bk)
                        from app.services.journal import record
                        metrics.AI_AUTOPILOT.inc(action="housing")
                        await record(session, "ai_autopilot", player.id, action="housing",
                                     building=bk, domain=d)
                        return 1
                    except Exception:
                        continue
        return 0
    except Exception:
        return 0


async def _auto_bunker(session: AsyncSession, player: Player) -> int:
    """SDD 78 v8 / v5-fix: desarrolla el búnker de TODAS las bases (no solo la natal) — lo cava si
    falta y construye una sala de investigación (electrónica, la moneda que sostiene y evoluciona la
    IA). Antes solo tocaba la base natal → los búnkeres de las colonias quedaban vacíos. Requiere
    `bunker_engineering`. 1 acción por tick (natal primero, después colonias)."""
    try:
        if not get_settings().bunkers_enabled:
            return 0
        from app.services.research import researched_techs
        if "bunker_engineering" not in await researched_techs(session, player.id):
            return 0
        from app.services.bunkers import _bunker_for_base, build_room, dig
        from app.services.journal import record
        home = await _home_base(session, player)
        bases = (await session.execute(
            select(Base_).where(Base_.player_id == player.id))).scalars().all()
        bases = sorted(bases, key=lambda b: (home is None or b.id != home.id))   # natal primero
        # 1) cavar el búnker en cualquier base que aún no tenga (empezando por la natal)
        for b in bases:
            if await _bunker_for_base(session, b.id) is None:
                await dig(session, player, b.id)
                metrics.AI_AUTOPILOT.inc(action="bunker")
                await record(session, "ai_autopilot", player.id, action="bunker", op="dig",
                             base_id=b.id)
                return 1
        # 2) construir una sala de investigación en el primer búnker con lugar (electrónica)
        for b in bases:
            try:
                await build_room(session, player, b.id, "research_room")   # auto-celda
                metrics.AI_AUTOPILOT.inc(action="bunker")
                await record(session, "ai_autopilot", player.id, action="bunker", op="room",
                             base_id=b.id)
                return 1
            except Exception:
                continue
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


async def _auto_repopulate(session: AsyncSession, player: Player) -> int:
    """SDD 78 v5: si te ATACARON hace poco (última hora) y te faltan edificios de algún set, gastá
    electrónica para reconstruir lo que falta (repopulate ya es idempotente). 1 set por tick."""
    try:
        if not get_settings().bunkers_enabled:
            return 0
        from datetime import UTC, datetime, timedelta

        from app.models import Building, CombatLog
        from app.services.bunkers import repopulate
        content = get_content()
        since = datetime.now(UTC) - timedelta(hours=1)
        hit = (await session.execute(
            select(CombatLog).where(
                CombatLog.defender_id == player.id, CombatLog.outcome == "attacker",
                CombatLog.created_at >= since).limit(1)
        )).scalars().first()
        if hit is None:
            return 0                              # sin ataque reciente → no reconstruye
        for b in (await session.execute(
            select(Base_).where(Base_.player_id == player.id))).scalars().all():
            active = {x.building_key for x in (await session.execute(
                select(Building).where(
                    Building.base_id == b.id, Building.status == "active"))).scalars()}
            for sk in sorted(content.repop_sets,
                             key=lambda k: content.repop_sets[k].get("electronics", 0)):
                spec = content.repop_sets[sk]
                missing = any(bk != "headquarters" and bk not in active
                              for bk in spec.get("buildings", []))
                if not missing:
                    continue
                try:
                    await repopulate(session, player, b.id, sk)   # idempotente: solo lo que falta
                    metrics.AI_AUTOPILOT.inc(action="repopulate")
                    from app.services.journal import record
                    await record(session, "ai_autopilot", player.id, action="repopulate",
                                 base_id=b.id)
                    return 1
                except Exception:
                    continue
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


async def _meta_best_unit(session: AsyncSession) -> str | None:
    """SDD 78 v6: la unidad que MÁS gana según la meta aprendida (SDD 41), con muestra chica."""
    try:
        from app.services.insights import get_insights
        payload = (await get_insights(session)).get("winrate_by_unit", {}).get("payload", {})
        best, best_rate = None, 0.0
        for u, d in payload.items():
            if isinstance(d, dict) and d.get("n", 0) >= 3 and d.get("rate", 0) > best_rate:
                best, best_rate = u, d["rate"]
        return best
    except Exception:
        return None


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


async def ai_posture(session: AsyncSession, player: Player) -> str:
    """SDD 78 v7: la IA elige POSTURA con lo aprendido de sus batallas (tipo bandit): agresiva si
    viene ganando, defensiva si perdiendo, balanceada sin evidencia. Modula margen + reserva."""
    n, wr = await _own_attack_winrate(session, player)
    if n < 4:
        return "balanced"
    if wr >= 0.6:
        return "aggressive"
    if wr < 0.4:
        return "defensive"
    return "balanced"


# SDD 81 v3/v4: skills del autopiloto que quedan BLOQUEADAS sin una tech → research las prioriza.
_SKILL_GATE_TECH = {"bunker": "bunker_engineering", "defend": "weapons", "spy": "satellite_tech",
                    "colonize": "antigravity", "expedition": "antigravity"}


def _first_researchable_toward(content, target_key: str, have: set) -> str | None:
    """La primera tech researchable YA (prereq cumplido) en la cadena de prereqs hacia `target_key`.
    Camina `requires_tech` hacia atrás hasta una con el prereq cumplido. None si ya la tenés."""
    key, seen = target_key, set()
    while key and key not in have and key not in seen:
        seen.add(key)
        t = content.technologies.get(key)
        if not t:
            return None
        req = t.get("requires_tech")
        if not req or req in have:
            return key                          # researchable ahora (sin prereq o ya cumplido)
        key = req
    return None


async def _auto_research(session: AsyncSession, player: Player, scope: list | None = None) -> int:
    """SDD 78: investigar la próxima tecnología asequible de economía/defensa (la más barata).
    SDD 81 v3: si un skill del scope está BLOQUEADO por falta de tech, prioriza esa tech (o el
    próximo paso researchable de su cadena de prereqs) antes que la simple 'más barata'."""
    try:
        from app.services.research import researched_techs, start_research
        content = get_content()
        have = await researched_techs(session, player.id)
        # techs que DESBLOQUEAN un skill del scope (resolviendo la cadena de prereqs al paso viable)
        wanted = set()
        for skill in (scope or []):
            gate = _SKILL_GATE_TECH.get(skill)
            if gate and gate not in have:
                step = _first_researchable_toward(content, gate, have)
                if step:
                    wanted.add(step)
        cats = ("economy", "military", "underground", "espionage", "colonization")
        cands = [t for k, t in content.technologies.items()
                 if k not in have and (t.get("category") in cats or k in wanted)
                 and (not t.get("requires_tech") or t["requires_tech"] in have)]
        # primero las que desbloquean un skill (wanted), después por costo
        cands.sort(key=lambda t: (t["key"] not in wanted, sum((t.get("cost") or {}).values())))
        for t in cands[:5]:                # probá las prioritarias/baratas; start_research valida
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
    session: AsyncSession, player: Player, settings, quality: float = 0.5, use_meta: bool = False
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
        # SDD 78 v7: POSTURA aprendida (bandit) modula margen + reserva (v2: experiencia afina más).
        posture = await ai_posture(session, player)
        reserve = settings.ai_attack_reserve
        margin = settings.ai_attack_margin - (quality - 0.5) * 0.6
        if posture == "aggressive":
            margin -= 0.2                                   # confiada: pelea más ajustado…
            reserve *= 0.7                                  # …y compromete más tropa
        elif posture == "defensive":
            margin += 0.5                                   # cauta: solo goleadas…
            reserve = min(0.9, reserve * 1.5)              # …y guarda tropa en casa
        margin = max(1.05, margin)
        # SDD 78 v6: con la skill `learn`, prioriza la composición que GANA según la meta aprendida.
        best_unit = await _meta_best_unit(session) if use_meta else None
        force = {}
        for k in combat_keys:
            frac = (1.0 - reserve) * (0.6 if (best_unit and k != best_unit) else 1.0)
            force[k] = int(mine.get(k, 0) * frac)
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
                     target_base_id=best.id, force=force, posture=posture)
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
