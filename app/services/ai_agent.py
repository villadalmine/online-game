"""SDD 83 — Autopiloto AGENTE: el LLM DECIDE y EJECUTA acciones (no solo prioriza una skill).

A diferencia del cerebro de SDD 81 (que elige UNA de las 14 skills pre-programadas), acá el LLM
juega por sí mismo vía un loop de "acción-JSON" (tool-calling PORTABLE: sirve en cualquier modelo
OpenAI-compatible, sin function-calling nativo). Cada acción se despacha a los SERVICIOS EXISTENTES
del juego (mismas reglas → no hace trampa) dentro de un savepoint (si falla, no ensucia la sesión).

Seguridad/escala: gateado por `ai_agent_enabled` + `ai_brain_mode="agent"` por jugador +
`ai_brain_min_level` + PRESUPUESTO diario de LLM + botón STOP. Acotado a `ai_agent_max_steps`
acciones por tick. Ante CUALQUIER fallo devuelve lo hecho y el caller cae al autopiloto determinista
(nunca rompe el tick). Primera rebanada: transport (la logística entre bases que faltaba), build,
train, research."""
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
    '- {"action":"done"}: nothing useful left to do this turn.\n'
    "Priorities: move SURPLUS minerals to a base/planet that lacks what it needs, keep the economy "
    "growing, research what unlocks needed things. Use EXACT keys from the state. If an action "
    "fails, read the error and try a different one or answer done."
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
    have = await researched_techs(session, player.id)
    researchable = [k for k, t in content.technologies.items()
                    if k not in have and (not t.get("requires_tech") or t["requires_tech"] in have)]
    return {
        "energy": round(player.energy),
        "bases": [{"id": b.id, "planet": b.planet_key} for b in bases],
        "stocks_by_planet": stocks,
        "units": units,
        "catalog": {
            "buildings": list(content.buildings.keys()),
            "units": list(content.units.keys()),
            "researchable_techs": researchable[:20],
        },
    }


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
            reply = await llm_chat(messages, json_mode=True, route=route, kind="npc",
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
