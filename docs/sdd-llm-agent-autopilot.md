# SDD 83 — Autopiloto AGENTE: el LLM ejecuta acciones (no solo prioriza)

## Contexto (por qué)
El usuario preguntó, con razón, si "la IA ya sabe hacer las cosas o mapeamos acciones a mano". Hasta
SDD 82 el autopiloto eran **14 skills escritas a mano** (deterministas). El "cerebro" LLM de SDD 81
solo **ELIGE cuál de esas 14 priorizar** — no inventa jugadas. Por eso "mover minerales entre bases"
la IA no lo sabía hacer: no existía la skill. El usuario eligió el camino ambicioso: que el LLM
**decida y EJECUTE** acciones él mismo (tool-calling).

## Diseño
- **Tool-calling PORTABLE (loop de acción-JSON), no function-calling nativo:** los modelos de prod
  (gemma vía LiteLLM) no siempre soportan `tools` nativo. Usamos `llm_chat(json_mode=True)` (que YA
  existe y anda en cualquier modelo OpenAI-compatible): el LLM devuelve `{"action":...}`, lo
  ejecutamos, le devolvemos el resultado y sigue. Loop de hasta `ai_agent_max_steps` pasos.
- **Las acciones pasan por los SERVICIOS del juego** (mismas reglas → no hace trampa): `transport`
  (`market.start_transport` — la LOGÍSTICA entre bases que faltaba), `build`, `train`, `research`.
  Cada `_dispatch` corre en un **savepoint** (`begin_nested`): si la acción falla, rollback del
  savepoint (la sesión queda limpia) y el error se le devuelve al LLM para que reintente/pare.
- **El estado va en el prompt** (`_agent_state`): bases, stock por planeta, unidades, energía y las
  **keys válidas** del catálogo (edificios/unidades/techs researchable) para que no alucine keys.

## Seguridad / escala (crítico — es lo que preocupaba del diseño determinista)
- **Opt-in por jugador:** solo con `ai_brain_mode="agent"` (selector 🤖 en el panel). El resto sigue
  determinista/gpu/cloud/auto.
- **Flag global** `AI_AGENT_ENABLED` (default OFF; **ON en prod** porque el opt-in por jugador +
  presupuesto lo acotan).
- **Presupuesto diario de LLM por jugador** (`_brain_budget_ok`, reusado de SDD 81 v4): agotado →
  para. **`ai_agent_max_steps`** (4) acota acciones por tick. **`ai_brain_min_level`** gatea.
- **Botón STOP** del autopiloto lo frena. **Fallback total:** cualquier excepción o 0 acciones →
  `run_ai_autopilot` sigue con el **autopiloto determinista** (nunca rompe el tick).
- Métrica `game_ai_agent_actions_total{action, outcome}` (ok|error) → en Grafana ves qué ejecuta.

## Archivos
- `app/services/ai_agent.py` (nuevo): `run_agent_autopilot`, `_dispatch`, `_agent_state`.
- `app/services/ai_life.py`: `run_ai_autopilot` prueba el agente primero si `mode=="agent"`;
  `_resolve_brain` trata `agent` como reglas (el determinista es el fallback).
- `app/api/v1/bunker.py`: `/ai-brain` acepta `agent`. `app/api/v1/catalog.py`: feature `ai_agent`.
- `app/core/{config,metrics}.py`, `web/index.html` (opción 🤖 agente + tooltip), `values-prod.yaml`.

## Tests
- `tests/test_ai_agent.py`: ejecuta un `transport` de verdad (mueve iron entre planetas), el flag lo
  gatea, un action inválido no rompe, y el fallback al determinista cuando el agente no hizo nada.

## Follow-ups
- Más acciones (fortificar, atacar, colonizar, evacuar) al set de tools, con las mismas barreras.
- Tool-calling NATIVO cuando el modelo lo soporte (más robusto que el JSON-loop).
- Que el agente vea el RESULTADO de sus jugadas (crecimiento) y aprenda qué acciones rinden.
