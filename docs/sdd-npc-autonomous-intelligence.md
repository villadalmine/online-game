# SDD 65 — NPC autónoma v3: leer TODO el entorno, cadena GPU→cloud→reglas y auto-evaluación

> **Estado:** **Fases 1-3 implementadas** — F1 (1.126.0): cadena GPU→cloud→reglas; F2 (1.127.0): el
> LLM lee TODO el tablero (`research_options` frontera del grafo + `intel` espías + `enemy_maps`
> satélites + `my_garrison`; enemies/opciones garrison- y tech-aware) y puede `research`/`spy`;
> F3 (1.128.0): **auto-evaluación** — ledger {postura: w/l} en `reflect_on_battle` + `bandit_posture`
> epsilon-greedy en `decide_strategy` (deja de insistir con la postura que viene perdiendo).
> **Pendiente:** F4 opcional (mini-loop agéntico), solo con datos que lo justifiquen. ·
> **Pedido:** usuario, 2026-07-01: "que la inteligencia del NPC sea más autónoma; que use las mejores
> técnicas para leer el entorno, la API, las métricas, el grafo de todo el juego, y el modelo de GPU
> y si no va, pasar a la de cloud".
> **Relacionado:** [SDD 29 inteligencia estratégica](sdd-npc-strategic-intelligence.md) (2 capas:
> táctica por tick + postura periódica), [SDD 1 grafo/RAG](sdd-dependency-graph.md), [SDD 9 LLM en
> GPU](sdd-local-gpu-llm.md), [SDD 28 métricas LLM](sdd-llm-usage-metrics.md), [SDD 51 analítica](sdd-player-analytics.md),
> [SDD 61 satélites](sdd-satellites-recon.md), [SDD 35 espionaje](sdd-espionage.md), `app/services/npc.py`.

## 1. Qué hay HOY (investigado, 2026-07-01)
El cerebro ya es de 2 capas (SDD 29) y bastante capaz; conviene saber qué existe antes de agregar:
- **Táctica (cada tick ~5 min):** `LlmBrain.act` arma `_npc_state` (personalidad por raza, recursos,
  unidades, edificios+costos con **marca de factibilidad** — evita que el modelo elija lo impagable —,
  enemigos con `defense_estimate`, ataques entrantes, misiones, lunas, memoria corta) → `_llm_decide`
  elige UNA acción JSON → `dispatch_action` la aplica. **Fallback duro a `RuleBasedBrain`** ante
  cualquier fallo, con métrica del motivo (`game_npc_fallback_reason_total`).
- **Estrategia (cada ~30 min):** `decide_strategy` lee el **scoreboard** (quién crece, amenazas) y fija
  `npc_posture` (perfil de `PROFILES` que sesga margin/prioridades). Sin LLM usa `pick_posture_rules`
  (determinista). `reflect_on_battle` ajusta la postura tras cada batalla (aprendizaje determinista).
- **Reglas (fallback y default):** `RuleBasedBrain` con prioridades + perfiles; hoy además: ataque
  esporádico arriesgado (~35% baja el margen), espía para leer el tablero, **nunca idle**.
- **Modelos:** `npc_llm_choice` elige por NPC: el designado (`npc_cloud_username`) usa el modelo de
  NUBE; el resto la **GPU local**. Si el modelo falla → **directo a reglas** (no prueba la nube).
- **Métricas:** `game_npc_actions_total{action}`, `game_npc_posture`, `game_npc_decisions_total
  {backend,outcome}`, `game_npc_fallback_reason_total` + dashboard Grafana `npc-ai`.

**Brechas identificadas** (lo que este SDD ataca):
1. La GPU que falla cae a reglas sin intentar la nube (pedido explícito). → **Fase 1**.
2. `_npc_state` no incluye la intel nueva: `enemy_maps` (satélites SDD 61), intel de espías (SDD 35),
   ni la guarnición propia por base (SDD 62) → el LLM decide con menos tablero del que existe.
3. No consume el **grafo** (SDD 1 `depgraph`/`retrieve`): el estado lista opciones planas; el grafo
   sabe *por qué* conviene algo (qué desbloquea, qué falta para un objetivo).
