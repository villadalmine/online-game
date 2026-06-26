# SDD 19 — Métricas Prometheus + dashboard Grafana (observabilidad)

> **Estado:** **implementado** (en producción) · **Fecha:** 2026-06-23 · **Autor:** equipo online-game
> **Relacionado:** API-first (`app/api/v1`), servicios (`app/services/*`), `worker.run_tick`,
> SSE (`app/api/v1/notifications.py`), `app/services/llm.py`, [SDD 7 capacidad](sdd-capacity-autoscaling.md),
> [SDD 12 métricas de jugador](sdd-player-metrics-public.md).

## 1. Objetivo

Exponer un endpoint **`/metrics`** (formato texto Prometheus) para scrapear con **Prometheus** y
armar un **dashboard en Grafana**: usuarios conectados en el momento, todas las tareas del juego
(construcciones, entrenamientos, investigación, expediciones, combate, altas, asistente AI), salud
de la API (RED: Rate/Errors/Duration), el tick del mundo, el LLM y la infra. Como **todo pasa por
la API**, casi todo es instrumentable en un solo lugar.

## 2. Cómo exponerlo (sin dep nueva, fiel al proyecto)

- **Opción elegida**: un módulo mínimo `app/core/metrics.py` (stdlib) con `Counter`/`Gauge`/
  `Histogram` en memoria del proceso + un endpoint `GET /metrics` que serializa el **formato de
  exposición de Prometheus**. Cero dependencias (consistente con "single installer / no new deps").
- **Alternativa**: `prometheus-client` (lib chica, pura Python) si se prefiere algo estándar —
  decisión abierta; el contrato (`/metrics`) es el mismo.
- **Middleware** FastAPI para RED automático por ruta (método, path *template*, status, latencia).
- **Multi-réplica**: cada pod expone SUS contadores; Prometheus scrapea todos y **suma**. Los
  `Gauge` (p.ej. conexiones SSE) se suman entre pods. Los `Counter` son monotónicos por proceso →
  usar `rate()` en Grafana (resetean si el pod reinicia, `rate()` lo maneja).

## 3. Qué métricas (análisis por categoría)

### 3.1 Usuarios conectados / actividad en vivo
- `game_sse_connections` **(gauge)** — conexiones SSE abiertas AHORA (`/notifications/stream`):
  el mejor proxy de "usuarios conectados en este momento". Se incrementa al abrir el stream y se
  decrementa al cerrar (`finally`).
- `game_active_players` **(gauge)** — jugadores distintos que tocaron `/players/me` en los últimos
  N min (ventana deslizante en memoria, o derivado en Prometheus con `count(...)`).
- `game_players_total` **(gauge)** — total de jugadores humanos (de la DB, refrescado cada scrape).
- `game_online_by_galaxy{galaxy}` **(gauge)** — conectados por instancia/shard (SDD 8).

### 3.2 RED de la API (salud)
- `http_requests_total{method,path,status}` **(counter)** — tasa y errores por endpoint.
- `http_request_duration_seconds{method,path}` **(histogram)** — p50/p95/p99 de latencia.
- `http_requests_in_flight` **(gauge)** — requests concurrentes. (El `/players/me` con `advance`
  es la query a vigilar — SDD 7.)

### 3.3 Tareas del juego (negocio — "todo lo que se hace")
Contadores incrementados en los servicios donde ya viven los `stats.bump` (SDD 12):
- `game_buildings_started_total{building}` / `game_buildings_completed_total{building}` (economy/state).
- `game_units_trained_total{unit}` (training).
- `game_research_completed_total{tech}` (research).
- `game_expeditions_total{result}` (expedition).
- `game_resources_mined_total{mineral}` (economy) — counter; tasa de minado.
- `game_attacks_dispatched_total` / `game_combats_resolved_total{outcome=win|loss}` /
  `game_loot_total{mineral}` (combat).
