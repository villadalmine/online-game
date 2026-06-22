# Changelog

Registro de todo lo que vamos logrando. Formato basado en
[Keep a Changelog](https://keepachangelog.com/). Fechas en formato AAAA-MM-DD.

> Regla del proyecto: **toda feature entra con su test e2e** (`tests/test_api_e2e.py`).

## [Unreleased]

### 2026-06-22 — SDD 6 implementado: login passwordless por email + código OTP
- **Passwordless (código siempre)**: `POST /auth/request-code` (respuesta uniforme anti-enumeración)
  + `POST /auth/verify-code` → JWT (signup = login: crea el `Player` si el email es nuevo). El JWT
  mantiene la sesión, así que no pide código en cada visita.
- **Servicio** `app/services/auth_otp.py` adaptando el patrón de `bot-telegram` a SQLAlchemy async:
  CSPRNG (`secrets`), código guardado como **HMAC-SHA256(code, OTP_SECRET)** (nunca en claro), TTL,
  máx intentos, **compare constant-time**, cooldown de reenvío. Modelo `EmailOtp` + `Player.email`
  (migración aditiva).
- **Mailer agnóstico sin deps** `app/services/mailer.py`: `console` (default, loguea el código —
  dev/CI sin SMTP) / `smtp` (stdlib) / `resend` (httpx). Email del código **i18n** (ES/EN).
- **Dev no se fuerza**: el login **usuario+contraseña** actual se mantiene (`/auth/login`,
  `/auth/register`) para dev/CLI/tests/NPC.
- **Web**: sección "Entrar con email (sin contraseña)" en la card de login.
- Tests: `tests/test_auth_otp.py` (7) + 3 e2e (`request/verify`, uniforme/inválido, código malo)
  + 1 browser. 128 unit/e2e + 12 browser verdes. SDD 6 actualizado con decisiones e impl.

### 2026-06-22 — Durabilidad: Postgres con PVC + backup (impl SDD 10)
- **Fix de pérdida de datos**: el Postgres del chart pasó de `Deployment` **sin volumen** a
  **`StatefulSet` con `volumeClaimTemplates` (PVC)** en `/var/lib/postgresql/data` (`PGDATA` en
  subdir para evitar `lost+found`) + `readinessProbe` `pg_isready`. **El PVC sobrevive a que el pod
  muera** → ya no se pierde la base. (`deploy/helm/templates/datastores.yaml`)
- **Knobs** (`values.yaml`): `postgres.persistence.{enabled,size,storageClass}` (default on, 8Gi).
  `persistence.enabled=false` → `emptyDir` (solo pruebas).
- **Postgres externo**: `postgres.externalUrl` + `postgres.enabled=false` (managed/operador con
  PITR); `dbUrl` lo honra (`_helpers.tpl`).
- **Backup opt-in**: `backup.enabled` → CronJob `pg_dump -Fc` a un PVC con retención
  (`postgres-backup-cronjob.yaml`). Offsite/cifrado y PITR quedan como follow-up.
- Verificado con `helm lint` + `helm template` (persistente / emptyDir / DB externa / backup on).
  SDD 10 actualizado con estado de implementación.

### 2026-06-22 — SDD 10 (diseño): durabilidad, backup y restore
- **[SDD 10](docs/sdd-durability-backup-restore.md)**: cómo no perder datos si un pod muere.
  🔴 **Hallazgo bloqueante**: el Postgres del chart (`datastores.yaml`) corre como `Deployment`
  **sin PVC** → si el pod se reprograma, **se pierde toda la base**. Fix: `StatefulSet`+PVC (o
  `postgres.enabled=false` + Postgres gestionado/operador con PITR). Backups offsite cifrados
  (`pg_dump` CronJob + retención, o WAL/PITR) y **runbook de restore probado** (RPO/RTO).
- Aclarado por qué la **app ya es crash-safe**: API stateless + estado lazy por timestamp
  (se reconstruye al leer) + transacciones atómicas + Redis como cache reconstruible. La
  durabilidad depende solo de Postgres. Solo diseño.

### 2026-06-22 — SDD 7/8/9 (diseño): escalado, límites de galaxia y LLM local en GPU
- **[SDD 7 — Capacidad y autoscaling](docs/sdd-capacity-autoscaling.md)**: metodología para
  estimar CCU, HPA + resource requests + PgBouncer; identifica los cuellos reales (el `run_tick`
  O(N) global y el SSE que abre sesión DB por poll) y cómo atacarlos.
- **[SDD 8 — Límites de galaxia](docs/sdd-galaxy-limits.md)**: `GalaxyInstance` con `capacity`
  (shard del mundo) para que una partida no colapse; tick e interacciones por instancia —
  también es la unidad de sharding del SDD 7.
- **[SDD 9 — LLM local en GPU](docs/sdd-local-gpu-llm.md)**: servir NPCs/asistente desde GPU local
  (Tesla P4 / Quadro Maxwell) con Ollama/LiteLLM; una GPU = serial (se encola, con fallback),
  reserva por pod, y qué modelo local conviene (Qwen2.5 3–7B JSON/ES-EN). La app ya es agnóstica;
  es operación + config.
- Solo diseño; sin código. Implementación tras decisiones de deploy.

### 2026-06-22 — SDD 6 (diseño): login para producción (email + código OTP)
- Diseño del login passwordless por **email + código** para abrir al público, **adaptando el
  patrón OTP de `bot-telegram`** (`src/otp.py`: CSPRNG, HMAC-SHA256 con salt, TTL, máx intentos,
  compare constant-time, respuestas uniformes anti-enumeración) a **SQLAlchemy async** (modelo
  `EmailOtp` + `Player.email`), con **mailer agnóstico sin deps nuevas** (console/SMTP stdlib/
  Resend httpx) y rate-limit. Convive con el login username+password actual (no rompe).
  [docs/sdd-auth-login.md](docs/sdd-auth-login.md). Solo diseño; la entrega real de email se
  verifica en deploy.

### 2026-06-22 — SDD 5 (diseño): bot de Telegram
- Diseño del bot como **cliente delgado** sobre `/api/v1`: long-poll con `httpx` (sin deps
  nuevas), opt-in por `TELEGRAM_BOT_TOKEN`, comandos `/login /me /build /train /attack /research`,
  push de notificaciones, tests con transporte mockeado. [docs/sdd-telegram-bot.md](docs/sdd-telegram-bot.md).
- **Implementación bloqueada** hasta tener un token real (verificación end-to-end). Solo diseño.

### 2026-06-22 — SDD 4: i18n del juego (ES/EN)
- **Contenido data-driven bilingüe**: cada item de `content/*.yaml` suma `name_en`/
  `description_en`/`real_en` (ES sigue siendo el default; si falta el `_en`, cae al ES).
  `personality`/`taunts` de las NPC quedan en su idioma (son model-facing, no UI).
- **API**: `GET /catalog?lang=en|es` (gana sobre `Accept-Language`; default `es`); cache Redis
  **por idioma** (`catalog:v1:<lang>`). Helpers puros `localize`/`localize_catalog`/`normalize_lang`
  en el registry. Planetas anidados en `galaxies` también se localizan; las claves `*_en` se quitan
  de la respuesta.
- **Web**: toggle **🌐 ES/EN** (persistido en `localStorage`) que recarga el catálogo en el idioma
  y traduce el chrome (títulos de panel vía `data-panel`, botones vía `data-i18n`, placeholder del
  asistente). Cobertura parcial del chrome (resto de textos fijos = follow-up).
- Tests: `tests/test_i18n.py` (unit) + e2e `test_catalog_i18n` + browser `test_language_toggle_en_es`.
  Diseño en [docs/sdd-i18n.md](docs/sdd-i18n.md). Sin migraciones ni deps.

### 2026-06-22 — SDD 3: paneles de la web colapsables (front-only)
- Cada card tiene un `data-panel` estable; un clic en su título lo **pliega a la cabecera**
  (`.collapsed` oculta todo menos el `h2` por CSS, sin reestructurar el HTML). Caret ▾/▸.
- Estado **persistido en `localStorage`** (`panels.collapsed`) → sobrevive recargas. Botones
  globales **⊟ plegar todo / ⊞ expandir todo**.
- Sin API ni backend (pura presentación, coherente con API-first). Diseño en
  [docs/sdd-web-panels.md](docs/sdd-web-panels.md).
- Test de navegador `test_panels_collapse_persist_and_expand` (colapsa, recarga, expande, todo).

### 2026-06-22 — Asistente: claridad hack vs. acción + mina del mineral nombrado
- **Bug**: pedir "mina de silicio" no daba una sugerencia con el mineral, así que se construía
  con el mineral viejo del dropdown (p.ej. hierro). Ahora el asistente detecta el mineral
  nombrado (ES/EN) y ofrece **"Construir mina de <silicio>"** que lleva `target_mineral`; al
  tocarla, el form de build se **sincroniza** (edificio+mineral) para que lo que ves sea lo que
  se construye.
- **UX**: la card separa **Acciones** (gastan recursos) del **Hack** (te *regala* el material/
  energía que falta; no construye), con texto explicativo y nombres legibles — antes parecían dos
  menús sueltos y no se entendía que el hack te da el material.
- Test de servicio `test_ask_named_mineral_suggests_that_mine` + browser actualizado.

### 2026-06-22 — SDD 2 implementado: asistente AI personal + hack (full-API)
- **`app/services/advisor.py`**: consejero por jugador que se apoya en el grafo (SDD 1) y en la
  **misma LLM agnóstica que las NPC** (con **fallback determinista** a los blockers si no hay
  LLM/falla). `ask()` usa **RAG `retrieve`** para enfocar la respuesta y devuelve prosa +
  `BlockerReport` + `suggestions`. Las **suggestions se generan deterministas** del análisis
  (siempre acciones válidas: build/train/research) — la LLM solo redacta.
- **Hack de emergencia** `grant_hack()`: otorga el **faltante mínimo** (minerales/energía, nunca
  unidades/ataques) para desbloquear un objetivo; **cap diario** (default 3) con **reset lazy en
  `Player`** (`assistant_hacks_used`/`assistant_hacks_reset_at`, sin cron/Redis). 4º del día → 429;
  objetivo ya construible → 400; emite notificación privada.
- **LLM compartido**: se extrajo el transporte a **`app/services/llm.py`** (`llm_chat`), usado
  por NPC y asistente (sin duplicar; tests del NPC siguen verdes).
- **Endpoints**: `POST /players/me/advisor/ask`, `POST /players/me/advisor/hack`,
  `GET /players/me/advisor/messages`. Modelo `AdvisorMessage` + migración Alembic aditiva.
- **Web**: card "🧠 Asistente AI" (preguntar, sugerencias de un clic, botón de hack N/3).
- Tests: `tests/test_advisor.py` (4 servicio) + 2 e2e (`ask`/`hack` con budget→429) + 1 browser.
  SDD 2 actualizado (suggestions deterministas). 112 unit/e2e + 9 browser verdes.

### 2026-06-22 — SDD 1 implementado: grafo de dependencias + RAG (full-API)
- **`app/services/depgraph.py`** (puro, sin DB/red): construye el grafo data-driven desde
  `content/*.yaml` y expone consultas deterministas — `prerequisites`, `mineral_sources`
  (mina local / expedición / loot / comercio; los minerales premium se marcan como
  *importados* porque no están en la abundancia de ningún planeta), `analyze`/`BlockerReport`
  (qué falta y **cuánto** — el `need-have` que consumirá el "hack" del SDD 2) y `build_graph`.
- **RAG ligero, sin dependencias nuevas**: `graph_documents` serializa el grafo en documentos
  cortos y `retrieve(query, k)` rankea los relevantes por score léxico **con sinónimos ES/EN**
  (fábrica↔factory, tanque↔tank, hierro↔iron…). Pensado para que la NPC/asistente LLM reciban
  solo los trozos útiles. (Backend de embeddings opcional con fallback léxico, igual patrón que
  el brain LLM — diseñado en el SDD, no implementado aún.)
- **Endpoints full-API** (sin auth, cacheables como `/catalog`): `GET /catalog/graph`,
  `GET /catalog/graph/docs`, `GET /catalog/graph/search?q=&k=`. Raza/planeta inválidos → 404.
- Schemas `Cost`/`Source`/`Blocker`/`BlockerReport` en `app/schemas`.
- Tests: `tests/test_depgraph.py` (10 unit puros) + e2e `test_catalog_graph` y
  `test_catalog_graph_docs_and_search`. SDD actualizado con la sección RAG y el principio
  full-API. Próximo: SDD 2 (asistente) sobre esta base.

### 2026-06-22 — Fix web: "marcar leídas" ahora vacía el feed
- El feed de 🔔 Notificaciones se renderiza desde la API (`GET /notifications?unread=true`) en
  cada `refresh()`; antes era un log de solo-escritura que el stream SSE iba acumulando en el
  DOM y **nunca se limpiaba**, así que "marcar leídas" bajaba el contador pero las notis seguían
  visibles. Ahora muestra solo las no leídas y al marcarlas queda "sin notificaciones sin leer".
- El backend ya marcaba bien (`POST /notifications/read` + filtro `unread`); el bug era de front.
- Test de navegador `test_mark_read_clears_notifications_feed` (mockea el endpoint para ser
  determinista). El contrato del backend sigue cubierto por `test_building_completion_notifies_and_mark_read`.

### 2026-06-22 — Diseño: asistente AI personal + grafo de dependencias (SDDs)
- **[SDD 1 — Grafo de dependencias](docs/sdd-dependency-graph.md)**: modelo data-driven
  (minerales→minas→edificios→unidades→tecnologías→efectos) con consultas deterministas
  (`prerequisites`, `mineral_sources`, `analyze`/blockers) y endpoint `GET /catalog/graph`. Es el
  *skill*/grounding del asistente; razona sin LLM (fallback) y sin depender de Redis.
- **[SDD 2 — Asistente AI personal](docs/sdd-ai-assistant.md)**: consejero por jugador que usa el
  grafo + el **mismo LLM que las NPC** (agnóstico, con fallback) para decirte *qué te falta y
  cómo conseguirlo* y sugerir acciones de un clic; incluye un **"hack" de emergencia** que otorga
  el faltante mínimo, acotado a **3/día** (contador lazy en `Player`, sin cron/Redis).
- ROADMAP actualizado: asistente AI + **i18n del juego (ES/EN)** (contenido/UI, no docs/SDDs).
- Solo documentación de diseño (sin código todavía); la implementación entrará con sus tests e2e.

### 2026-06-21 — NPCs: estrategia (taunts + rivalidad + few-shot)
- **Taunts in-character**: cuando una NPC ataca a un **humano** le manda una notificación con
  una frase de su raza (al despachar, y otra al ganar/perder). Data-driven: `taunts.{attack,
  win,lose}` por raza en `content/races.yaml`. No-op en humano→x y NPC↔NPC. Llega por el feed
  de notificaciones + SSE + sonido, sin tocar el front.
- **Rivalidad dinámica**: entre las bases que claramente puede vencer, la NPC (rule brain)
  prioriza al **humano con más score** (las NPC se coordinan contra el líder); si no hay
  humano batible, pega a la base más débil. El `state` del LLM ahora marca `enemies[].is_human`
  y el prompt instruye lo mismo.
- **Few-shot** en el prompt LLM (formato + prioridades) para decisiones más consistentes.
- Tests de servicio: taunt al humano atacado, y que el rule brain ataca al humano líder
  cuando hay varios batibles. Sin dependencias nuevas (Python + YAML).

### 2026-06-21 — Helm: LLM agnóstico del proveedor
- El chart ahora expone `llm.baseUrl` / `llm.model` / `llm.apiKey` / `llm.jsonMode` y los pasa
  como `LLM_*` a la API y al worker (la key vía Secret). Permite apuntar las NPC a cualquier
  endpoint OpenAI-compatible (OpenRouter, LiteLLM, Ollama, vLLM) **sin que el chart levante
  ningún LLM** — eso queda en tu infra. `openrouter.*` sigue como fallback/compat.
- `secret.yaml` crea el Secret si hay `llm.apiKey` y/o `openrouter.apiKey`. README +
  `values-local.example.yaml` actualizados. Verificado con `helm lint` + `helm template`.

### 2026-06-21 — NPCs LLM: proveedor agnóstico (OpenRouter/LiteLLM/Ollama) + JSON mode
- El cerebro LLM ahora habla con **cualquier endpoint OpenAI-compatible** vía `LLM_BASE_URL` /
  `LLM_MODEL` / `LLM_API_KEY` (con fallback a los `OPENROUTER_*` para no romper configs viejas).
  Permite apuntar a **Ollama** (modelo local/GPU), **LiteLLM** (router) o **vLLM** sin tocar código.
- `_openrouter_decide` → `_llm_decide`; usa propiedades resueltas `settings.llm_url/llm_model_name/llm_key`.
- **JSON mode**: pide `response_format=json_object` (`LLM_JSON_MODE=true`, default) → respuestas
  parse-safe; configurable por si el server no lo soporta.
- Log de arranque muestra el proveedor/modelo cuando `NPC_BRAIN=llm`.
- Tests de servicio: resolución de settings (LLM_* gana, fallback a OPENROUTER_*) y que
  `_llm_decide` postea al endpoint configurado con JSON mode (sin red). Docs (.env.example,
  CLAUDE.md, development.md) con recetas para OpenRouter/Ollama/LiteLLM.

### 2026-06-21 — Web: sonidos de eventos
- Beeps con WebAudio (sin archivos de audio) al llegar notificaciones por SSE; tono distinto
  por tipo (ataque/ reporte/ expedición). Toggle 🔊/🔇 en el header, preferencia persistida en
  `localStorage`; el `AudioContext` se crea/reanuda con el gesto del usuario.
- e2e de navegador: el toggle cambia el ícono, persiste la preferencia y expone `playBeep`.

### 2026-06-21 — Eventos del mundo
- Nuevo endpoint `GET /api/v1/world/events`: feed público de la galaxia (batallas resueltas
  con nombres + resultado, y alianzas formadas), ordenado del más nuevo al más viejo. Sin
  modelo nuevo: se deriva de `CombatLog` + `Alliance` (servicio `app/services/world.py`).
- Web: tarjeta **🌍 Eventos del mundo** en la columna derecha, refrescada cada 4s.
- e2e: el feed muestra la alianza formada y la batalla (ambos jugadores + tipos battle/alliance)
  + caso de error (sin auth → 401) + test de navegador. Screenshot `09-world.png`.

### 2026-06-21 — Chat de alianza
- Nuevo modelo `AllianceMessage` (+ migración) y servicio `post_message`/`list_messages`
  (solo miembros). Endpoints `POST /api/v1/alliances/messages` y `GET .../messages`
  (declarados antes de `/{alliance_id}` para no chocar con el path param).
- Web: tarjeta **💬 Chat de alianza** (aparece al estar en una alianza); feed con autoscroll,
  marca tus mensajes "(vos)", input que sobrevive al refresh de 4s (card propia).
- e2e: chat entre dos miembros (orden viejos→nuevos, resuelve `sender_username`) + caso de
  error (sin alianza no podés leer ni postear) + test de navegador. Screenshot `08-chat.png`.

### 2026-06-21 — Web: detalle de planeta (modal)
- Click en un planeta del mapa → modal con **abundancia mineral** (barras por mineral, ricos en
  verde / pobres en ámbar, con el multiplicador de minas), **lunas** y **colonias** del planeta
  (con acceso directo a "⚔ atacar" enemigos). Cierra con ✕ o Escape. Todo data-driven desde
  `catalog` (sin backend nuevo).
- e2e de navegador: abre el detalle de la Tierra y verifica abundancia/lunas/colonias y el
  cierre. Screenshot `07-planet.png`.
- Fix CSS: `.modal.hidden` para que el overlay oculto no tape la pantalla (bloqueaba clicks).

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
