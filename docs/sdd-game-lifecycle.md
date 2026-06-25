# SDD 11 — Inicio y final del juego: mundo persistente + temporadas (híbrido)

> **Estado:** **implementado** (en producción) · **Fecha:** 2026-06-22 · **Autor:** equipo online-game
> **Relacionado:** [SDD 8 — Límites de galaxia](sdd-galaxy-limits.md), `app/services/scoring.py`,
> `app/services/combat.py`, `app/worker.py`. **Monetización: fuera de alcance** (decisión: por ahora no).

## 1. Objetivo

Definir **cómo empieza y cómo "termina"** el juego. Decisión del usuario: **híbrido** —
**mundo persistente** (tu imperio no se borra) + **temporadas** periódicas que dan clímax,
ranking y premios **cosméticos / Hall of Fame** que quedan en tu cuenta, **sin wipe** del progreso
base. Referencia investigada: StarKingdoms usa rondas con reset total + newbie protection + ranking
por networth + Hall of Fame persistente; tomamos la idea de **temporada + HoF + protección de
novatos**, pero **sin** el reset destructivo (esa es nuestra diferencia).

## 2. Conceptos

### 2.1 Mundo persistente (base)
El imperio, bases, recursos, tecnologías y alianzas **persisten siempre** (como hoy). No hay un
"fin del juego" duro. El ranking global por `scoring.player_score` sigue existiendo de fondo.

### 2.2 Temporada (la capa de "inicio/fin" recurrente)
Una **`Season`** es una ventana de tiempo recurrente (configurable, p.ej. 4 semanas) con
`starts_at`/`ends_at` y `status` (`active`/`closed`). Durante la temporada los jugadores acumulan
**puntos de temporada** por logros del período (no por tamaño histórico), así un jugador nuevo o
una remontada compiten de igual a igual.
- **Cierre**: al llegar `ends_at`, se hace una **foto del ranking** → los top N entran al
  **Hall of Fame** (rank + puntos + fecha) y reciben **insignias cosméticas** que quedan para
  siempre en la cuenta. Luego **se resetea el leaderboard de temporada** (los puntos de temporada
  vuelven a 0) y arranca la siguiente — **el imperio NO se toca**.
- Esto da el "final" con ganador y rejugabilidad, sin castigar al jugador borrándole todo.

### 2.3 Puntos de temporada (cómo se acumulan)
Aditivos por **eventos del período** (data-driven, valores ajustables):
- ganar un combate ofensivo, completar una expedición, terminar una investigación/edificio, subir
  de score, etc. Se escriben en `SeasonScore` desde los procesadores existentes (combat/expedition/
  research) o se derivan del **delta de `player_score`** desde el inicio de la temporada.
- v1 simple recomendado: **delta de `player_score`** (snapshot al unirse a la temporada vs. al
  cierre) + bonus por victorias. Mantiene el cálculo barato y "seasonal".

## 3. Inicio del juego (onboarding + protección de novatos)

- **Onboarding** (ya existe): galaxia → planeta → raza. Con [SDD 8] la galaxia es una
  **instancia con cupo**; al entrar se te asigna una instancia abierta o se crea una.
- **Newbie protection** (nuevo): `Player.protected_until = now + NEWBIE_HOURS` (config, p.ej. 48 h).
  Mientras dure:
  - **no te pueden atacar** (en `combat.start_attack`, si `defender.protected_until > now` → error);
  - **no podés atacar a humanos** (sí a NPCs/"food") — para que aprendas sin que te farmeen;
  - la protección **termina** al vencer el tiempo **o** cuando hacés tu primer ataque ofensivo
    (opt-out explícito).
- Ya tenemos NPCs por raza (potenciales "food kingdoms") y la guía in-game para los primeros pasos.
- `GET /players/me` expone `protected_until` y la **temporada actual** (nombre, tiempo restante,
  tu puesto) para que el cliente muestre el contexto de inicio.

## 4. "Final" (cierre de temporada)

- No hay fin del mundo; el "final" es el **cierre de temporada**: ranking final, **ganadores**,
  Hall of Fame + insignias, y un **mensaje/evento del mundo** anunciándolo (reusa `world` +
  notificaciones). Arranca la próxima temporada automáticamente.
- **Apertura/cierre automáticos**: una función en `worker.run_tick` revisa si la temporada activa
  venció → la cierra (snapshot HoF, reset de `SeasonScore`) y abre la siguiente
  (`ensure_active_season`), igual patrón que `ensure_npcs`. También por `POST /admin/season/close`.