- `game_signups_total` / `game_logins_total` / `game_otp_requests_total{allowed=true|false}` (auth_otp).
- `game_onboarding_completed_total{race,planet}` (onboarding).
- `game_advisor_asks_total{source=llm|fallback}` / `game_advisor_hacks_total` (advisor, SDD 2).
- `game_seasons_closed_total` / `game_newbie_protection_active` (gauge) (seasons, SDD 11).

### 3.4 Tick del mundo (worker)
- `game_tick_duration_seconds` **(histogram)** — cuánto tarda `run_tick` (cuello O(N), SDD 7).
- `game_tick_players_advanced_total` / `game_tick_npc_turns_total` / `game_tick_missions_resolved_total`.
- `game_tick_last_run_timestamp` **(gauge)** — para alertar si el tick dejó de correr.

### 3.5 LLM / IA (no escala como la API — SDD 9)
- `game_llm_requests_total{purpose=npc|advisor,status=ok|error|timeout}` **(counter)**.
- `game_llm_latency_seconds{purpose}` **(histogram)** — latencia de la GPU/proveedor.
- `game_llm_fallbacks_total{purpose}` **(counter)** — cuántas veces cayó al determinista/reglas.

### 3.6 Infra (en parte ya disponible)
- `game_db_pool_in_use` / `game_db_pool_size` **(gauge)** — pool SQLAlchemy (techo real, SDD 7).
- `game_redis_up` **(gauge)** + hit/miss del cache de catálogo.
- Proceso: CPU/mem (de cAdvisor/kube-state-metrics, no hace falta instrumentar).

## 4. Dashboard Grafana (paneles propuestos)
1. **Conectados ahora** (`game_sse_connections`, `game_active_players`) + por galaxia.
2. **RED**: RPS por endpoint, % error (5xx), p95/p99 `/players/me`, requests in-flight.
3. **Actividad del juego**: rate de construcciones/entrenamientos/investigación/expediciones/ataques;
   altas (signups) y logins; OTP permitidos vs bloqueados (allowlist, SDD 14).
4. **Combate**: combates resueltos win/loss, botín por mineral.
5. **Tick**: duración (p95), última corrida, players avanzados/turno NPC.
6. **IA**: latencia LLM por propósito, % fallback, errores/timeouts.
7. **Infra**: pool de DB, Redis, CPU/mem por pod, réplicas (HPA, SDD 7).

Se versiona un **dashboard JSON** en `deploy/observability/grafana-dashboard.json` (importable) +
opcional provisioning por ConfigMap.

## 5. Wiring en k8s
- **Puerto/serv**: `/metrics` en el mismo app (puerto 8000). Scrapeo **in-cluster** vía el Service
  (Prometheus pega al pod/ClusterIP, NO por el gateway público).
- **ServiceMonitor** (Prometheus Operator) opt-in `metrics.serviceMonitor.enabled` en el chart,
  o anotaciones `prometheus.io/scrape` si usan scrape por anotación.
- **Grafana**: importar el JSON, datasource Prometheus.

## 6. Seguridad (importante)
- **`/metrics` NO debe ser público.** El HTTPRoute actual matchea `PathPrefix: /` → expondría
  `/metrics` por el dominio. Mitigar (elegir una):
  1. **Regla en el HTTPRoute** que devuelva 404 para `/metrics` desde el hostname público (scrapeo
     interno por Service sigue funcionando), **o**
  2. servir `/metrics` en un **puerto separado** no ruteado por el gateway, **o**
  3. token/allowlist de IP en el endpoint.
- Las métricas son **agregadas** (sin email/PII), igual que `/public/*` (SDD 12). Nada de datos por
  usuario identificable en labels (no usar email/username como label → cardinalidad + privacidad).
- Cuidar **cardinalidad de labels**: usar el *path template* (no la URL con IDs), `building`/`unit`/
  `tech` (valores acotados del catálogo), nunca IDs de jugador.

