# SDD 38 — Journal de eventos: todo medible + reproducir la partida (YAML → "video")

> **Estado:** propuesto · **Fecha:** 2026-06-24
> **Relacionado:** [SDD 19 métricas Prometheus](sdd-observability-metrics.md),
> [SDD 28 uso de IA por usuario](sdd-llm-usage-metrics.md), `app/services/stats.py` (`bump`),
> `app/core/metrics.py`, `app/models` (`CombatLog`/`Notification` = registros parciales),
> motor puro (`resolve_combat`, `resolve_spy`) que habilita el **replay determinista**.

## 1. Objetivo
Que **todo lo que hacen los jugadores quede registrado** en un **log de eventos append-only**
(event sourcing), del que se pueda: (a) **medir todo en Grafana** (cada evento bumpea una métrica por
tipo), (b) **exportar la partida a YAML** ("guardo todo lo que hicieron"), y (c) **reproducirla**
determinísticamente para armar un **"video"/timeline** de la partida. Tres capas, una fuente:
- **Prometheus/Grafana** = *cuánto* (agregados, dashboards, monetización).
- **Loki** = *qué pasó* (búsqueda/auditoría del timeline; retención limitada, no autoritativo).
- **Event log (Postgres, append-only)** = **la película**: fuente de verdad ordenada y replayable.

## 2. Por qué event sourcing y no solo métricas/logs
- **Métricas** son contadores agregados → no se puede reconstruir una partida desde ellas.
- **Logs (Loki)** son lossy y con TTL → sirven para buscar, no como fuente de verdad de un replay.
- **Event log** es **append-only y ordenado** (`seq`) → con el motor **puro** del juego
  (`resolve_combat`, `resolve_spy`, economía lazy) se puede **re-aplicar** cada evento y obtener el
  estado en cualquier instante → export YAML + reproducción ("video").

## 3. Modelo
- **`GameEvent`** `(id PK = seq global, created_at, player_id nullable, type, payload JSON)`.
  `id` autoincremental = **orden total**. `type` ∈ set acotado (`build_queued`, `train_queued`,
  `research_started`, `expedition_launched`, `attack_launched`, `battle_resolved`, `spy_launched`,
  `intel_gathered`, `spy_detected`, `onboard`, …). `payload` = lo mínimo para replay/UX (claves,
  cantidades, resultado). Índices: `created_at`, `player_id`.
- No reemplaza `CombatLog`/`Notification` (vistas especializadas); el journal es el **superset
  ordenado**.

## 4. Servicio `journal.record()` (un solo punto = mide y registra)
```python
async def record(session, type_, player_id=None, **payload):
    session.add(GameEvent(type=type_, player_id=player_id, payload=json.dumps(payload)))
    metrics.JOURNAL_EVENTS.inc(kind=type_)     # Prometheus por tipo → Grafana "ve todo"
```
- Se llama en **cada acción que cambia estado** (build/train/research/expedition/attack/spy/onboard…).
- **Resuelve el gap de métricas de una**: como espionaje y combate también llaman `record()`, quedan
  **medidos automáticamente** (`game_journal_events_total{kind="spy_launched"}`, etc.) sin instrumentar
  cada servicio a mano.
- No commitea (lo hace el caller, en la misma transacción que la acción → consistencia).

## 5. API
- **`GET /api/v1/journal`** (auth) → tus eventos (paginado `since`/`limit`), para un "diario" del
  jugador y un futuro timeline visual.
- **`GET /api/v1/journal/export?format=yaml`** (admin, como `/admin/tick`) → **toda la partida** como
  YAML ordenado por `seq` → "guardo todo / reproducir". (Filtros: `galaxy`, `since`.)
- **(futuro) `POST /api/v1/journal/replay`** → dado un export, re-aplica los eventos sobre un estado
  vacío y devuelve snapshots por paso (el "video"). El motor puro lo hace determinista.

## 6. Métricas + dashboard (Grafana ve todo)
- Counter `game_journal_events_total{kind}` (uno por tipo de evento) → panel "actividad por tipo"
  (incluye espionaje y uso de la calculadora). Apila con los `game_events_total{kind}` de lifetime
  (SDD 19) — el journal cubre el **flujo de acciones**, stats el **acumulado por jugador**.
- (futuro) Loki: `journal.record()` puede además loguear el evento como línea JSON estructurada para
  búsqueda/auditoría en Grafana (mismo dato, otra capa).

## 7. Replay → "video" (visión)
- Export YAML = lista ordenada de eventos con `at`/`player`/`type`/`payload`.
- Reproductor (web/CLI): recorre los eventos, re-aplica con el motor puro y **anima** el timeline
  (mapa, flotas, batallas, intel) → un "video" de la partida. Determinista y auditable (mismos
  números que la partida real, igual que la calculadora SDD 34 vs combate real).

## 8. Tests / validación
- `record()` agrega `GameEvent` e incrementa la métrica por tipo.
- Una acción real (spy, attack, build) deja su evento en el journal (orden por `seq`).
- `GET /journal` devuelve los eventos del jugador; `export?format=yaml` parsea a YAML válido y ordenado.
- e2e: jugar una secuencia corta → exportar → el YAML contiene los eventos esperados en orden.

## 9. Riesgos / decisiones
- **Volumen:** el journal crece con la actividad → retención/compactación por temporada (archivar el
  YAML al cerrar temporada, SDD 11) y/o purgar eventos viejos manteniendo el export.
- **Privacidad:** el export completo es admin (datos de todos); `GET /journal` solo lo tuyo.
- **Consistencia:** `record()` va en la **misma transacción** que la acción (si la acción se revierte,
  el evento también) → el log nunca miente.
- **Determinismo del replay:** depende de que el motor siga puro; cualquier no-determinismo (RNG de
  NPC/taunts) debe registrarse en el payload para reproducir fiel.
- **Compatibilidad:** aditivo (modelo + un `record()` por acción + métrica); sin journal el juego es
  idéntico a hoy.