## 5. Modelo de datos (aditivo)
- `Season`: `id`, `name/seq`, `starts_at`, `ends_at`, `status`.
- `SeasonScore`: `(season_id, player_id)` → `points` (+ snapshot de score inicial si usamos delta).
- `HallOfFame`: `player_id`, `season_id`, `rank`, `points`, `awarded_at` (**persiste**; nunca se
  borra). Opcional `badge`/`title` cosmético.
- `Player.protected_until: datetime | null` (newbie protection).
- Migración Alembic aditiva (con `server_default` donde aplique; ojo SQLite, ver CLAUDE.md).

## 6. API (full-API, versionada)
```
GET  /api/v1/seasons                 -> temporada actual + recientes (con countdown)
GET  /api/v1/seasons/current/ranking -> top por puntos de temporada (por instancia y/o global)
GET  /api/v1/players/me              -> +protected_until, +season standing, +HoF count
POST /api/v1/admin/season/close      -> cierre manual (admin/tests)
```
Cambios aditivos; las cuentas actuales entran a la temporada vigente sin perder nada.

## 7. Interacción con galaxy instances (SDD 8)
- La temporada es una **ventana de tiempo global**; el ranking puede ser **por instancia**
  (competís contra tu galaxia) **y** global (HoF general). Encaja: cada instancia ya acota las
  interacciones; la temporada acota el tiempo.

## 8. Plan de tests (regla del proyecto)
**Servicio**: abrir/cerrar temporada (vencimiento en el tick) crea HoF de los top y resetea
`SeasonScore` sin tocar el imperio; los puntos de temporada acumulan en un evento (p.ej. victoria);
newbie protection bloquea ataque a/desde protegido y se libera al vencer o al primer ataque.
**E2E HTTP** (`tests/test_api_e2e.py`): `GET /seasons` y `/seasons/current/ranking` 200 con datos;
atacar a un jugador protegido → 4xx claro; `/players/me` reporta `protected_until` y puesto;
`POST /admin/season/close` cierra y abre la siguiente.

## 8.bis Estado de implementación (2026-06-22) — v1 hecho
- **Modelos**: `Season`, `HallOfFame`, `Player.protected_until` (+ migración aditiva).
- **`app/services/seasons.py`**: `ensure_active_season`, `close_due_seasons`/`close_current_now`
  (snapshot top-N al Hall of Fame + abre la siguiente; **el imperio no se borra**), `season_ranking`
  (en vivo por `player_score`), `hall_of_fame`. Apertura/cierre en el **tick** (`worker.run_tick`).
- **Newbie protection**: `onboarding` setea `protected_until`; `combat.start_attack` **bloquea
  atacar a un protegido** y **atacar a un humano cancela tu protección** (opt-out); atacar NPCs no.
- **API**: `GET /seasons`, `GET /seasons/current/ranking`, `GET /seasons/hall-of-fame`,
  `POST /admin/season/close`. `/players/me` expone `protected_until` + `season`.
- **Web**: card "📅 Temporada" (countdown + ranking + escudo de novato), i18n ES/EN.
- **Tests**: `tests/test_seasons.py` (8 servicio) + 2 e2e + 1 browser. 137 unit/e2e + 13 browser ✅.

**Decisión / refinamiento vs. §3**: en v1 el ranking de temporada se computa **en vivo con
`player_score`** y se congela en el Hall of Fame al cerrar (no hay tabla `SeasonScore` acumulable
todavía → **follow-up**). Y la protección permite atacar a un humano **cancelando** tu escudo
(opt-out) en vez de prohibirlo, que es más claro.

**Pendiente (follow-up)**: `SeasonScore` acumulable (puntos por eventos / delta de score),
evento del mundo al cerrar temporada, y ligar la temporada a las **galaxy instances** (SDD 8).

## 9. Riesgos / decisiones
- **Puntos de temporada**: elegir entre "delta de score" (simple) vs. "eventos ponderados" (más
  rico). v1 = delta + bonus por victorias; data-driven para tunear.
- **Abuso de protección**: no atacar durante protección evita farmear bajo escudo; el opt-out al
  primer ataque lo cierra. Tunear `NEWBIE_HOURS`.
- **Duración de temporada**: muy corta = estrés; muy larga = sin clímax. Config; calibrar.
- **Monetización**: fuera de alcance ahora. Si más adelante: insignias/temporada premium
  **cosméticas** (no pay-to-win) — su propio SDD.
