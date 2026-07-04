# SDD 81 — Cerebro del autopiloto: determinista / GPU / nube / auto

## Idea (del usuario)
"La IA que desarrollo (el autopiloto de vida artificial) es determinista, ¿no usa GPU/nube?" — sí, era
100% reglas. El usuario quiere poder ELEGIR: determinista o GPU/cloud, **medir con métricas cuál anda
mejor**, y que **auto-switchee** si está en modo full-auto; si no, que el usuario defina cuál usar.

## Aclaración importante
- El **autopiloto** (`run_ai_autopilot`, corre en el tick para todos) era **determinista** por diseño:
  rápido, gratis, sin tope, sin latencia — por eso escala a todos los jugadores. Su "inteligencia" es
  REAL (aprende por experiencia, batallas propias, meta global; 12 skills; posturas), solo que no LLM.
- El **cerebro NPC** (rivales) sí puede usar LLM (gpu/cloud). SDD 81 le da al AUTOPILOTO la MISMA opción.

## Diseño
- **`Player.ai_brain_mode`** (migración `81577f5a3965`): `rules` | `gpu` | `cloud` | `auto`. Default
  `rules` (determinista). Endpoint `POST /bunker/ai-brain {mode}`; selector 🧠 en el panel 🤖.
- **`_resolve_brain(session, player, scope)`**: si el flag `ai_autopilot_brain_enabled` está ON, el
  modo no es `rules` y `ai_level ≥ ai_brain_min_level`, consulta el LLM (`_llm_pick_skill`, prompt chico
  con estado + habilidades) por la ruta elegida. `auto` = prueba **gpu, después cloud, después reglas**
  (usa la que responda). Registra `game_ai_autopilot_brain_total{outcome=llm|fallback, route}`.
- **`run_ai_autopilot`**: la skill que eligió el LLM corre PRIMERO (prioridad); si no (o falla) → orden
  determinista de siempre. Nunca rompe: cualquier fallo del LLM → reglas.

## Métricas (comparar "cuál anda mejor")
- `game_ai_autopilot_brain_total{outcome, route}` — cuántas decisiones tomó el LLM vs fallback, por
  ruta. Más `llm` y menos `fallback` en una ruta = ese backend anda. + las de SDD 65
  (`game_llm_route_total`, `game_llm_tokens_total`, `game_llm_last_ok_timestamp{route}`).
- El tooltip del selector apunta a esa métrica en Grafana para elegir gpu vs nube.

## Flags / balance
`AI_AUTOPILOT_BRAIN_ENABLED=true` en prod (default por-jugador sigue siendo `rules` → nadie gasta LLM
hasta que lo elija). `ai_brain_min_level=3` (recién la IA "desarrollada" razona con el LLM).

## Tests
`tests/test_ai_life.py::test_ai_brain_llm_mode_picks_skill` (LLM stubbeado: modo gpu elige skill; rules
y flag off → determinista).

## v2 (HECHO) — `auto` que se auto-optimiza + readout in-game
Pedido del usuario: *"quiero leer cómo va la ai si elijo gpu/cloud/determinista para saber qué anda
mejor, y para que ella sepa qué va mejor si usa auto"*.
- **`auto` es un BANDIT por jugador:** ya no prueba gpu→cloud en orden fijo. Ordena las rutas por su
  **tasa de aplicadas** (`llm/(llm+fallback)`, suavizada Laplace) y prueba primero la mejor; con
  probabilidad `ai_brain_explore` (0.15) explora la otra para seguir midiendo. Ante todo fallo → reglas.
- **Rendimiento per-jugador:** `Player.ai_brain_stats` (Text JSON `{route:{llm,fallback}}`, migración
  `d7ff71187c52`) se actualiza en CADA decisión del cerebro (también en modo gpu/cloud manual), además
  de la métrica global. `brain_stats_report(player)` lo resume (aplicadas/fallback/tasa/muestras).
- **Readout in-game:** el snapshot `ai.brain_stats` alimenta el panel 🤖 → línea `📊 rinde: 🖥️ GPU 82%
  (41/50) · ☁️ nube 61% (11/18)` y, en modo `auto`, `— auto prefiere 🖥️`. Se lee sin Grafana.
- Tests: `test_brain_auto_prefers_better_route` (bandit prueba primero la mejor ruta + registra) y
  `test_brain_rules_mode_never_calls_llm`; e2e verifica `brain_stats` en el snapshot.

## v2.1 (HECHO) — la tasa pesa CALIDAD + decaimiento + research desbloquea skills
Los tres follow-ups menores que quedaban:
- **La tasa mide CALIDAD, no solo "respondió":** `_resolve_brain` devuelve `(skill, ruta)` y el registro
  se hace DESPUÉS, en `run_ai_autopilot`, según si la skill priorizada **produjo algo** (`total`
  subió) → `llm`, o no hizo nada → `fallback`. Así el bandit prefiere la ruta cuyas decisiones
  realmente mueven la aguja, no la que solo devuelve una key válida. (Las rutas que ni eligen se marcan
  `fallback` al toque.)
- **Decaimiento (media móvil):** `_record_brain` multiplica los conteos por `ai_brain_decay` (0.97)
  antes de sumar → la ventana efectiva es ~1/(1−0.97)≈33 muestras; la IA se adapta a lo reciente en vez
  de arrastrar todo el historial. Los conteos quedan fraccionarios (se redondean en el readout).
- **`research` desbloquea skills bloqueados (SDD 81 v3):** `_auto_research(scope)` mira si un skill del
  scope está gateado por una tech faltante (`_SKILL_GATE_TECH`: bunker→bunker_engineering,
  defend→weapons, spy→satellite_tech) y, con `_first_researchable_toward`, prioriza el próximo paso
  **researchable** de esa cadena de prereqs por sobre la simple "más barata". Así la IA se destraba sola.
- Tests: `test_brain_quality_weighs_impact`, `test_brain_records_fallback_when_route_fails`,
  `test_auto_research_prioritizes_blocked_skill_tech`.

## v4 (HECHO) — impacto + presupuesto diario + más gates
- **La calidad PESA el impacto (no solo "hizo algo"):** el crédito de un acierto = las acciones que
  produjo la skill priorizada (`total-before`, con tope 3) → `_record_brain(..., weight=)`. Un fallo suma
  1. Así `auto` prefiere la ruta cuyas decisiones RINDEN más, no solo la que devuelve una key válida.
- **Presupuesto diario del cerebro LLM por jugador (control de costo):** `ai_brain_llm_calls_per_day`
  (200) tope por día/jugador, contado en `ai_brain_stats` bajo `_day`/`_calls` (sin migración; reset
  diario). Agotado → cae a reglas ese turno. `_brain_budget_ok`. 0 = sin tope.
- **Más gates skill→tech:** `colonize`/`expedition` → `antigravity` (la tech de la nave colonizadora /
  transbordador). Sumados a bunker/defend/spy.
- Tests: `test_brain_quality_weighs_impact`, `test_brain_daily_budget_caps_llm` + gate de colonize.

## Follow-ups
- Que la calidad además pese el RESULTADO de juego (win-rate/crecimiento), no solo "cuántas acciones".
- Más gates skill→tech en `_SKILL_GATE_TECH` a medida que se agreguen habilidades con prerequisito.
