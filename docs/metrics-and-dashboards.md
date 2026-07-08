# Métricas y dashboards — referencia completa

Qué mide el juego, de dónde sale cada métrica y en qué dashboard de Grafana se ve. Fuente de verdad
del código: `app/core/metrics.py` (métricas propias) + LiteLLM/HAMI (proxy LLM + GPU).

## Cómo llegan las métricas a Prometheus (topología — leer primero)
- **API (`galaxy-api`, 3 réplicas):** todo lo que pasa en un request (HTTP, signups, el **asistente**
  del chat, eventos por acción del jugador) se scrapea **directo** del `/metrics` de la app.
- **Tick del mundo (`galaxy-tick`, CronJob `*/5`):** las NPC, el **autopilot**, el **agente** y la
  diplomacia corren acá. El CronJob es efímero y NO es scrapeable → **empuja** sus métricas a la
  **Pushgateway** y las **acumula en Redis** para que los contadores sean monótonos (ver
  `worker._cumulative_counter_render`, SDD 19 §7.quinquies, y [[metrics-tick-pushgateway]]).
- **LiteLLM / HAMI (ns `ai`):** el proxy LLM y la GPU exponen sus propias métricas (`litellm_*`,
  `hami_*`), scrapeadas aparte. Son la fuente de **tokens reales y costo USD**.

## Los 4 tipos de IA — cómo distinguirlos (era la duda principal)
Toda llamada al LLM lleva DOS etiquetas que separan quién la hizo:
- **`kind`** (en NUESTRAS métricas `game_llm_*`): `advisor` · `autopilot` · `agent` · `npc` · `other`.
- **`end_user`** (en LiteLLM): `online-game:<tipo>:<nombre>`, con `<tipo>` = `player` (asistente),
  `autopilot`, `agent`, `npc`. Esto da el grado **por-jugador** (p.ej. `autopilot:villadalmine`).

| IA | Qué es | `kind` | `end_user` | Dónde corre | Métricas propias |
|----|--------|--------|-----------|-------------|------------------|
| **Asistente** | El CHAT: el jugador le habla | `advisor` | `player:<user>` | API | `game_llm_calls_total{kind="advisor"}` |
| **Autopilot** (SDD 81) | Elige QUÉ skill priorizar | `autopilot` | `autopilot:<user>` | tick | `game_ai_autopilot_brain_total`, `game_ai_autopilot_total` |
| **Agente** (SDD 83) | EJECUTA acciones (mover minerales, construir…) | `agent` | `agent:<user>` | tick | `game_ai_agent_actions_total` |
| **NPC** | Los bots del mundo | `npc` | `npc:<name>` | tick | `game_npc_*` |

> Antes el autopilot y el agente iban con `kind="npc"` → se confundían con los bots. Corregido
> (2026-07-07): ahora cada uno tiene su `kind`, así los paneles los separan bien.

## Métricas propias del juego (`app/core/metrics.py`)

### HTTP / infra (scrapeadas de galaxy-api)
- `http_requests_total{method,path,status}` — requests. `http_request_duration_seconds{method,path}`
  — latencia (histograma). `http_requests_in_flight` — en curso.
- `game_sse_connections` — conexiones SSE abiertas (conectados ahora).
- `game_tick_duration_seconds` / `game_tick_last_run_timestamp` — salud del tick (heartbeat:
  `time() - game_tick_last_run_timestamp` = seg desde el último tick OK).

### Jugadores / negocio
- `game_players_total` — humanos totales. `game_online_players` — online (heartbeat de /players/me).
- `game_player_online{player,galaxy}` — **opt-in** (`METRICS_PER_PLAYER`, alta cardinalidad): 1 por
  jugador online, filtrable por jugador/galaxia.
- `game_signups_total{method}` (password|otp) · `game_logins_total{method}`.
- `game_events_total{kind}` — eventos de juego (buildings_built, units_trained, research_completed,
  battles_won/lost, resources_mined/looted…). `game_journal_events_total{kind}` — TODA acción que
  toca estado (incluye espionaje/combate/calculadora) vía `journal.record()`.
- `game_building_upgrades_total{building,kind}` (SDD 82) — mejoras de nivel de edificios
  (kind=defense|antimissile|production), incluye las mejoras EN LOTE. **Regla:** NO hay tope de
  nivel; el límite es económico → cada mejora cuesta `base × building_upgrade_cost_mult(1.5) ×
  nivel_actual` (sube de nivel se pone caro). Efecto por nivel (lineal, sin tope): producción +25%,
  defensa +25 y +40 HP, antimisil +8. Panel en **online-game.json**.

### LLM (las 4 IAs) — NUESTRA vista (scraped API + pushed tick)
- `game_llm_requests_total{status}` (ok|error) · `game_llm_latency_seconds` (histograma).
- `game_llm_calls_total{kind,status}` — llamadas por tipo de IA (advisor|autopilot|agent|npc|other).
- `game_llm_route_total{kind,route,status}` — por backend: `route`=gpu|cloud|byok. `gpu` con `ok>0`
  = tu GPU local respondió.
