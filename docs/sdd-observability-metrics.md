# SDD 19 — Métricas Prometheus + dashboard Grafana (observabilidad)

> **Estado:** propuesto · **Fecha:** 2026-06-23 · **Autor:** equipo online-game
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
- **Pendiente**: más counters de negocio (build/train/research/expedition/combate) en los puntos de
  `stats.bump`; histogram del tick y del LLM; dashboard Grafana JSON; PrometheusRule (alertas).

## 8. Follow-up
- Alertas (PrometheusRule): tick caído (`game_tick_last_run_timestamp` viejo), error-rate alto,
  pool de DB saturado, p95 `/players/me` > objetivo (liga con autoscaling, SDD 7), LLM fallback alto.
- Exemplars/trazas (OpenTelemetry) si se quiere correlacionar latencias.
