# SDD 7 — Capacidad (usuarios concurrentes) y autoscaling en k8s

> **Estado:** **implementado** (en producción) · **Fecha:** 2026-06-22 · **Autor:** equipo online-game
> **Relacionado:** [SDD 8 — Límites de galaxia](sdd-galaxy-limits.md) (sharding del mundo y del
> tick), [SDD 9 — LLM local en GPU](sdd-local-gpu-llm.md) (la IA no escala como la API).

## 1. Objetivo

Estimar **cuántos usuarios concurrentes** soporta el juego y **cómo autoescalar en k8s** (HPA +
recursos) para llegar ahí sin que colapse. Dar una **metodología de cálculo** (no un número
mágico) y los cambios concretos al chart.

## 2. Hallazgos del repo (qué escala bien y qué no)

**A favor (escala horizontal):**
- **API stateless** detrás de un Service (`deploy/helm/templates/api.yaml`, `replicas: 2`) →
  se replica sin estado de sesión.
- **Estado lazy por timestamp** (`services/state.py:advance`): energía/producción/colas se
  calculan al leer `/players/me`; **no hay cron por usuario**, así que los inactivos no cuestan.
- **Turn-based**: sin requisito de baja latencia; el cliente refresca `/players/me` cada ~4 s y
  el SSE hace poll cada ~2 s. Mucho margen vs. tiempo real.

**Cuellos de botella (medir/atacar):**
1. **`worker.run_tick` es O(N)**: recorre **todos** los players con `race_key` cada tick
   (CronJob `*/5`), llamando `finalize_due_*` + `collect_mines` por cada uno. A 50k jugadores eso
   es un barrido grande cada 5 min → el tick es el primer límite. (El `advance` lazy ya cubre el
   progreso al leer; el tick masivo es sobre todo para NPCs, llegadas de flotas y avanzar a
   offline.) **Mitigación:** tické **solo lo necesario** (NPCs + misiones con `arrives_at<=now` +
   jugadores activos recientemente) y **shardeá por galaxia** (ver SDD 8) para paralelizar.
2. **SSE**: `GET /notifications/stream` mantiene conexión viva y **abre una sesión DB por poll**
   (cada `interval`, default 2 s). Con muchos usuarios = muchas conexiones largas + carga DB
   constante. **Mitigación:** subir `interval`, mover notif a Redis pub/sub, y/o limitar SSE.
3. **Pool de DB**: `create_async_engine(database_url)` usa el pool por defecto (5 + 10 overflow)
   **por réplica**. Postgres es el único escritor → es el techo real. **Mitigación:** tunear pool,
   **PgBouncer**, réplicas de lectura para `/catalog`/ranking, y Redis para lecturas calientes
   (ya: catálogo cacheado).

## 3. Modelo de cálculo (cómo estimar el número)

Definimos **"usuario activo concurrente" (CCU)** por su presupuesto de requests:
- SSE poll: 1 req / `STREAM_INTERVAL` (2 s) = **0.5 rps**.
- Refresh `/players/me`: 1 req / 4 s = **0.25 rps** (incluye `advance`, la lectura más cara).
- Acciones (build/train/attack/advisor): ráfagas, ~**0.05 rps** promedio.
- ⇒ **~0.8 rps/CCU** (dominado por SSE+me). Bajar SSE a 5 s ⇒ ~0.45 rps/CCU.

`CCU_max ≈ (rps_por_pod × n_pods) / rps_por_CCU`, donde `rps_por_pod` sale de **load test**
(no se inventa). Plantilla de cálculo:

| Variable | Cómo obtenerlo |
|---|---|
| `rps_por_pod` | k6/locust contra 1 pod con requests/limits fijos, hasta p95 objetivo (p.ej. <200 ms) |
| `rps_por_CCU` | de la fórmula de arriba según `STREAM_INTERVAL`/refresh |
| `db_conns` | `pool_size × n_pods ≤ max_connections` de Postgres (con margen) → suele ser el techo |

**Ejemplo ilustrativo** (calibrar con datos reales): si un pod (500m CPU) sostiene 300 rps a p95
ok y `rps_por_CCU=0.8`, 1 pod ≈ **375 CCU**; 8 pods ≈ **3000 CCU**, *si* Postgres aguanta las
conexiones (de ahí PgBouncer). El `/players/me` (advance + writes) es la query a perfilar primero.