- `game_llm_tokens_total{kind,route,type}` — tokens del campo `usage` (type=prompt|completion). Si
  sube en `route=gpu`, la GPU genera de verdad (no cae a reglas/nube).
- `game_llm_last_ok_timestamp{route}` — heartbeat por ruta (última respuesta OK).

### NPC (¿juega bien la IA de los bots?)
- `game_npc_actions_total{action,brain}` — qué hace (build/train/attack…); brain=rules|llm.
- `game_npc_decisions_total{outcome,backend}` — outcome=llm (el LLM decidió) | fallback (cayó a
  reglas), por backend gpu/cloud. **Más `llm`, menos `fallback` = la IA razona, no adivina.**
- `game_npc_fallback_reason_total{reason}` — por qué no se aplicó (energy|infeasible|parse). Que baje
  `energy` con el tiempo = la NPC aprende a no proponer lo que no puede pagar.
- `game_npc_posture{posture}` — gauge: cuántas NPC juegan con cada postura AHORA (recount por tick).
- `game_npc_attack_targets_total{target}` — a quién pega (human|npc).

### IA del JUGADOR (autopilot / agente / diplomacia)
- `game_ai_autopilot_total{action}` — qué hicieron los robots (staff_workers|build_mine|sell_surplus|
  housing|bunker|colonize|defend|research|repopulate|spy|expedition|attack|diplomacy).
- `game_ai_autopilot_brain_total{outcome,route}` (SDD 81) — cerebro: outcome=llm (eligió una skill
  válida) | fallback (no supo); route=gpu|cloud. **`llm/(llm+fallback)` = "¿me anda este cerebro?".**
- `game_ai_agent_actions_total{action,outcome}` (SDD 83) — el agente EJECUTA: action=transport|build|
  train|research; outcome=ok|error. **`ok` subiendo = la IA juega sola de verdad.**
- `game_diplomacy_actions_total{action,actor}` (SDD 67/80) — tributos/recalls; actor=human|npc.

## Métricas externas que usan los dashboards
- **LiteLLM** (tokens/costo reales, label `end_user`, `model`): `litellm_output_tokens_metric_total`,
  `litellm_total_tokens_metric_total`, `litellm_spend_metric_total` (**USD**),
  `litellm_proxy_total_requests_metric_total`, `litellm_in_flight_requests`,
  `litellm_deployment_successful_fallbacks_total`. Modelos en prod: `qwen2.5:7b` = **GPU local (gratis)**,
  `google/gemma-4-31b-it` = **nube (paga)**.
- **HAMI** (GPU compartida): `hami_vgpu_memory_allocated_bytes{exported_pod=~"ollama.*"}`, cores/VRAM.

## Dashboards (`deploy/helm/dashboards/`)
- **online-game.json** — salud general: RPS, latencia, tick heartbeat, online, signups, eventos.
- **llm-usage.json** — "LLM usage & GPU": requests/tokens/**spend USD**, GPU viva, y el desglose
  **por TIPO de IA** (asistente/autopilot/agente/NPC) y **por jugador** (tabla por `end_user`).
- **npc-ai.json** — "¿juega bien la IA?": decisiones llm vs fallback, motivos de fallback, posturas.
- **ai-autopilot.json** — "Vida artificial (IA del jugador)": jugadas del autopilot, cerebro
  (aplicadas vs reglas), **agente** (acciones ejecutadas ok/error), diplomacia.

## Preguntas frecuentes
- **"El Spend dice 0 / casi 0."** Normalmente es correcto: la IA del jugador corre en la **GPU local
  (qwen, $0)**; solo el fallback a la **nube (gemma)** paga centavos, casi siempre por las NPC. El
  total histórico (stat "Spend USD total") crece lentísimo a propósito. 0 ≈ "gastás casi nada", no
  "roto". **Excepción:** si la GPU está apagada por mantenimiento (`llm.model=gemma4-paid`, ver
  CHANGELOG Ops), TODO va a la nube y el spend SÍ crece hasta re-prender la GPU.
- **"¿Cómo sé si la IA MEJORA?"** NPC: `game_npc_decisions_total{outcome="llm"}` sube y `fallback`
  baja (+ `game_npc_fallback_reason_total{reason="energy"}` baja). Autopilot: el ratio
  `game_ai_autopilot_brain_total{outcome="llm"}/total` sube. Agente: `game_ai_agent_actions_total
  {outcome="ok"}` sube y `error` baja. En el juego, el jugador ve su cerebro en el panel 🤖 (📊 rinde)
  y sus robots en "📈 Tu historia".
- **"¿Qué IA usa cada jugador?"** Tabla "Consultas por TIPO de IA y JUGADOR (24h)" en llm-usage:
  cada fila es `end_user` = `tipo:jugador` (p.ej. `autopilot:villadalmine` vs `player:villadalmine`).