## 7. Validación / tests
- `tests/test_metrics.py`: `/metrics` devuelve 200 y contiene las series clave; un contador sube tras
  ejecutar una acción (p.ej. `game_buildings_started_total` tras un build e2e); labels acotados.
- Guard de cardinalidad: el test falla si alguna serie usa un id de jugador como label.
- e2e (`tests/test_api_e2e.py`): `/metrics` accesible y, si se aplica la mitigación (1), 404 desde el
  hostname público.

## 7.bis Estado de implementación (2026-06-23) — v1
- **`/metrics`** (Prometheus text) con módulo stdlib `app/core/metrics.py` (Counter/Gauge/Histogram,
  sin deps). Middleware RED (`http_requests_total`, `http_request_duration_seconds`,
  `http_requests_in_flight`) con **path-template** (no ids). Métricas: `game_sse_connections`
  (conectados ahora), `game_players_total`, `game_signups_total{method}`, `game_logins_total{method}`.
- **No público**: `METRICS_TOKEN` (Secret) → `/metrics` exige Bearer; vacío = abierto (dev). El
  middleware no se mide a sí mismo; sin labels con PII (test lo verifica).
- **Helm**: `templates/servicemonitor.yaml` (opt-in `metrics.serviceMonitor.enabled`), Service con
  puerto `http` nombrado + label, `METRICS_TOKEN` por Secret. Para kube-prometheus-stack, label
  `release: kube-prometheus-stack` en el SM.
- Tests: `test_metrics_endpoint_and_no_pii`, `test_metrics_token_guard`. **169 unit/e2e verdes.**
- **v1.1 (2026-06-23)**: `game_events_total{kind}` (un counter, instrumentado en `stats.bump` →
  cubre buildings_built/units_trained/research_completed/expeditions_completed/attacks_launched/
  battles_won|lost/resources_mined|looted|lost). `game_tick_duration_seconds`(histogram)+
  `game_tick_last_run_timestamp` en `run_tick`. `game_llm_requests_total{status}` +
  `game_llm_latency_seconds` en `llm_chat`. **Dashboard Grafana** (`deploy/helm/dashboards/online-game.json`)
  como ConfigMap opt-in (`metrics.grafanaDashboard.enabled`, label `grafana_dashboard`).

## 7.ter Para tus bots (openclaw/hermes) y alertas — PromQL útil
Las series viven en Prometheus (job `galaxy-api`, ns `online-game`). Ejemplos que un bot puede
consultar vía la API de Prometheus (`/api/v1/query?query=...`) para responder preguntas:
- **¿Cuántos jugadores hay?** → `game_players_total`
- **¿Cuántos conectados ahora?** → `sum(game_sse_connections)`
- **¿Se creó alguien (última hora)?** → `increase(game_signups_total[1h])` (por método: sin `sum`)
- **Logins última hora** → `increase(game_logins_total[1h])`
- **Tráfico (rps)** → `sum(rate(http_requests_total[5m]))`; **errores** →
  `sum(rate(http_requests_total{status=~"5.."}[5m]))`
- **Latencia p95** → `histogram_quantile(0.95, sum by (le)(rate(http_request_duration_seconds_bucket[5m])))`

**Alertas** (`PrometheusRule` opt-in `metrics.prometheusRule.enabled`, ya desplegado): `OnlineGameSignup`
(info, `increase(game_signups_total[10m])>0` → te avisa de altas vía Alertmanager→openclaw→Telegram),
`OnlineGameApiDown` (critical), `OnlineGameHighErrorRate` (warning). Ajustá el ruteo en tu Alertmanager.

> Nota: los counters resetean al reiniciar el pod (normal); por eso se usan `increase()`/`rate()`,
> no el valor absoluto.