## 4. Autoscaling en k8s (cambios al chart)

1. **Resource requests/limits** en la API (hoy no hay) → sin requests, el HPA no puede escalar
   por CPU. Ej: `requests: cpu 200m / mem 256Mi`, `limits: cpu 1 / mem 512Mi` (tunear).
2. **HPA** nuevo (`templates/hpa.yaml`, opt-in por `autoscaling.enabled`):
   `minReplicas`/`maxReplicas`, target **CPU 70%** y/o métrica custom **rps por pod** (KEDA/
   Prometheus-adapter). La readinessProbe ya existe → rolling seguro.
3. **PodDisruptionBudget** + `topologySpreadConstraints` para no tirar todas las réplicas juntas.
4. **Tick desacoplado del tamaño**: el CronJob hoy hace O(N). A escala, convertirlo en
   **worker shardeado por galaxia** (ver SDD 8) o por rango de IDs, corriendo en paralelo; o un
   Deployment worker con cola (Redis) en vez de un solo CronJob. Mantener `AUTO_TICK_SECONDS=0`
   en multi-réplica (ya documentado) para no duplicar ticks.
5. **Postgres**: PgBouncer (transaction pooling), subir `max_connections` con criterio, réplicas
   de lectura para catálogo/ranking. Redis ya descarga catálogo + rate-limit.
6. **SSE**: exponer `STREAM_INTERVAL` configurable; considerar `notify` por Redis pub/sub para no
   pollear la DB por conexión; o degradar a poll de `/notifications` si hay demasiadas conexiones.

## 5. Verificación
- **Load test** reproducible (k6/locust) en `tests/load/` (no en CI por costo): escenarios de N
  CCU con el mix SSE+me+acciones; reportar p50/p95/p99 y rps por pod, y la curva al subir réplicas.
- Dashboards: rps, p95, CPU/mem por pod, conexiones Postgres, hit-rate Redis, duración del tick.
- Criterio de aceptación: a `maxReplicas`, p95 `/players/me` < objetivo y conexiones DB < límite.

## 5.bis Estado de implementación (2026-06-23) — v1
- **App (testeable):** pool de DB tuneable (`app/core/db.py:engine_kwargs` → `pool_size`/
  `max_overflow`/`pool_timeout`/`pool_recycle`/`pool_pre_ping` en Postgres; SQLite intacto) e
  **intervalo del SSE configurable** (`STREAM_INTERVAL`, default del stream en
  `app/api/v1/notifications.py`). Config en `app/core/config.py`.
- **Helm:** `api.resources`/`worker.resources` (requests/limits), **HPA** opt-in
  (`templates/hpa.yaml`, `autoscaling.enabled`, CPU 70%, ignora `api.replicas`),
  **PodDisruptionBudget** opt-in (`templates/pdb.yaml`), `topologySpreadConstraints`, y los envs
  `STREAM_INTERVAL`/`DB_POOL_SIZE`/`DB_MAX_OVERFLOW` en `commonEnv`. Verificado con `helm
  lint`/`template`.
- **Load test:** `tests/load/k6_ccu.js` + `tests/load/README.md` (modelo de CCU ~0.8 rps;
  criterio de aceptación p95 `/players/me` < objetivo). No corre en CI.
- Tests: `tests/test_scaling.py` (engine_kwargs sqlite/postgres + defaults/overrides).
- **Pendiente (follow-up):** métrica custom **rps/pod** (KEDA/Prometheus-adapter) para el HPA;
  **PgBouncer** + réplicas de lectura; **tick shardeado por galaxia** (SDD 8); SSE por Redis
  pub/sub; correr el load test real y calibrar `rps_por_pod`/`CCU_max`.

## 6. Riesgos / decisiones
- **Postgres es el límite duro** (un escritor). El sharding por galaxia (SDD 8) es lo que permite
  crecer de verdad; el HPA de la API sin DB escalable solo mueve el cuello.
- **La IA no escala como la API** (GPU serial) → tratarla aparte (SDD 9), siempre con fallback.
- No optimizar a ciegas: primero **instrumentar y load-testear**; los números acá son plantilla.
