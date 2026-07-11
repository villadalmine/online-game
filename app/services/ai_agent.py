"""SDD 83 — Autopiloto AGENTE: el LLM DECIDE y EJECUTA acciones (no solo prioriza una skill).

A diferencia del cerebro de SDD 81 (que elige UNA de las 14 skills pre-programadas), acá el LLM
juega por sí mismo vía un loop de "acción-JSON" (tool-calling PORTABLE: sirve en cualquier modelo
OpenAI-compatible, sin function-calling nativo). Cada acción se despacha a los SERVICIOS EXISTENTES
del juego (mismas reglas → no hace trampa) dentro de un savepoint (si falla, no ensucia la sesión).

Seguridad/escala: gateado por `ai_agent_enabled` + `ai_brain_mode="agent"` por jugador +
`ai_brain_min_level` + PRESUPUESTO diario de LLM + botón STOP. Acotado a `ai_agent_max_steps`
acciones por tick. Ante CUALQUIER fallo devuelve lo hecho y el caller cae al autopiloto determinista
(nunca rompe el tick). v1: transport (la logística entre bases que faltaba), build, train, research.
v2 (paridad con el determinista): fortify, bunker (dig/dig_deeper/room), stash, sell, colonize,
spy, tribute, move_troops, attack — todos wrappers 1:1 sobre los servicios del juego."""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core import metrics
from app.models import Base_, Player

_SYS = (
    "You are the autonomous brain of a player's empire in a turn-based space strategy game. "
    "Each step you may execute ONE action to improve the empire; you then get the result and may "
    "continue. Respond with ONLY a JSON object (no prose, no markdown). Available actions:\n"
    '- {"action":"transport","from_planet":"<p>","to_planet":"<p>","mineral":"<m>","amount":<n>}: '
    "move minerals between YOUR planets (needs cargo ships).\n"
    '- {"action":"build","base_id":<id>,"building":"<key>","mineral":"<key|null>"}: '
    "build a building (mineral only for mine/silo).\n"
    '- {"action":"train","base_id":<id>,"unit":"<key>","quantity":<n>}: train units.\n'
    '- {"action":"research","tech":"<key>"}: research a technology.\n'
    # SDD 83 v2: paridad con el autopiloto determinista — defensa, búnker, bóveda, mercado,
    # colonización, espionaje, diplomacia, logística de tropas y ataque.
    '- {"action":"fortify"}: put a turret (building the missing lab) on every undefended base.\n'
    '- {"action":"bunker","base_id":<id>,"op":"dig|dig_deeper|room","room":"<key|null>"}: '
    "dig this base's bunker / enlarge it / build a room (auto-cell; see catalog.rooms).\n"
    '- {"action":"stash","base_id":<id>,"mineral":"<m>","amount":<n>}: hide minerals in the '
    "bunker vault (safe from looting; see bunkers[].vault_free).\n"
    '- {"action":"sell","planet":"<p>","mineral":"<m>","quantity":<n>}: sell surplus for energy '
    "(needs a market: see market_planets).\n"
    '- {"action":"colonize","planet":"<p>"}: found a colony (needs a colony_ship; '
    "see colonizable).\n"
    '- {"action":"spy","target_player_id":<id>}: launch a spy satellite at a rival.\n'
    '- {"action":"tribute","mission_id":<id>,"mineral":"<m>","amount":<n>}: offer tribute to '
    "cancel an incoming nuclear strike (see incoming_strikes).\n"
    '- {"action":"move_troops","from_base_id":<id>,"to_base_id":<id>,"units":{"<u>":<n>}}: '
    "move garrison between YOUR bases.\n"
    '- {"action":"attack","target_base_id":<id>,"units":{"<u>":<n>},"source_base_id":<id|null>}: '
    "attack an enemy base (see enemy_bases; ONLY when your power clearly beats defense_est, and "
    "keep a home reserve).\n"
    '- {"action":"done"}: nothing useful left to do this turn.\n'
    "Priorities: defend every base and grow the bunker before attacking; stash SURPLUS in the "
    "vault so raids can't loot it; move surplus to a planet that lacks it; research what unlocks "
    "needed things; spy before you attack; if a nuke is incoming, tribute can save you. EXPLOIT "
    "`active_events` (build during `build_cost`/`solar_storm`, expand during `production`/"
    "`energy_regen`, train during `free_units`, attack during `attack`). Use EXACT keys from the "
    "state. If an action fails, read the error and try another or answer done."
)