## 7.quater Limitación conocida → RESUELTA (Pushgateway, 2026-06-26)
El **tick** corre en el CronJob `galaxy-tick` (proceso aparte), no scrapeable directo → antes
`game_tick_*` / `game_npc_*` quedaban vacíos en Prometheus. **Resuelto:** al terminar, `worker.tick()`
**empuja** sus métricas (`worker._push_metrics`) a una **Pushgateway** (rol `install-pushgateway` en
infra-ai, ns `monitoring`, con ServiceMonitor `honorLabels`), de donde kube-prometheus-stack las
scrapea. Se activa con `PUSHGATEWAY_URL` (env del CronJob, p.ej.
`http://pushgateway.monitoring:9091`); vacío = no empuja (dev). PUT a `/metrics/job/galaxy-tick`
reemplaza el grupo cada corrida (no acumula). Así el dashboard "NPC AI" y `game_tick_*` se llenan.

## 9. NPC AI — observar cómo juega la IA y si mejora (2026-06-26)

Objetivo del usuario: **entender cómo juega la NPC, cómo consume la API/GPU y si se vuelve más
inteligente con el tiempo.** Hay tres vistas, de menos a más detalle:

### 9.1 Métricas Prometheus (tendencia en el tiempo)
- **`game_npc_actions_total{action,brain}`** — qué hace la IA cada turno (build/train/attack/
  research/colonize/expedition/idle). `brain=rules|llm`.
- **`game_npc_decisions_total{outcome}`** — `outcome=llm` (el LLM decidió y se aplicó) vs `fallback`
  (la llamada falló → reglas). **Más `llm` y menos `fallback` = la IA razona, no adivina.**
- Se combinan con las métricas LLM existentes (`game_llm_latency_seconds`, `game_llm_requests_total`)
  y el uso por NPC (`end_user=online-game:npc:*` en LiteLLM).

### 9.1.bis Glosario (qué significa cada métrica — clave para no confundirse)
Dos ejes **independientes** en `game_npc_decisions_total`:
- **`backend`** = a qué modelo se consultó: `gpu` (GPU local) | `cloud` (modelo pago). **La GPU/nube
  se usa en AMBOS outcomes** — gastás el modelo aunque después caiga a reglas.
- **`outcome`** = qué pasó con esa jugada: `llm` = la jugada del modelo **se aplicó** (✅ la IA jugó
  de verdad) | `fallback` = el modelo respondió pero la jugada **no se pudo aplicar** (inviable / sin
  energía / JSON malo) → ese turno jugó **reglas**.

| Quiero saber… | Métrica |
|---|---|
| **"usó GPU y la jugada salió bien"** | `game_npc_decisions_total{backend="gpu",outcome="llm"}` |
| "usó nube y salió bien" | `…{backend="cloud",outcome="llm"}` |
| **¿juega bien? (acierto)** | `llm / (llm+fallback)` por backend (más alto = mejor) |
| ¿cuánto gasta cada backend? | `sum by(backend)(increase(game_npc_decisions_total[…]))` + `game_llm_latency_seconds` |
| qué hace | `game_npc_actions_total{action}` |
| ¿falló la llamada misma (red)? | `game_llm_requests_total{status="error"}` (≠ `fallback`) |

> **`fallback` NO es "no usó GPU".** Es "usó el modelo pero su jugada no servía". El único caso sin
> GPU/nube es `brain=rules` (o sin API key, que ni cuenta como decisión).

### 9.1.ter Aprendizaje: la NPC aprende de sus propias jugadas
Cuando una jugada del LLM **falla**, la NPC la **memoriza con el motivo** (`LlmBrain.act` →
`_remember("intento LLM 'build' falló: Energía insuficiente…")`). Esa memoria entra en
`recent_actions` del **próximo prompt** → el modelo **ve su error y no lo repite** (p.ej. deja de
intentar construir sin energía). Es el lazo de "leer su resultado y mejorar"; combinado con el `meta`
(SDD 41, win-rate por unidad) la NPC juega lo que estadísticamente funciona. Las métricas de §9.1
miden si ese aprendizaje **sube el ratio `llm`** con el tiempo.

