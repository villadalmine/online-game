# Changelog

Registro de todo lo que vamos logrando. Formato basado en
[Keep a Changelog](https://keepachangelog.com/). Fechas en formato AAAA-MM-DD.

> Regla del proyecto: **toda feature entra con su test e2e** (`tests/test_api_e2e.py`).

## [Unreleased]

### 2026-06-21 — Web: naves viajando + mapa por galaxia
- **Flotas en tránsito** ("naves viajando"): nueva sección en el mapa que dibuja cada flota en
  vuelo como una nave que se desplaza por su trayecto, con ETA en vivo:
  - 🚀 ataque saliente (origen → destino) · ↩ flota volviendo · 🛰 expedición a una luna ·
    ☄ ataque entrante (fog of war: origen `???`).
  - El progreso es exacto sin tocar el backend: para ataques deriva la duración de un tramo de
    `returns_at − arrives_at`; para expediciones usa `duration_seconds` del catálogo; para
    entrantes (solo `arrives_at`) hace fallback midiendo desde que se ve. La nave interpola
    suave (`transition: left`) entre los samples de 1s.
- **Mapa agrupado por galaxia**: usa `catalog.galaxies` (Vía Láctea + Andrómeda), resalta la
  galaxia donde estás y atenúa el resto. Orbes con color para todos los planetas
  (mercury/vega_prime/nyx) y fallback para nuevos.
- e2e de navegador (`tests/browser/test_ui.py`): inyecta el shape real de la API
  (`missions_outgoing`/`expeditions`/`missions_incoming`) y verifica que se renderiza una nave
  por tramo, ubicada al 50% del trayecto, con origen→destino resueltos por planeta; + caso
  vacío ("sin flotas en vuelo", sin naves sueltas). Screenshot `06-transit.png`.

### 2026-06-20 — make run mata el server viejo antes de arrancar
- `make run`/`run-lan` hacen un `pkill` del uvicorn previo antes de levantar, para no quedar
  con **dos servers en el mismo puerto** (causa real de 500s al jugar local: el server viejo
  servía el 8099 con un `game.db` ya borrado/reseteado por debajo). Patrón `[u]vicorn` para que
  `pkill` no se mate a sí mismo. `make stop` usa el mismo patrón.

### 2026-06-20 — Expuesto vía Gateway API (Cilium)
- Chart: `HTTPRoute` opcional (`--set gateway.enabled=true`, host/gateway configurables) para
  exponer la API por un Gateway (ej. Cilium). Desplegado: el juego queda en
  `http://online-game.cluster.home/`. Verificado end-to-end por el gateway (health/register/web).

### 2026-06-20 — Desplegado en k3s (ARM64) ✅
- Imagen construida con **Kaniko** in-cluster desde el repo público → `registry.registry:5000`,
  arquitectura ARM64. Helm chart desplegado en namespace `online-game` (API + Postgres + Redis +
  initContainer de migraciones). Verificado: `/health` `db=postgres`, register/onboard OK, web sirve.
- Chart: **`nodeSelector` configurable** (cluster mixto / imagen single-arch). Aprendizajes del
  deploy real: pods en el nodo amd64 daban `exec format error` (→ fijar arch), y un nodo no
  resolvía el registry interno (→ fijar a un nodo bueno o arreglar `registries.yaml`).

### 2026-06-20 — Fix Dockerfile (build de imagen)
- El Dockerfile hacía `pip install .` con solo `pyproject.toml` copiado → fallaba
  (`package directory 'app' does not exist`). Ahora copia `app/` y `clients/` antes de instalar.
  Lo detectó el build real con **Kaniko** en el cluster (el path de Docker no estaba cubierto
  por los tests, que usan `pip install -e` con el código completo).

### 2026-06-20 — Deploy en k8s: OpenRouter en el chart + imagen multi-arch por CI
- Helm chart: soporte de **OpenRouter** (token como `Secret` vía `--set openrouter.apiKey`,
  no se commitea; si está vacío las NPC usan reglas), `npc.brain`, `AUTO_TICK_SECONDS`, y
  `imagePullSecrets` opcional. Imagen por defecto desde **GHCR**.
- CI: workflow `build-image` que construye **multi-arch (amd64+arm64)** y publica en GHCR
  (para clusters Raspberry Pi/k3s sin builder local) + workflow `ci` (ruff + pytest).
- `deploy/helm/values-local.example.yaml` (gitignored `values-local.yaml`) para el token local.
- README con pasos de deploy en k3s/ARM. `helm lint` ok; render validado con token+pull-secret.
- Nota: el deploy real (`helm install`) corre una vez que la CI publica la imagen ARM (esta
  máquina no tiene builder de contenedores).

### 2026-06-20 — Replicable y publicable (probado en Linux)
- `make publish REPO=nombre` crea el repo público en GitHub y sube todo (vía `gh`).
- `make run`/`run-lan` ahora prenden el auto-tick por defecto (`AUTOTICK=15`), así una copia
  recién clonada tiene mundo vivo sin tocar `.env`.
- README con flujo de publicar + replicar (clonar → `make install` → `make run`).
- **Verificado en Linux** (clean-room): clon fresco desde GitHub → install → server arranca,
  DB migra sola, registro 201, web sirve, 86 tests verdes; sin `.env` (defaults).

### 2026-06-20 — Visibilidad de la DB en uso
- Al arrancar, el server **loguea qué base usa** (`[online-game] DB=sqlite (...) · auto-tick=...`),
  con la contraseña redactada. `/health` ahora devuelve `db` (sqlite/postgres) y la web muestra
  un pill 🗄 en el header. Para que quede claro si estás en SQLite local o Postgres (Docker) y
  no confundir partidas. e2e: `/health` expone `db`.

### 2026-06-20 — Tests de navegador (Playwright) con screenshots
- `tests/browser/` maneja la web real en Chromium: registro → onboarding → construir →
  crear alianza (ve beneficios explicados) → guía; + verifica que la alianza NPC sale
  marcada "no unible". Guarda **screenshots** de cada pantalla en
  `tests/browser/screenshots/` (gitignored). Corren con `make test-ui` (aparte de `make test`,
  que los ignora porque necesitan navegador). Deps opcionales en el extra `ui`.

### 2026-06-20 — Web: alianzas más claras + CLAUDE.md
- UI de alianzas reescrita para que se entienda: al crear, cada **tipo** muestra su
  descripción y **beneficios explicados** (no solo el nombre); estando en una alianza ves
  **miembros, beneficios en lenguaje claro, alertas y comercio**; las alianzas de **NPC**
  salen marcadas y **sin botón de unirse** (con el motivo). El formulario ya no se borra solo.
- `CLAUDE.md` agregado (guía de arquitectura/comandos para el repo).
- e2e: el catálogo expone `alliance_types` con `benefits`+`description` (lo que la web muestra).

### 2026-06-20 — Web: UI de alianzas (tipo, beneficios, comercio, visión) + repo público
- La web ahora deja **elegir el tipo de alianza** al crear, muestra sus **beneficios**, una
  **alerta de visión compartida** (aliados bajo ataque) y un mini-form de **comercio** para
  transferir minerales a un aliado (si el tipo lo permite). Sigue consumiendo solo la API.
- **Fix (code-review)**: un humano ya no puede unirse a la alianza de las NPC (daba inmunidad
  + beneficios); la alianza NPC se identifica por tener miembros NPC (no por nombre), evitando
  que un humano la "capture" usando el mismo nombre.
- Repo preparado para publicar: `LICENSE` (MIT), `.dockerignore`, `.gitignore` endurecido
  (nunca sube `.env` ni `*.db`), README con 3 modos (full-local / LAN / online) y `make`
  targets `run`/`run-lan`/`up`/`tunnel`.

### 2026-06-20 — Alianzas con beneficios y tipos (data-driven)
- **Tipos de alianza** en `content/alliances.yaml` (no-agresión / defensiva / plena), cada uno
  habilita beneficios. Se elige al crear (`type`). La no-agresión aplica siempre.
- **Beneficios**:
  - `shared_bonus`: multiplicador compartido (prod/ataque/defensa) a todos los miembros.
  - `shared_unit_tech`: cada raza de la alianza comparte su `unit_perk` (en `races.yaml`) →
    p.ej. terran+marciano = +prod y +ataque para todos. Se aplica vía `services/effects.py`.
  - `mutual_defense`: los aliados prestan 25% de su defensa cuando atacan a un miembro.
  - `shared_vision`: ves los ataques entrantes sobre tus aliados (`/me.alliance_incoming`).
  - `trade`: `POST /alliances/transfer` mueve minerales entre aliados.
- `/me` expone `alliance_type`; el catálogo lista los tipos. CLI `alliance-create ... [tipo]`,
  `alliance-transfer`. Migración Alembic (`alliances.type`).
- Tests: 6 de servicio (bonus, unit-tech, defensa mutua, comercio) + 2 e2e (tipo+comercio,
  visión compartida). Smoke en vivo: alianza plena terran+marciano → ataque/prod ×1.21.

### 2026-06-20 — DB auto-migra al arrancar + Guía in-game + sacar "Avanzar" del jugador
- **Migraciones automáticas en el arranque** (`run_migrations()` vía `asyncio.to_thread`):
  el server aplica Alembic a head al iniciar → **ya no hace falta `make db-reset`** al cambiar
  el esquema en dev (idempotente; sirve para SQLite local y Postgres). Solo se necesita un
  último reset si venías de una DB vieja creada con `create_all`.
- **Guía in-game** (web): tarjeta "📖 ¿qué es cada cosa?" que explica energía, minerales
  (in-game ↔ real, desde el catálogo), edificios, unidades, expediciones, combate,
  investigación y alianzas.
- **Quitado el botón "Avanzar"** de la UI del jugador (rompía el tiempo real; el mundo ya
  avanza solo con el auto-tick). `/admin/tick` queda como herramienta de dev/CLI/tests.

### 2026-06-20 — Ranking por alianza + NPCs aliados + UX de costos en la web
- **Ranking por alianza**: `GET /alliances/ranking` (suma de scores de miembros). Score de
  jugador extraído a `services/scoring.py` y reutilizado por ambos rankings. CLI `alliance-ranking`.
- **NPCs aliados**: todas las NPC entran a una alianza compartida ("Consorcio Estelar"/AI),
  cooperan y no se atacan entre sí; el cerebro NPC excluye bases aliadas al elegir objetivo.
- **Web — costos y avisos**: ahora muestra el costo (en minerales reales por raza) y un aviso
  **⚠ te falta / ✓ alcanza** para construir, entrenar (×cantidad) y expediciones; tooltips que
  explican "Avanzar" (forzar tick) y "Refrescar" (F5 de datos).
- Migración: ninguna nueva (reusa `alliances`). Tests: 2 e2e (ranking de alianza, NPCs comparten alianza).

### 2026-06-20 — Web: paneles de Investigación, Ranking y Alianzas
- La web ahora expone las features de profundidad (sigue siendo puro consumidor de la API):
  - **🔬 Investigación**: lista las techs del catálogo con efecto/costo, botón "investigar",
    estado ✓ lista / en progreso con barra (de `/catalog` + `/me`).
  - **🏆 Ranking**: tabla bajo demanda desde `/players/ranking`.
  - **🤝 Alianzas**: tu alianza con "salir", o crear (nombre+tag) y lista para "unirse"
    (de `/alliances` + `/me`).
- e2e: la página servida incluye los paneles (Investigación/Ranking/Alianzas/Galaxia).

### 2026-06-20 — Alianzas
- Jugadores forman alianzas (`Alliance` + `Player.alliance_id`, `services/alliances.py`):
  crear, unirse, salir, listar y ver detalle con miembros.
- **No se puede atacar a un aliado**: `start_attack` rechaza si atacante y defensor comparten
  alianza. `/me` muestra `alliance_id`/`alliance_name`; el scoreboard incluye `alliance_id`.
- API `POST /alliances`, `/{id}/join`, `/leave`, `GET /alliances`, `/{id}`. CLI
  `alliances`, `alliance-create`, `alliance-join`, `alliance-leave`.
- Migración Alembic (`alliances` + `players.alliance_id`, FK nombrada para batch SQLite).
- Tests: 3 e2e (crear/unirse/listar, no atacar aliado, salir).

### 2026-06-20 — Más juego: investigación, ranking y más mundos
- **Investigación/tecnologías** (`content/technologies.yaml`, `services/research.py`):
  cuesta minerales+energía, requiere laboratorio activo, tarda un tiempo, y al completarse
  otorga un **efecto permanente** (producción/ataque/defensa). `services/effects.py` unifica
  boons + techs y se aplica en economía y combate. API `POST /research`; `/me` expone
  `technologies` y `research`; el catálogo lista las techs. CLI `research <key>`.
- **Ranking**: `GET /players/ranking` con puntaje (edificios + poder militar + minerales +
  techs + victorias), ordenado. CLI `ranking`.
- **Más mundos**: Mercurio en la Vía Láctea + nueva galaxia **Andrómeda** (Vega Prime, Nyx),
  todo data-driven en `content/planets.yaml`. Onboarding ya soporta múltiples galaxias.
- Migración Alembic (`player_techs`, `research_orders`). Tests: 3 de servicio + 4 e2e
  (research flow, requiere lab, ranking, más planetas/galaxias). Smoke en vivo: prod 1.0→1.25.

### 2026-06-20 — Pulido visual de la web
- **Mapa de la galaxia**: planetas (Tierra/Marte/Venus) con orbes animados y sus colonias;
  click en una base enemiga autocompleta el objetivo de ataque.
- **Barras de progreso animadas** en colas (construcción/entrenamiento/expedición) calculadas
  desde el catálogo; flotas con countdown + botón recall; ataques entrantes resaltados.
- Refresco suave (countdowns/mapa cada 1s, estado cada 4s), tema más prolijo, responsive,
  indicador "● en vivo" del stream. Todo sigue siendo puro consumidor de la API.

### 2026-06-20 — World auto-tick + UX de sesión en la web
- **Auto-tick**: loop en segundo plano (`AUTO_TICK_SECONDS`, lifespan de FastAPI) que avanza
  el mundo (turnos NPC, llegadas de flotas, colas) sin intervención. 0 = apagado
  (multi-réplica usa el CronJob). Verificado: dejando el server solo, las NPC nacen y juegan.
- Web: recuerda el último usuario, aclara que los datos persisten en la cuenta del servidor
  (entrás desde cualquier dispositivo) y muestra errores de auth claros.

### 2026-06-20 — Push en tiempo real (SSE) + cliente web jugable
- **SSE**: `GET /notifications/stream?token=...` empuja notificaciones en vivo
  (catch-up + nuevas). Auth por query (EventSource no manda headers). Lógica en
  `stream_events` (testeable con `once=True`); el endpoint hace loop hasta desconexión.
- **Cliente web** (`web/index.html`, vanilla JS) servido en `GET /`: registro/login,
  onboarding, estado, construir/entrenar/atacar/expedición/tick, scoreboard y un panel de
  **notificaciones en vivo** vía `EventSource`. Ahora se puede jugar desde el navegador.
- Tests: generador SSE emite la notificación; la web responde en `/`.

### 2026-06-20 — NPCs más tácticos
- **Reglas tácticas** (`RuleBasedBrain`): respuesta a amenazas (si hay ataque entrante,
  **recall** de la flota propia para defender, o construir **torreta**); fabrica **tanques**
  (build factory) además de soldados; ataca el blanco con **menor defensa estimada** y solo
  si su poder de ataque la supera con margen; manda **expediciones** si tiene transbordador.
- **LLM táctico**: el `state` ahora incluye `incoming_attacks`, `my_missions`,
  `defense_estimate` por enemigo y `reachable_moons`; el dispatcher acepta acciones
  `recall` y `expedition`. (El default por reglas es el confiable; el LLM free es opcional.)
- Tests: 4 de servicio (recall y torreta bajo ataque, state táctico, LLM recall).

### 2026-06-20 — Notificaciones
- Tabla `Notification` + `services/notifications.py`. Se emiten en los puntos donde el
  estado cambia del lado servidor (una sola vez por evento): **ataque entrante** (al
  defensor, fog of war), **batalla resuelta** (atacante y defensor), **flota de vuelta**,
  **expedición de vuelta**, **edificio listo**, **unidades entrenadas**.
- API: `GET /notifications` (`?unread=true`), `POST /notifications/read` (todas o `ids`).
  `/players/me` expone `unread_notifications`.
- CLI: `notifications`, `read`. Migración Alembic `notifications`.
- Tests: 2 e2e (ataque entrante notifica al defensor; edificio listo notifica + marcar leídas).

### 2026-06-19 — Defensas de edificio + recall de flotas
- **Torreta defensiva** (`content/buildings.yaml`, `category: defense`, `defense_power`):
  suma defensa fija a la base. En la resolución, las torretas activas del base objetivo
  refuerzan al defensor (con bonus de raza/boon) → una base bien fortificada aguanta sin unidades.
- `resolve_combat` admite `defender_flat_defense` (puro/testeable).
- **Recall**: `POST /combat/missions/{id}/recall` retira una flota en vuelo de ida; viaja de
  vuelta lo ya recorrido y regresa con toda la fuerza, sin combate. Solo el dueño, solo outbound.
- CLI: `recall <mission_id>`. Tests: 1 unit (flat defense) + 2 e2e (torretas aguantan, recall sin batalla).

### 2026-06-19 — Combate con viaje/tiempo (flotas, resolución diferida, ida y vuelta)
- El ataque deja de ser instantáneo: `POST /combat/attack` ahora **despacha una flota**
  (`AttackMission`). Las unidades se **bloquean** (salen del stock mientras viajan).
- Tiempo de vuelo según **distancia** entre planetas (`TRAVEL_SECONDS_SAME_PLANET` /
  `TRAVEL_SECONDS_CROSS_PLANET`). El defensor ve el ataque entrante (fog of war: sin
  composición) → ventana para reaccionar.
- **Resolución diferida** al llegar (`process_missions` en el tick y en `state.advance`):
  batalla con `resolve_combat` + bonus de raza + boons; bajas y botín.
- **Viaje de ida y vuelta**: sobrevivientes + botín regresan y se re-acreditan al volver.
- `/players/me` muestra `missions_outgoing` (tuyas) y `missions_incoming` (entrantes).
- Migración Alembic `attack_missions`. NPCs ahora lanzan flotas (mismo flujo).
- Tests: 2 e2e (despacho+bloqueo+fog; ciclo completo viaje→batalla→retorno). Smoke en vivo OK.

### 2026-06-19 — Cerebro LLM enriquecido: personalidad + memoria
- Cada raza tiene `personality` en `content/races.yaml` (marciano belicoso, venusiano
  tecnológico/cauto, terrícola económico). Se inyecta en el prompt → las NPC juegan en
  personaje. Verificado en vivo: mismo escenario, marciano ataca / venusiano hace ciencia /
  terrícola mina.
- **Memoria corta** por NPC (`Player.npc_memory`, JSON de últimas 8 acciones) + resumen de
  `recent_battles` (de `CombatLog`), incluidos en el prompt para continuidad.
- Migración Alembic para `npc_memory` (con `server_default`).
- Tests: personalidad distinta por raza, memoria que se acumula entre turnos, prompt-state
  con personality/recent_actions.

### 2026-06-19 — Redis: cache + rate limit (con degradación elegante)
- Capa `app/core/redis.py`: si `REDIS_ENABLED=false` o Redis no responde, todo degrada a
  no-op (sin romper local/tests). `get_redis` es dependency de FastAPI.
- **Cache** del catálogo (`GET /catalog`, TTL configurable) y **rate limit** de ataques
  (`POST /combat/attack` → 429 al exceder `ATTACK_RATE_LIMIT_PER_MIN`).
- compose/Helm activan `REDIS_ENABLED=true`. Tests con `fakeredis`: 4 unit + 2 e2e.

### 2026-06-19 — Tooling: Makefile + script de demo
- `Makefile` con targets: `install`, `run`, `demo`, `test`, `lint`, `fmt`, `migration`,
  `up`/`down` (docker), `clean`. `make help` los lista.
- `scripts/demo.sh`: levanta un server efímero (SQLite fresca) en un puerto libre (8099),
  corre el flujo completo por CLI (register→onboard→build→train→tick→players→me) y apaga
  el server solo. Evita el choque típico con un `http.server` en el 8000.

### 2026-06-19 — Razas NPC con IA (reglas + OpenRouter opcional)
- NPCs como jugadores reales (`is_npc`), uno por raza, creados/onboardeados automáticamente.
- Cerebro **enchufable** (`services/npc.py`): `RuleBasedBrain` (default, heurística
  determinista) y `LlmBrain` (OpenRouter, opcional) detrás de la misma interfaz, con
  **fallback duro a reglas** ante cualquier fallo (red/rate-limit/JSON inválido/acción
  infactible) — el tick nunca se rompe.
- Toman **una acción por tick** vía los mismos servicios que un humano (build/train/attack),
  ejecutado por `worker.run_tick` (refactor: corre sobre una sesión, drivable por HTTP).
- API: `GET /players` (scoreboard con bases NPC para atacar) y `POST /admin/tick`
  (avanzar el mundo a demanda; útil para demo/tests). CLI: `players`, `tick`.
- OpenRouter: modelo free por defecto `google/gemma-4-31b-it:free` (elegido por latencia
  + JSON correcto). Config: `NPC_BRAIN`, `OPENROUTER_*`. Key en `.env` (gitignored).
- Migración Alembic para `is_npc` (con `server_default` seguro en tablas pobladas).
- Tests: 4 de servicio (incl. LLM con `decide` inyectado + fallback) + 2 e2e HTTP
  (tick crea NPCs y actúan; humano ataca un NPC). Smoke en vivo confirmado contra OpenRouter.

### 2026-06-19 — Migraciones con Alembic
- **Alembic** configurado para esquema de base de datos (async, lee `DATABASE_URL`).
  - `alembic.ini`, `migrations/env.py`, migración inicial con todas las tablas.
  - Prod usa migraciones; dev/sqlite sigue pudiendo usar `init_models()`.
  - Test que verifica que `alembic upgrade head` crea todas las tablas de los modelos.
- **CHANGELOG.md** creado para trackear el progreso.

### 2026-06-19 — Expediciones a lunas + boons de dioses
- Enviar expedición a una luna de tu galaxia: cuesta energía + requiere transbordador;
  al volver entrega recursos premium (He-3, tierras raras, hielo) y un **boon temporal**.
- Boons (`production`/`attack`/`defense`) aplicados *lazy* en producción y combate,
  encima de los bonus de raza. Todo data-driven en `content/gods.yaml`.
- API: `GET /expeditions/moons`, `POST /expeditions`. `/players/me` expone `expeditions` y `boons`.
- Servicios: `services/expedition.py`, `services/boons.py`. CLI: `moons`, `expedition`.
- Tests: 5 de servicio + 3 e2e HTTP.

### 2026-06-19 — Combate PvP
- Atacar la base de otro jugador comprometiendo una fuerza; resolución con `stats`
  (attack/defense) + bonus de raza (marciano +ataque, venusiano +defensa).
- Bajas en ambos lados y **botín** de minerales al ganar. Historial de combates.
- API: `POST /combat/attack`, `GET /combat/reports`. Servicio: `services/combat.py`
  (`resolve_combat()` puro/determinista). Config: `ATTACK_ENERGY_COST`, `LOOT_FRACTION`.
- CLI: `attack`, `reports`. Tests: 4 puros + 3 e2e HTTP.

### 2026-06-19 — Entrenamiento de unidades
- Entrenar personajes (trabajador/militar/científico) y unidades pesadas
  (tanque/barco/avión/transbordador). Cuesta energía + minerales (resueltos por raza),
  requiere el edificio activo correspondiente, entra a una cola y se entrega al cumplirse.
- API: `POST /bases/{id}/train`. `/players/me` expone `units` y `training`.
- Servicio: `services/training.py`. CLI: `train`. Tests: 3 integración + 2 e2e HTTP.
- Suite **e2e HTTP** (`tests/test_api_e2e.py`) creada para cubrir todos los endpoints.

### 2026-06-19 — Slice vertical jugable (MVP inicial)
- Juego online por turnos asíncrono, **API-first** (FastAPI), con planetas y minerales
  **reales** (Vía Láctea: Tierra, Marte, Venus). 3 razas con mapeo configurable
  rol→mineral. Energía que regenera por hora (cálculo *lazy* por timestamp).
- Flujo: registro/login (JWT) → onboarding (galaxia/planeta/raza) → construir edificios
  (incl. minas que producen minerales) vía API.
- **Contenido data-driven** en `content/*.yaml` (minerales, planetas, razas, edificios,
  unidades, dioses): rebalancear = editar un valor.
- Stack: FastAPI + SQLAlchemy async + Postgres/Redis (SQLite para dev/tests).
- Portabilidad: `Dockerfile`, `docker-compose`, chart **Helm** (api + worker CronJob + pg + redis).
- Cliente **CLI** de referencia. Documentación: `README`, `docs/{game-design,architecture,development}.md`.
- Tests: energía, producción, contenido, flujo end-to-end.