async def _agent_state(session: AsyncSession, player: Player) -> dict:
    """Resumen COMPACTO del imperio para el prompt: bases, stock por planeta, unidades, energía y
    las keys válidas del catálogo (para que el LLM no alucine edificios/unidades/techs)."""
    from app.services.economy import planet_stocks
    from app.services.research import researched_techs
    from app.services.training import player_units
    content = get_content()
    bases = list((await session.execute(
        select(Base_).where(Base_.player_id == player.id))).scalars())
    stocks: dict[str, dict] = {}
    for pk in dict.fromkeys(b.planet_key for b in bases):
        st = await planet_stocks(session, player.id, pk)
        stocks[pk] = {k: round(v) for k, v in st.items() if v}
    units = {k: v for k, v in (await player_units(session, player.id)).items() if v}
    # SDD 86: eventos del mundo activos (SDD 36) → el agente los aprovecha (construir en hora feliz,
    # atacar en fervor bélico, etc.).
    from app.services.events import active_events_out
    events = [{"effect": e["effect"], "magnitude": e["magnitude"], "name": e["name"]}
              for e in await active_events_out(session)]
    have = await researched_techs(session, player.id)
    researchable = [k for k, t in content.technologies.items()
                    if k not in have and (not t.get("requires_tech") or t["requires_tech"] in have)]
    from app.core.config import get_settings
    settings = get_settings()
    base_out = []
    for b in bases:
        d: dict = {"id": b.id, "planet": b.planet_key}
        if settings.garrison_enabled:   # guarnición por base → move_troops/attack saben desde dónde
            from app.services.training import units_at_base
            g = {k: v for k, v in (await units_at_base(session, player.id, b.id)).items() if v}
            if g:
                d["units"] = g
        base_out.append(d)
    out = {
        "energy": round(player.energy),
        "bases": base_out,
        "stocks_by_planet": stocks,
        "units": units,
        "active_events": events,   # SDD 86: eventos del mundo para aprovechar

        "catalog": {
            "buildings": list(content.buildings.keys()),
            "units": list(content.units.keys()),
            "researchable_techs": researchable[:20],
        },
    }
    # SDD 83 v2: estado para el resto de las acciones — solo las claves que APORTAN (prompt corto).
    if settings.bunkers_enabled:
        from app.services.bunkers import (
            _bunker_for_base,
            _vault_capacity,
            _vault_stocks,
            grid_bonus,
            grid_side,
        )
        bunkers = []
        for b in bases:
            bk = await _bunker_for_base(session, b.id)
            if bk is None:
                continue
            side = grid_side(bk, settings, await grid_bonus(session, bk.id, settings))
            cap = await _vault_capacity(session, bk.id)
            used = sum(s.amount for s in await _vault_stocks(session, bk.id))
            bunkers.append({"base_id": b.id, "side": side, "vault_free": round(cap - used)})
        if bunkers:
            out["bunkers"] = bunkers
        out["catalog"]["rooms"] = list(content.rooms.keys())
    from app.models import StrikeMission
    strikes = (await session.execute(
        select(StrikeMission).where(StrikeMission.defender_id == player.id,
                                    StrikeMission.status == "outbound"))).scalars().all()
    if strikes:
        out["incoming_strikes"] = [
            {"mission_id": m.id, "nuclear": "nuclear_missile" in (m.force or "")} for m in strikes]
    # enemigos (para spy Y attack): bases rivales con defensa ESTIMADA (mismo estimador que la NPC)
    from app.services.npc import _base_defense_estimate
    foes = (await session.execute(
        select(Base_, Player).join(Player, Base_.player_id == Player.id)
        .where(Base_.player_id != player.id))).all()
    enemy_bases = []
    for b, owner in foes:
        if player.alliance_id and owner.alliance_id == player.alliance_id:
            continue
        if not owner.is_npc and owner.galaxy_instance_id != player.galaxy_instance_id:
            continue
        enemy_bases.append({"id": b.id, "planet": b.planet_key, "owner": owner.username,
                            "owner_id": owner.id,
                            "defense_est": round(await _base_defense_estimate(session, b))})
        if len(enemy_bases) >= 8:
            break
    if enemy_bases:
        out["enemy_bases"] = enemy_bases
    from app.services.colonization import compat
    mine = {b.planet_key for b in bases}
    colonizable = [pk for pk in content.planets
                   if pk not in mine
                   and (not player.galaxy_key or content.planet_galaxy.get(pk) == player.galaxy_key)
                   and compat(player.race_key, pk, have).get("can_colonize")]
    if colonizable:
        out["colonizable"] = colonizable[:6]
    from app.services.market import player_market_planets
    mkts = await player_market_planets(session, player)
    if mkts:
        out["market_planets"] = mkts
    return out


async def _base_by_id(session: AsyncSession, player: Player, base_id) -> Base_:
    b = await session.get(Base_, int(base_id))
    if b is None or b.player_id != player.id:
        raise ValueError(f"base {base_id} no es tuya")
    return b