### 9.2 Dashboard Grafana `Online Galaxy War — NPC AI`
`deploy/helm/dashboards/npc-ai.json` (wired en `grafana-dashboard.yaml`): decisiones LLM vs reglas,
**% de decisiones por LLM** (gauge = "confiabilidad de la IA"), **mezcla de jugadas** (timeseries +
piechart), latencia p50/p95 del LLM y llamadas ok/error. Queries clave:
`sum by(outcome)(increase(game_npc_decisions_total[1h]))`,
`sum by(action)(rate(game_npc_actions_total[15m]))`.

### 9.3 Vista en el panel de ADMIN (sin Grafana)
`GET /admin/npc-stats` (admin-gated) devuelve un **snapshot por NPC**: score, postura, **mezcla de
acciones** (del journal), **récord de combate** (wins/battles) y **últimas jugadas**. La **consola de
admin** lo muestra en una card "🤖 NPC — cómo juega la IA". Es la respuesta a "ver las métricas en
modo admin" para lo de NPC, sin depender de Grafana.

> **Ver los dashboards de Grafana DENTRO del admin (embed):** posible vía iframe a una *panel embed
> URL* de Grafana, pero requiere config de Grafana (`allow_embedding=true` + acceso anónimo de
> sololectura o auth proxy). Decisión: por ahora el admin trae el **snapshot nativo** (9.3) y un
> **link** al dashboard de Grafana; el embed iframe queda como follow-up de infra (no exponer Grafana
> con anónimo sin pensar el acceso).

### 9.4 Cuándo se usa la GPU (aclaración)
Tres call-sites únicos: (a) **NPC decide su jugada** (`npc._llm_decide`, 1× por NPC **por tick**,
CronJob cada 5 min), (b) **NPC refresca postura** (`npc.decide_strategy`, ocasional), (c) **asistente
del jugador on-demand** (`advisor`, al tocar "preguntar", con límite diario). NPC `rules` = **0 GPU**.

### 9.6 Comparar GPU local vs nube (qué juega mejor)
Seteá **`npc_cloud_username`** (p.ej. `npc_venusian`): ese NPC usa el **modelo de nube**
(`npc_cloud_model`, alias del litellm, ej. `gemma4-paid`) y el resto la **GPU local**
(`npc_llm_model`). `npc_llm_choice(player)` resuelve `(model, backend)`; las llamadas LLM del NPC
(acción y postura) usan ese modelo, y `game_npc_decisions_total` se etiqueta por **`backend`**
(gpu|cloud). Comparás:
- **Quién juega mejor:** `score` y `combat.wins/battles` por NPC en `/admin/npc-stats` (con su
  `backend`/`model`) — DB-backed, fiable aunque el tick corra en el CronJob.
- **Quién decide mejor (menos fallback):** panel "GPU vs Nube" del dashboard
  (`sum by(backend,outcome)(increase(game_npc_decisions_total[24h]))`).
- **Qué modelo usa cada uno:** `model`/`backend` en `/admin/npc-stats` y en la card de admin.

### 9.5 Follow-up (idea del usuario): turnos de NPC orquestados por Argo, de a uno
Mover el bucle de NPCs del worker in-process a un **Argo Workflow** que itere los NPCs **uno a la vez**
(serial), una llamada LLM por NPC, esperando que termine antes de la siguiente. La GPU es serial igual,
pero Argo aporta: **estados/reportes por NPC**, **reintentos**, **decoupling** del pod de API, y la
posibilidad de invertir más tokens/calidad por turno. Diseño: endpoint `POST /admin/npc/{id}/turn`
(corre el turno de UN NPC) + un `CronWorkflow` que lista NPCs (`withParam`) y los corre en pasos
secuenciales. Pendiente de SDD propio.

## 8. Follow-up
- Alertas (PrometheusRule): tick caído (`game_tick_last_run_timestamp` viejo), error-rate alto,
  pool de DB saturado, p95 `/players/me` > objetivo (liga con autoscaling, SDD 7), LLM fallback alto.
- Exemplars/trazas (OpenTelemetry) si se quiere correlacionar latencias.
