# SDD 51 — Analítica por jugador + gráficos in-app ("¿cómo me fue en el tiempo?")

> **Estado:** **diseño** (no implementado) · **Fecha:** 2026-06-28
> **Relacionado:** SDD 38 (journal append-only = fuente de verdad), SDD 12 (stats de por vida),
> SDD 19/21 (métricas Prometheus + presencia), SDD 41 (meta/insights), SDD 43 (UI pictográfica),
> SDD 2 (asistente). Archivos: `app/services/journal.py`, `app/models`, `app/api/v1/`, `web/index.html`.

## 1. Objetivo
Como **todo es una API/acción**, podemos medir **todo por jugador** y devolvérselo como **gráficos
lindos en un popup** (como el modal de planeta/árbol): cómo evolucionó tu **energía**, tus
**recursos**, tus **unidades**, tus **ataques/construcciones/investigaciones** **a lo largo del
tiempo**, y qué **endpoints** usaste. Para el jugador (su historia) y para el admin (uso por usuario).

## 2. Por qué NO es solo "más métricas de Prometheus"
Prometheus es para **agregados de operación** (cardinalidad acotada; el repo prohíbe labels por
jugador, ver `app/core/metrics.py`). Series **por jugador** = alta cardinalidad → NO van como labels.
La fuente correcta ya existe: el **journal (SDD 38, `game_events`)** registra **cada acción con
`player_id` + `created_at` + `version`**. Lo que falta es: (a) muestrear el **estado** (energía/
stock/unidades/score) que NO es un evento, y (b) **endpoints de agregación por jugador** + **UI**.

## 3. Datos
### 3.1 Eventos (ya existen) — SDD 38
`game_events(player_id, type, payload, version, created_at)` ya captura build/train/research/attack/
strike/drones/expedición/mercado/espionaje… → **conteos por tipo en el tiempo** salen de acá (group
by bucket de tiempo). No hay que instrumentar nada nuevo.

### 3.2 Estado muestreado (nuevo) — `PlayerSample`
La energía, el stock, las unidades y el score son **estado**, no eventos → para graficarlos en el
tiempo hay que **muestrear**. Tabla nueva, append-only y barata:
```
PlayerSample(id, player_id, at, energy, energy_max, stock_total, units_total, score,
             stocks_json, units_json)
```
- Se inserta en `state.advance()` (o en `/players/me`) **con throttle** (≤ 1 cada
  `analytics_sample_seconds`, default 300s, por jugador) → costo despreciable, sin cron.
- **Retención + downsample** (anti-crecimiento): un paso del tick borra/baja resolución de muestras
  viejas (p.ej. 5-min últimas 48 h, 1-h últimos 30 d, 1-d histórico). Config: `analytics_retention_*`.

### 3.3 Uso de endpoints por usuario (nuevo, opcional)
El middleware HTTP ya mide agregado (`http_requests_total`). Para **por-usuario** sin reventar
Prometheus: contador en DB `EndpointHit(player_id, route, day, count)` (upsert por día) → "qué
endpoints usó cada quién". Solo si `analytics_per_endpoint` ON (admin/diagnóstico).

## 4. API (todo detrás de `/players/me`, el jugador ve LO SUYO)
- `GET /players/me/history?metric=energy|stock|units|score&from=&to=&bucket=` → serie temporal
  `[{at, value}]` desde `PlayerSample` (downsample al `bucket`).
- `GET /players/me/history/events?from=&to=&bucket=&types=` → conteos por tipo por bucket (del
  journal) → barras de "qué hiciste" (ataques, builds, research…).
- `GET /players/me/history/summary` → KPIs (totales SDD 12 + tendencias: energía media, pico de
  unidades, ataques/semana, recursos minados vs gastados).
- **Admin:** `GET /admin/players/{id}/history*` (mismas series para cualquier jugador) +
  `GET /admin/usage` (endpoints por usuario). Gateado por admin (SDD 14).
- Todo **determinista**, sin LLM. Cacheable corto.

## 5. UI — popup con gráficos (SDD 43, "lindo y sin leer")
- Botón **📈 "Tu historia"** (card Imperio, al lado de 🌳). Abre un **modal** (mismo patrón que
  planeta/árbol) con:
  - **Sparklines/áreas** de energía, recursos (apilado por mineral), unidades (apilado por dominio),
    score — render con **SVG inline** (sin librería externa; o una mínima como uPlot si se decide).
  - **Barras** de acciones por período (ataques, construcciones, investigaciones, expediciones).
  - Selector de rango (24 h / 7 d / todo) y pictográfico (íconos por serie).
- Es **autoservicio**: el jugador entiende "cómo me fue" sin Grafana. Grafana sigue para operación.

## 6. Grafana (operación) — opcional por-usuario
Para ops, las series por jugador NO van a Prometheus. Si se quiere ver en Grafana por usuario:
- opción A: **datasource SQL** (Postgres) apuntando a `PlayerSample`/`game_events` → paneles por
  jugador en Grafana leyendo la DB (sin tocar Prometheus). **Recomendado**.
- opción B: recording por top-N jugadores a Pushgateway (acotado), si hiciera falta en Prometheus.

## 7. Rendimiento / escala
- Muestreo throttvleado + downsample → tamaño acotado por jugador.
- Las queries de historia son por `player_id` + rango (índice `(player_id, at)`), baratas.
- Lazy (sin cron por usuario), coherente con el resto del juego.

## 8. Privacidad
El jugador ve **solo lo suyo**; el detalle por-usuario cruzado es **admin-only**. Nada de PII en
Prometheus. Retención configurable.

## 9. Tests / validación
- **Servicio:** el muestreo respeta el throttle; el downsample reduce filas viejas; las series salen
  ordenadas y bucketizadas; los conteos del journal cuadran con las acciones.
- **e2e** (`tests/test_api_e2e.py`): jugar unas acciones + avanzar tiempo → `GET /players/me/history`
  devuelve serie de energía creciente; `/history/events` cuenta los ataques/builds; admin ve otro
  jugador; no-admin NO ve a otros.
- **UI:** el modal abre y dibuja con datos reales; smoke de Chrome sin errores JS.

## 10. Rollout / riesgos
- Flag `analytics_enabled` (default ON; el muestreo es barato). `analytics_per_endpoint` default OFF.
- Riesgo: crecimiento de `PlayerSample` → mitigado por downsample + retención.
- Aditivo: no toca el journal existente; nuevas tablas + endpoints + un modal. API versionada.

## 11. Fases
1. `PlayerSample` + muestreo throttle + `GET /players/me/history` (energía/stock/units/score) + modal
   con sparklines. (MVP de mayor valor.)
2. `/history/events` (del journal) + barras de acciones.
3. Downsample/retención en el tick + admin (`/admin/players/{id}/history`, `/admin/usage`).
4. Grafana SQL datasource (operación) + `EndpointHit`.
