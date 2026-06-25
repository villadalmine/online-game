# SDD 12 — Métricas del jugador, historial de temporadas y showcase público

> **Estado:** **implementado** (en producción) · **Fecha:** 2026-06-22 · **Autor:** equipo online-game
> **Depende de:** [SDD 11 — Inicio/final (temporadas + Hall of Fame)](sdd-game-lifecycle.md).
> **Relacionado:** `app/services/scoring.py`, procesadores diferidos (combat/training/build/
> expedition/economy), `app/api/v1/players.py` (ranking), [SDD 7 — Capacidad](sdd-capacity-autoscaling.md).

## 1. Objetivo

Que cada jugador tenga un **historial de todas las temporadas/torneos jugados** y **métricas de
todo** (cuánto construyó, entrenó, exploró, ganó/perdió, minó/gastó/saqueó…), con **puntos de
ranking**, y **mostrar todo eso públicamente en la página de login** (showcase + leaderboard +
Hall of Fame, sin necesidad de estar logueado).

## 2. Estado actual

- `scoring.player_score` calcula un score **a partir del estado actual** (edificios, poder,
  minerales, techs, victorias) → sirve para el ranking pero **no es histórico**.
- `CombatLog` registra batallas (se podría derivar won/lost), pero **no** hay contadores de por
  vida de entrenamientos, construcciones, expediciones, recursos minados/gastados/saqueados.
- El ranking (`GET /players/ranking`) **requiere auth**; no hay nada **público** (pre-login).

## 3. Diseño

### 3.1 Métricas de por vida: `PlayerStats`
Tabla de contadores 1:1 con `Player`, incrementada **en los procesadores que ya emiten eventos**
(donde hoy se llama `notify`), para no recalcular:
- combate: `battles_won`, `battles_lost`, `attacks_launched`, `defenses_won`,
  `resources_looted`, `resources_lost`;
- producción/colas: `buildings_built`, `units_trained`, `research_completed`,
  `expeditions_completed`, `resources_mined`, `resources_spent`;
- actividad: `created_at`, `last_active_at`.
Aditivo y barato (un `UPDATE ... += n` por evento). Para cuentas existentes: arrancan en 0
(o backfill puntual desde `CombatLog`/estado en una migración de datos opcional).

### 3.2 Historial de temporadas
Viene de **SDD 11**: `HallOfFame` (rank + puntos por temporada, persiste) + `SeasonScore`. De ahí
se derivan, y se cachean en `PlayerStats`: `seasons_played`, `best_rank`, `hof_count`,
`total_season_points`. El "historial de torneos jugados" = lista de las temporadas del jugador con
su puesto/puntos en cada una.

### 3.3 Puntos de ranking
- **Por temporada**: `SeasonScore` (SDD 11).
- **All-time / cuenta**: un `career_points` derivable (p.ej. suma ponderada de HoF: 1º=N pts, etc.)
  → un ranking histórico estable que no depende del estado actual.

## 4. API pública (sin auth) — alimenta el login

```
GET /api/v1/public/stats                 -> métricas globales del universo (jugadores totales,
                                            imperios, temporada actual + countdown, batallas totales,
                                            minerales minados del mundo, etc.)
GET /api/v1/public/leaderboard           -> top por puntos de temporada actual y/o career_points
GET /api/v1/public/hall-of-fame          -> ganadores por temporada (HoF)
GET /api/v1/public/players/{username}    -> perfil público: stats de por vida + historial de
                                            temporadas + insignias. 404 si no existe.
```
- **Solo agregados + `username`**; **nunca** datos sensibles (email fuera). 
- **Cacheables en Redis** (TTL corto) — son lecturas calientes públicas (ver SDD 7); degradable.
- Router nuevo `app/api/v1/public.py` montado en `/public` (sin `get_current_player`).

## 5. Cliente web (login público)
- En la **página de login** (`#auth`, pre-login), agregar un **showcase público**:
  - **Stats del universo** (jugadores, temporada actual + countdown, batallas, etc.).
  - **Leaderboard** (top de la temporada + Hall of Fame).
  - Link a **perfiles públicos** (`/public/players/{username}`) con stats + historial.
- Pura presentación (consume los `/public/*`); sin lógica de juego en el front (API-first). i18n
  con el toggle existente (SDD 4).

## 6. Plan de tests (regla del proyecto)
**Servicio**: cada contador sube en su evento (ganar batalla → `battles_won+1`; entrenar →
`units_trained+=n`; minar → `resources_mined`; etc.); el perfil arma el historial desde HoF.
**E2E HTTP** (`tests/test_api_e2e.py`): `GET /public/stats|leaderboard|hall-of-fame` 200 **sin
auth**; `GET /public/players/{username}` 200 con stats y **sin email** en el payload; usuario
inexistente → 404.
**Browser**: la página de login muestra el leaderboard/stats públicos antes de entrar.

## 6.bis Estado de implementación (2026-06-22) — v1 hecho
- **Modelo** `PlayerStats` (contadores de por vida) + migración aditiva.
- **`app/services/stats.py`**: `bump` (incrementa contadores), `leaderboard`, `global_stats`,
  `season_history` (de `HallOfFame`, SDD 11), `player_profile`. Contadores cableados en los
  procesadores existentes: combate (battles_won/lost, attacks_launched, resources_looted/lost),
  build (buildings_built), train (units_trained), research (research_completed), expedición
  (expeditions_completed), minería (resources_mined).
- **Endpoints públicos SIN auth** `app/api/v1/public.py`: `GET /public/stats`, `/public/leaderboard`,
  `/public/hall-of-fame`, `/public/players/{username}` — solo agregados + username, **sin email**.
- **Web**: showcase en la página de **login** (stats del universo + top-10), pre-auth.
- **Tests**: `tests/test_stats.py` (5 servicio) + 1 e2e (público, sin auth, sin email, 404) +
  1 browser. 149 unit/e2e + 15 browser ✅.

**Follow-ups**: cachear los `/public/*` en Redis (SDD 7); `career_points` all-time; backfill de
contadores para cuentas previas (hoy arrancan en 0); ranking por instancia (SDD 8).

## 7. Riesgos / decisiones
- **Exactitud de contadores**: incrementar en **un solo lugar** por evento (el procesador
  diferido) para no doblar; los reintentos/ticks deben ser idempotentes respecto del contador.
- **Privacy**: perfiles públicos exponen solo agregados + username (sin email ni datos de cuenta).
- **Carga**: endpoints públicos = caché Redis + posibles read-replicas (SDD 7); nunca dependen de
  Redis para funcionar.
- **Orden de implementación**: requiere **SDD 11** (temporadas/HoF) primero; los contadores de por
  vida se pueden empezar antes (no dependen de temporadas).