async def _dispatch(session: AsyncSession, player: Player, action: dict) -> tuple[bool, str]:
    """Ejecuta UNA acción del LLM contra los servicios del juego, en un savepoint (si falla,
    rollback del savepoint → la sesión queda limpia y el error va al LLM). Devuelve (ok, msg)."""
    name = str(action.get("action") or "").lower()
    try:
        async with session.begin_nested():
            if name == "transport":
                from app.services.market import start_transport
                await start_transport(session, player, str(action["from_planet"]),
                                      str(action["to_planet"]),
                                      {str(action["mineral"]): int(action["amount"])})
            elif name == "build":
                from app.services.build import start_build
                base = await _base_by_id(session, player, action["base_id"])
                await start_build(session, player, base, str(action["building"]),
                                  action.get("mineral") or None)
            elif name == "train":
                from app.services.training import start_training
                base = await _base_by_id(session, player, action["base_id"])
                await start_training(session, player, base, str(action["unit"]),
                                     int(action["quantity"]))
            elif name == "research":
                from app.services.research import start_research
                await start_research(session, player, str(action["tech"]))
            # SDD 83 v2: paridad con el determinista — wrappers 1:1 sobre los servicios del juego
            # (mismas reglas/validaciones; ninguna lógica nueva acá).
            elif name == "fortify":
                from app.services.build import fortify_undefended
                r = await fortify_undefended(session, player)
                if not r.get("fortified") and not r.get("soldiered"):
                    return False, f"nothing fortified: {r.get('skipped') or 'all bases defended'}"
            elif name == "bunker":
                from app.services.bunkers import build_room, dig, dig_deeper
                op = str(action.get("op") or "dig")
                bid = int(action["base_id"])
                if op == "dig":
                    await dig(session, player, bid)
                elif op == "dig_deeper":
                    await dig_deeper(session, player, bid)
                elif op == "room":
                    await build_room(session, player, bid, str(action["room"]))
                else:
                    return False, f"unknown bunker op: {op} (dig|dig_deeper|room)"
            elif name == "stash":
                from app.services.bunkers import stash
                await stash(session, player, int(action["base_id"]), str(action["mineral"]),
                            float(action["amount"]))
            elif name == "sell":
                from app.services.market import sell
                await sell(session, player, str(action["planet"]), str(action["mineral"]),
                           int(action["quantity"]))
            elif name == "colonize":
                from app.services.colonization import found_colony
                await found_colony(session, player, str(action["planet"]),
                                   mode=str(action.get("mode") or "surface"),
                                   vehicle="colony_ship")
            elif name == "spy":
                from app.services.satellites import launch
                await launch(session, player, "spy_satellite", int(action["target_player_id"]))
            elif name == "tribute":
                from app.services.strike import offer_tribute
                await offer_tribute(session, player, int(action["mission_id"]),
                                    {str(action["mineral"]): float(action["amount"])}, 0.0)
            elif name == "move_troops":
                from app.services.troops import start_move
                await start_move(session, player, int(action["from_base_id"]),
                                 int(action["to_base_id"]),
                                 {str(k): int(v) for k, v in dict(action["units"]).items()})
            elif name == "attack":
                from app.services.combat import start_attack
                src = action.get("source_base_id")
                await start_attack(session, player, int(action["target_base_id"]),
                                   {str(k): int(v) for k, v in dict(action["units"]).items()},
                                   source_base_id=int(src) if src else None)
            else:
                return False, f"unknown action: {name}"
        metrics.AI_AGENT_ACTIONS.inc(action=name, outcome="ok")
        return True, "ok"
    except KeyError as e:
        metrics.AI_AGENT_ACTIONS.inc(action=name or "?", outcome="error")
        return False, f"missing argument: {e}"
    except Exception as e:
        metrics.AI_AGENT_ACTIONS.inc(action=name or "?", outcome="error")
        return False, f"error: {e}"


async def run_agent_autopilot(session: AsyncSession, player: Player, settings) -> int:
    """Loop del agente: el LLM ve el estado y ejecuta acciones (hasta `ai_agent_max_steps`), cada
    una validada por el juego. Respeta el presupuesto diario de LLM. Devuelve nº de acciones
    APLICADAS. Best-effort: cualquier excepción → devuelve lo hecho (caller cae al determinista)."""
    from app.services.ai_life import _brain_budget_ok  # reusa el tope diario por jugador
    if not settings.ai_agent_enabled:
        return 0
    route = settings.ai_agent_route or "gpu"
    try:
        from app.services.llm import llm_chat
        state = await _agent_state(session, player)
        messages = [{"role": "system", "content": _SYS},
                    {"role": "user", "content": json.dumps(state, default=str)}]
        applied = 0
        for _ in range(max(1, int(settings.ai_agent_max_steps))):
            if not _brain_budget_ok(player, settings):   # sin cupo diario → parar (costo)
                break
            reply = await llm_chat(messages, json_mode=True, route=route, kind="agent",
                                   max_tokens=120, user=f"agent:{player.username}")
            try:
                action = json.loads(reply or "{}")
            except Exception:
                break
            if str(action.get("action") or "").lower() in ("", "done", "stop", "none"):
                break
            ok, msg = await _dispatch(session, player, action)
            if ok:
                applied += 1
                from app.services.journal import record
                await record(session, "ai_agent", player.id, action=action.get("action"))
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": msg})   # feedback para el próximo paso
        return applied
    except Exception:
        return 0
