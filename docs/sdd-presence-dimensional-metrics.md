# SDD 21 — Presencia en vivo (quién está online) + métricas por usuario/galaxia

> **Estado:** **implementado** (en producción) · **Fecha:** 2026-06-24 · **Autor:** equipo online-game
> **Relacionado:** [SDD 19 métricas](sdd-observability-metrics.md), [SDD 8 galaxias](sdd-galaxy-limits.md),
> [SDD 12 stats](sdd-player-metrics-public.md), [SDD 20 usuarios](sdd-users.md).

## 1. Objetivo

Dos cosas relacionadas que pediste:
1. **Saber quién está online** ahora mismo (no solo el conteo `game_sse_connections`), por API y por
   métrica, para que un bot (hermes) o Grafana lo muestren.
2. **Métricas por dimensión**: poder filtrar en Grafana **por usuario** y **por galaxia** (labels),
   manteniendo lo agregado que ya existe (SDD 19).

## 2. Diseño

### 2.1 Presencia (quién está online)
**Fuente de verdad**: dos señales combinadas, vía Redis (compartido entre réplicas):
- **SSE abierto** (tiempo real): al abrir `/notifications/stream`, `SET online:{player_id}` con
  `EX = 2×STREAM_INTERVAL`, refrescado en cada poll → "conectado de verdad ahora".
- **Last-seen** (actividad): cada `/players/me` refresca `seen:{player_id}` `EX = ~5 min` →
  "activo recientemente" aunque no tenga SSE.
- Sin Redis (dev): degrada a per-pod en memoria (suficiente con 1 réplica).

**Exposición**:
- `GET /public/online` → `{count}` (agregado, sin PII) — para el showcase.
- `GET /admin/online` → lista de **usernames** online (solo admin, SDD 14 — username es público
  pero la *lista de presencia* es info operativa → admin). El bot pregunta acá.
- Métrica `game_online_players` (gauge) — conteo; y opt-in `game_player_online{player}` (ver 2.3).

### 2.2 Por galaxia (label de baja cardinalidad — seguro)
Agregar un label **`galaxy`** (nombre/seq de la instancia, SDD 8) a las métricas clave:
`game_sse_connections{galaxy}`, `game_online_players{galaxy}`, `game_signups_total{galaxy}`,
`game_events_total{kind,galaxy}`. Pocas galaxias ⇒ cardinalidad baja ⇒ **sin problema**. En
Grafana: variable `$galaxy` para filtrar paneles por shard.

### 2.3 Por usuario (label de ALTA cardinalidad — opt-in, con cuidado)
Filtrar por usuario en Grafana requiere un label `player`. **Tensión** (ya advertida en SDD 19):
- **Cardinalidad**: 1 serie por jugador × métrica → crece con la base. OK para un juego
  privado/chico; NO para miles.
- **Privacidad**: el `username` (no el email) queda en Prometheus (interno). Aceptable si el
  username es el identificador público (SDD 20), pero es PII operacional → mantener Prometheus
  interno (ya lo es).

**Diseño opt-in** `metrics.perPlayer.enabled` (default false): un **exporter de gauges por jugador**
calculado **al scrapear** desde la DB (acotado a N jugadores activos), p.ej.:
`game_player_score{player}`, `game_player_online{player}` (1/0), `game_player_events{player,kind}`
(de `PlayerStats`). Como se emite en `/metrics` al momento del scrape (no por evento), la
cardinalidad está acotada a "jugadores existentes", no a "eventos". Tope configurable
(`metrics.perPlayer.maxPlayers`) para no explotar.

**Alternativa sin tocar Prometheus**: Grafana con un **datasource JSON/Infinity** apuntando a
`/public/players/{username}` (SDD 12) o a `/admin/online` → tablas/series por usuario sin meter el
username como label en Prometheus. Mejor para escalar; peor para alertas/PromQL.

## 3. Cómo lo usa el bot (hermes/openclaw)
- "¿quién está online?" → hermes hace `GET /admin/online` (con su credencial de admin) **o** PromQL
  `game_online_players` / `game_player_online == 1`.
- "¿cuántos por galaxia?" → `sum by (galaxy)(game_online_players)`.
- "¿cómo va el jugador X?" → `game_player_score{player="X"}` (si perPlayer on) o `/public/players/X`.

## 4. Validación / tests
- Presencia: e2e que abre SSE → `/public/online` cuenta 1 → cierra → vuelve a 0; `/admin/online`
  lista el username (y 403 a no-admin).
- Galaxy label: métrica con `galaxy` correcto tras onboarding en una instancia.
- perPlayer: con flag off, NO aparece `game_player_*` (guard de cardinalidad del test SDD 19);
  con flag on (y pocos jugadores), aparece y respeta `maxPlayers`.
- Privacidad: ningún endpoint público ni métrica agregada expone **email**.

## 5. Riesgos / decisiones
- **Cardinalidad por usuario**: opt-in + tope + Prometheus interno. Para escala real, preferir la
  vía datasource JSON (no labels por usuario).
- **Presencia con multi-réplica**: usar Redis (no per-pod) para que el conteo sea global.
- **Privacy**: la *lista* de quién está online es admin-only; el *conteo* puede ser público.

## 5.bis Estado de implementación (2026-06-24) — v1
- **Presencia** (`app/services/presence.py`): ZSET Redis (global) con fallback en memoria; heartbeat
  en `GET /players/me`; ventana `presence_window_seconds` (90s).
- **Endpoints**: `GET /public/online` (conteo, sin PII) · `GET /admin/online` (lista de usernames,
  admin-gated).
- **Métricas**: `game_online_players` (gauge, al scrapear) + opt-in `game_player_online{player,galaxy}`
  (`metrics_per_player`, tope `metrics_per_player_max`, recalculado con `clear()` cada scrape) →
  filtrable por player/galaxy en Grafana (`sum by(galaxy)(game_player_online)`).
- **Helm**: `metrics.perPlayer.enabled` → env `METRICS_PER_PLAYER`.
- Tests: `tests/test_presence.py` (2) + e2e `test_presence_online_endpoints` (público cuenta,
  admin lista, 403 no-admin). **177 unit/e2e verdes.**
- **Pendiente**: label `galaxy` en los counters agregados (no solo en el per-player); presencia por
  SSE además del heartbeat; "última vez visto" en el perfil público; vía datasource JSON para escalar.

## 6. Follow-up
- Heatmap de actividad por hora; "última vez visto" por jugador en el perfil público (SDD 12);
  alerta "pico de online" (PrometheusRule).