4. No se **auto-evalúa** con sus métricas: gana/pierde queda en `reflect_on_battle` (1 batalla), pero
   nadie mira el win-rate acumulado por postura para favorecer lo que le funciona.

## 2. Diseño (técnicas elegidas y por qué)
### Fase 1 — Cadena de modelos GPU → cloud → reglas ✅ (implementada)
- En `LlmBrain.act`, si la llamada al modelo **GPU** falla (timeout/red/JSON), **reintenta una vez con
  el modelo de nube** (`npc_cloud_model`) antes de caer a reglas. Métricas: la decisión aplicada tras
  el rescate cuenta como `backend="cloud"`; el rescate se ve en
  `game_npc_fallback_reason_total{reason="gpu_rescued_by_cloud"}`.
- Por qué así: la GPU local es gratis pero flaky (carga/OOM); la nube es confiable pero paga. La cadena
  da autonomía real (sigue jugando "con cabeza") sin gastar nube salvo cuando hace falta. Reglas queda
  como red final (un tick nunca rompe).

### Fase 2 — Estado más rico (leer TODO el entorno) ✅ (implementada 1.127.0)
- Sumar a `_npc_state`: `enemy_maps` (satélites, % descubierto + bases/unidades), intel de espías
  (`player_intel`), guarnición propia por base (`units_by_base`) y los medidores del búnker (SDD 64)
  cuando existan. Marcar todo con factibilidad como ya se hace (clave para modelos chicos).
- **Grafo (SDD 1) como herramienta de razonamiento:** incluir en el prompt el resultado de
  `depgraph.analyze(snapshot, objetivo)` para el objetivo de la postura (p.ej. "para dreadnought te
  falta: hyperspace_travel ← relativistic_drive"). El grafo ya es la fuente de verdad del asistente;
  reusar `retrieve`/`build_tree` — NO duplicar conocimiento en prosa (regla del proyecto:
  [[unified-graph-model-for-ai]]).

### Fase 3 — Auto-evaluación por métricas (bandit liviano sobre posturas) ✅ (implementada 1.128.0)
- La NPC ya registra batallas (stats wins/losses) y acciones. Agregar a `decide_strategy` un sesgo
  **epsilon-greedy**: con prob. 1−ε elegir la postura con mejor win-rate propio de los últimos N días
  (de `PlayerStats`/journal, sin infra nueva); con prob. ε explorar otra. Determinista, barato, y es
  "aprender de verdad" sin entrenar nada: usa las métricas que ya emitimos.
- Exponer el win-rate por postura en el dashboard `npc-ai` (query sobre `game_npc_posture` +
  `battles_won/lost`) para VER si aprende.

### Fase 4 (opcional, endgame) — Mini-loop agéntico acotado
- En la capa **estratégica** (no por tick): permitir al LLM 2-3 "consultas de herramienta" antes de
  fijar postura: `graph(objetivo)`, `scoreboard()`, `intel(rival)`. Formato ReAct acotado (máx 3
  pasos, timeout corto, siempre cae a `pick_posture_rules`). Solo si Fase 2-3 quedan cortas: cada
  paso extra es latencia/costo de GPU, y la evidencia actual es que el estado rico + reglas sesgadas
  rinden mejor que loops largos con modelos chicos.

## 3. Tests
- Fase 1: `test_npc.py` — si el decide con modelo GPU falla y hay `npc_cloud_model`, se reintenta con
  la nube y la jugada se aplica (`outcome=llm, backend=cloud`); si la nube también falla → reglas.
- Fase 2: `_npc_state` incluye `enemy_maps`/intel/guarnición cuando los flags están ON.
- Fase 3: con historial sesgado (posturas con distinto win-rate), `decide_strategy` elige la mejor la
  mayoría de las veces y explora a veces.

## 4. Rollout / riesgos
- Fase 1: sin flag (es un rescate, mejora pura; la nube ya está permitida para NPCs). Fases 2-3:
  aditivas, por el pipeline. Fase 4: solo con datos que lo justifiquen.
- Riesgos: costo de nube si la GPU flaquea seguido (mitigado: 1 reintento por turno + presupuesto
  LiteLLM SDD 28); prompts más grandes en Fase 2 (mitigado: truncar como hace `_npc_state` hoy).
