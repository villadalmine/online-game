# Changelog

Registro de todo lo que vamos logrando. Formato basado en
[Keep a Changelog](https://keepachangelog.com/). Fechas en formato AAAA-MM-DD.

> Regla del proyecto: **toda feature entra con su test e2e** (`tests/test_api_e2e.py`).

## [Unreleased]

### 2026-06-24 — Deuda técnica de prod: secretos fuertes + locks distribuidos
- **Secretos fuertes en prod**: `Settings.weak_secrets()` detecta `JWT_SECRET`/`OTP_SECRET`
  default o cortos (<16 bytes); con `ENVIRONMENT=production` el **arranque aborta** si hay alguno
  débil (el pod no levanta → obliga a setear uno real); en dev solo avisa. OTP solo se exige cuando
  el login passwordless está activo (allowlist o mailer real). Tests `tests/test_secrets_guard.py`.
- **Locks distribuidos por jugador** (Redis): `player_lock()` (SET NX PX + release con check de token;
  degrada a no-op sin Redis o si Redis falla) + dependency `lock_current_player` aplicada a las
  acciones que gastan recursos (build/train/research/expedición/ataque/recall) → **serializa** los
  requests concurrentes del mismo jugador y evita doble-gasto; en contención devuelve **409**. Tests
  unit (`test_redis.py`) + e2e (409 con Redis simulado). **205 verdes.**

### 2026-06-24 — SDD 26 diseñado: universos spin-off (Star Trek / BSG / Star Wars)
- Doc `docs/sdd-spinoff-universes.md`: packs de datos **tipados** (mismo modelo de objetos del
  contenido) con mundos/naves/materiales **fieles al canon** de cada franquicia (`canon: fiction` +
  `universe` + `sources` de wikis). **Solo especificación** (es la fuente; se edita el SDD para
  cambiar datos; se implementa cuando se decida). Incluye **nota legal/IP** (fan/no-comercial; modo
  genérico recomendado para publicar). Selección de universo por galaxy instance/temporada (SDD 8/11/13).

## [1.5.0] - 2026-06-24

### 2026-06-24 — SDD 25 v1: catch-up del recién llegado (nivelar sin dar ventaja)
- `app/services/catchup.py` (hook en onboarding): a quien entra a una partida con ≥3 pares en su
  galaxia, lo lleva al **P40 del stock de minerales** de los pares (top-up, nunca por encima →
  sin ventaja), le da **energía full** y asegura **mina + torreta** (defensa; nada ofensivo).
  Config `catchup_*`. Tests `tests/test_catchup.py` (P40 < mediana, partida joven no aplica). **195 verdes.**

## [1.4.0] - 2026-06-24

### 2026-06-24 — SDD 13 v2: jerarquía `system` + exosistemas reales + nivel `speculative`
- `content/planets.yaml`: campo **`system`** por planeta (Sistema Solar / sistemas de Andrómeda),
  nueva región **`solar_neighborhood`** (`canon: real`) con **Proxima Centauri b** y **TRAPPIST-1e**
  (datos publicados + `sources` + `confidence: low`), y un planeta **`speculative`** (`nova_terra` +
  `rationale`). Aditivo (no se removió nada → no rompe jugadores existentes).
- `registry`: `system`/`rationale` se localizan (ES/EN). Modal de planeta muestra system/canon/
  confidence/rationale. Tests `tests/test_science.py`.

### 2026-06-24 — SDD 25 diseñado: catch-up del recién llegado (nivelar sin dar ventaja)
- Doc `docs/sdd-newcomer-catchup.md`: al entrar a una partida vieja, grant proporcional a días +
  baseline de pares (P40 de su galaxia, leyendo `PlayerStats`/score), **priorizando defensa**,
  capeado a ≤ baseline (equalizar, no boostear). Una vez por cuenta. En la cola.

## [1.3.0] - 2026-06-24

### 2026-06-24 — SDD 24: landing pública /game (bilingüe, social-share)
- `web/landing.html` (ES/EN, toggle 🌐) servida en **`GET /game`**: hero + features + modelo
  **Free / BYOD (open source, self-host + tu API key de LLM) / Paid (nada por ahora)** + CTA a jugar.
- **Open Graph / Twitter cards** con `PUBLIC_URL` inyectada (og:url/og:image absolutas) →
  `GET /og-image.png` (1200×630, generado con Playwright vía `scripts/capture_og.py`).
- Tests e2e (`/game` bilingüe + OG, `/og-image.png` png). config `public_url`.

### 2026-06-24 — SDD 23: `make release V=X.Y.Z` (corte de release con una sola fuente del número)
- `scripts/release.py` + target `make release`: valida SemVer + tree limpio, mueve el CHANGELOG
  `[Unreleased]`→`[X.Y.Z]`, setea `Chart.appVersion` + tag del build manifest, commit + `git tag`.
  `DRY=1` para dry-run; no hace push. Tests `tests/test_release.py` (5). **188 verdes.**

### 2026-06-24 — SDD 23 diseñado: estrategia de versionado (SemVer) + releases
- Doc `docs/sdd-versioning.md`: MAJOR.MINOR.PATCH, **versión por release (no por commit)**, los
  cambios de **solo env/config (allowlist) NO llevan versión ni rebuild**, tag de imagen = release,
  `git tag vX.Y.Z`, y flujo CHANGELOG[Unreleased]→[X.Y.Z]. Follow-up: `make release V=`. (Motivado
  por la ráfaga 0.2.0→1.2.3.)

### 2026-06-24 — fix(deps): aiosqlite en runtime (lo necesita el smoke --selftest)
- El smoke (SDD 22 capa 2) levanta la app en SQLite efímero → necesita `aiosqlite`, que estaba
  solo en `[dev]`. Agregado a las deps principales (es el driver default de dev; inofensivo en prod
  con Postgres). 2do falso positivo del gate, ya cubierto.

### 2026-06-24 — fix(packaging): `pip install .` instalaba un paquete incompleto (faltaba app.api)
- `pyproject` listaba `packages=["app","clients"]` (solo top-level) → la instalación no traía los
  subpaquetes (`app.api`, `app.services`, …). El runtime no lo notaba (corre desde el fuente), pero
  **rompió el initContainer smoke** (capa 2 de SDD 22) con `ModuleNotFoundError: app.api`. Fix:
  `[tool.setuptools.packages.find] include=["app*","clients*"]`. Además `scripts/smoke.py` ahora
  fuerza el fuente al `sys.path` (como uvicorn). **El gate capa 2 hizo su trabajo: frenó el rollout
  y el pod viejo siguió sirviendo (sin downtime)** — fue un falso positivo por este bug de packaging.

### 2026-06-24 — SDD 22 capa 2: initContainer smoke (gate de rollout) + doc completa
- **initContainer `smoke`** (opt-in `api.smokeInit.enabled`): corre `scripts/smoke.py --selftest`
  (app en SQLite efímero, sin tocar Postgres/Redis) **antes de migrar/servir**; si falla, el pod no
  arranca → el rollout queda frenado y los pods viejos siguen. Cierra la capa 2 del SDD 22.
- **SDD 22 documentado** a fondo: flujo build→upgrade→test, qué hace/qué NO, y la prueba real (el
  build de 1.2.0 se cortó por un test rojo y no publicó imagen). Capas 1+2+3 implementadas.

### 2026-06-24 — SDD 22 capa 1: gate de tests en el build (Dockerfile multi-stage)
- El `deploy/Dockerfile` ahora es **multi-stage** con un stage `test` que corre `pytest -q`
  (unit/e2e, browser excluido) **durante el build**; el `runtime` depende de él (`COPY --from=test`).
  → un build con tests rojos **falla y NO produce imagen** (Kaniko/docker, sin tocar el Workflow).
  Cierra la capa 1 del SDD 22 (no publicar una versión que no pasa la suite). Runtime queda lean.

### 2026-06-24 — SDD 22: tests del deploy (helm test + smoke) + i18n de errores (SDD 4)
- **i18n errores**: handler global traduce el `detail` de errores conocidos (auth/seguridad) a EN
  con `?lang=en`/`Accept-Language` (`app/core/i18n_errors.py`); la web manda `lang` en
  register/login/verify. Test `test_error_message_i18n_en`.
- **SDD 22 — tests del deploy** (`docs/sdd-deploy-testing.md`): 3 capas (CI/build, initContainer
  smoke, `helm test`). v1: `scripts/smoke.py` (health/catalog/register/me; `--selftest` levanta la
  app en SQLite) + `COPY scripts` en el Dockerfile + **`helm test`** hook
  (`templates/tests/smoke.yaml`) → `helm test galaxy`. Recomendado `helm upgrade --atomic` (rollback
  auto). Tests `tests/test_smoke_script.py`. **183 verdes.**
- Follow-up: step de pytest previo al build (Kaniko) + initContainer smoke opt-in + `--atomic` en el runbook.

### 2026-06-24 — i18n del server: notificaciones en EN (SDD 4)
- `GET /notifications?lang=en` (o `Accept-Language`) **re-renderiza** el mensaje desde `type`+`data`
  (`notifications.localize`): building/training/research/expedition/incoming_attack/battle/attacked/
  fleet_returned/season_end. Tipos sin data (npc_taunt/advisor_hack) o desconocidos → mensaje
  original. La web manda `lang` en `loadFeed`. Empty-state del feed también traducido (`tr('nofeed')`).
- Tests: `tests/test_notif_i18n.py` (3). **180 verdes.** Follow-up: errores (HTTPException) y el
  `outcome` de combate (códigos) si se quiere traducir también.

### 2026-06-24 — SDD 21 v1: presencia (quién está online) + métricas por usuario/galaxia
- **Presencia** (`app/services/presence.py`, Redis ZSET + fallback memoria): heartbeat en
  `/players/me`; `GET /public/online` (conteo) y `GET /admin/online` (lista de usernames, admin).
- **Métricas**: `game_online_players` + opt-in `game_player_online{player,galaxy}`
  (`metrics.perPlayer.enabled`, tope) → en Grafana filtrás por player/galaxy. Gauge con `clear()`
  para no dejar series stale.
- Tests: `tests/test_presence.py` (2) + e2e (`test_presence_online_endpoints`). **177 verdes.**
  El bot (hermes) ya puede preguntar `/admin/online` o PromQL `game_online_players`.

### 2026-06-24 — SDD 21 diseñado: presencia (quién está online) + métricas por usuario/galaxia
- Doc `docs/sdd-presence-dimensional-metrics.md`: presencia vía Redis (SSE + last-seen),
  `/public/online` (conteo) y `/admin/online` (lista, admin); label **`galaxy`** (seguro) y
  **`player`** (opt-in por cardinalidad) para filtrar en Grafana; cómo lo consulta el bot. En la cola.

### 2026-06-24 — i18n EN del cliente completo (SDD 4): toda la web traduce
- El toggle 🌐 ahora pasa a inglés **toda la UI del cliente**: pantalla de login/registro/OTP,
  onboarding, "tu imperio", tips, botones, y todos los strings generados en JS (alianzas, colas,
  mapa, ranking/temporada, planeta, chat, stream, estados vacíos, guía). Helper `tr()` + dict plano
  `s` (es/en) + `data-i18n-html`/`data-i18n-ph`; guía con array por idioma.
- Browser test `test_language_toggle_to_english` + **aislamiento del `.env`** en el server de los
  browser-tests (ALLOWED_EMAILS/ADMIN_EMAIL/MAIL_BACKEND por env) → herméticos. **16 browser verdes.**
- Pendiente (backend, aparte): texto **generado por el server** (notis/combate/errores) sigue en ES.

### 2026-06-23 — SDD 18 v1: GitHub Pages auto-generado desde los SDDs
- `scripts/build_site.py` (stdlib) genera `site/index.html` desde `docs/sdd-*.md` + CHANGELOG
  (features+estado+novedades+botón Jugar). **Guard de privacidad** que aborta si hay PII/secretos.
  `GAME_URL` por variable de repo (no hardcodeada). `.github/workflows/pages.yml` publica en cada
  push a main. Tests `tests/test_site.py` (4). **174 unit/e2e verdes.** Falta habilitar Pages
  (Settings → Pages → GitHub Actions) — 1 vez, manual.

### 2026-06-23 — SDD 19 v1.1: métricas de negocio + tick/LLM + dashboard Grafana
- **`game_events_total{kind}`** instrumentado en `stats.bump` (un solo punto) → cubre
  construcciones/entrenamientos/investigación/expediciones/ataques/batallas/minería/saqueo/pérdidas.
- **Tick**: `game_tick_duration_seconds` (histogram) + `game_tick_last_run_timestamp`.
- **LLM**: `game_llm_requests_total{status}` + `game_llm_latency_seconds` (en `llm_chat`).
- **Dashboard Grafana** (`deploy/helm/dashboards/online-game.json`) como ConfigMap opt-in
  (`metrics.grafanaDashboard.enabled`, label `grafana_dashboard` → sidecar de kube-prometheus-stack).
- Test `test_bump_increments_prometheus_events`. **170 unit/e2e verdes.**

### 2026-06-23 — SDD 19 v1: métricas Prometheus (/metrics) + ServiceMonitor
- **`/metrics`** (formato Prometheus, módulo stdlib `app/core/metrics.py`, sin deps): RED por ruta
  (path-template), `game_sse_connections` (conectados ahora), `game_players_total`,
  `game_signups_total{method}`, `game_logins_total{method}`. Middleware + instrumentación en
  auth/OTP/SSE.
- **No público**: `METRICS_TOKEN` (Secret) → `/metrics` exige Bearer; sin PII en labels (test).
- **Helm**: ServiceMonitor opt-in (`metrics.serviceMonitor.enabled`), Service con puerto `http`
  nombrado, `METRICS_TOKEN` por Secret. Para kube-prometheus-stack: label
  `release: kube-prometheus-stack`.
- Tests: `test_metrics_endpoint_and_no_pii`, `test_metrics_token_guard`. **169 unit/e2e verdes.**
- **Desplegado y verificado**: kube-prometheus-stack scrapea `galaxy-api` (`game_players_total`=6,
  RED, SSE). **PrometheusRule** opt-in con alertas (`OnlineGameSignup` → avisa altas vía
  Alertmanager→openclaw/Telegram, `OnlineGameApiDown`, `OnlineGameHighErrorRate`). PromQL para los
  bots en el SDD 19. (rev 18, imagen 0.6.0.)

### 2026-06-23 — Privacidad: nick neutro en alta OTP (no derivar del email) (SDD 20)
- El alta por OTP genera `comandante-<hex>` en vez de derivar el username del local-part del email
  (que lo exponía en el nombre público). `auth_otp._unique_username`. Test
  `test_otp_username_is_neutral_not_from_email`. **167 unit/e2e verdes.** Follow-up: endpoint de
  renombrado (requiere re-emitir el JWT). Incluye también el log INFO de envío de email (resend_id).

### 2026-06-23 — Seguridad: admin gate + rate-limit OTP + registro web por email; SDDs 20/usuarios
- **Gate de `/admin/*` (SDD 14 v2)**: `get_current_admin` (`Player.is_admin` + `ADMIN_EMAIL`).
  Antes `tick`/`season/close` los llamaba cualquier logueado. Migración aditiva `is_admin`
  (`server_default`). Sin `ADMIN_EMAIL` (dev/test) queda abierto como antes. e2e
  `test_admin_endpoints_gated`.
- **Rate-limit por IP en `/auth/request-code`** (`otp_rate_limit_per_min`, 429): defensa anti-abuso
  del endpoint (el envío ya estaba acotado por allowlist+cooldown). e2e `test_otp_request_rate_limited`.
- **Web alineada con la allowlist**: el form de registro ahora manda **email** (antes daba 403 al
  gatear register por email). `register()` envía email; login sigue user+pass. `is_admin` se siembra
  desde `ADMIN_EMAIL` al crear la cuenta (register + OTP).
- **SDD 20 — Usuarios** (`docs/sdd-users.md`): modelo `Player`, campos, e identidad **nickname
  público / email privado**. **SDD 10 ampliado**: estrategia de **Redis** (cache, no requiere
  backup) + runbook de recuperación. **Backlog**: i18n EN incompleto + nickname OTP no derivar del email.
- **166 unit/e2e verdes.**

### 2026-06-23 — Deploy: mailer Resend + OTP_SECRET vía Secret (entrega real de códigos)
- El chart ahora wirea el **envío de email** (SDD 6/14): `mail.backend`/`mail.from` (env) +
  `mail.resendApiKey`/`mail.otpSecret` **vía Secret** (`templates/secret.yaml` + `commonEnv`). Reusa
  el mismo proveedor que `bot-telegram` (**Resend**, dominio verificado). Cierra el blocker: antes
  `MAIL_BACKEND=console` no entregaba el código OTP. Ahora `request-code` envía de verdad.
- `OTP_SECRET` fuerte (no el default) por Secret. Datos reales en `values-local.yaml` (gitignored).

### 2026-06-23 — fix(seguridad): cerrar bypass de allowlist en /auth/register (SDD 14 v1.1)
- **Bug**: `/auth/register` (usuario+contraseña) NO respetaba la allowlist → cualquiera podía
  crear cuenta salteando el gate (solo el OTP estaba gateado). Detectado probando en vivo.
- **Fix**: register ahora exige `email` autorizado cuando hay allowlist (403 si falta/no está;
  201 si está). Da acceso a los permitidos **sin depender del mailer** (email+clave). Sin
  allowlist, registro abierto (dev) como antes.
- Tests (regla e2e que faltaba aplicar): `test_register_gated_by_allowlist` +
  `test_register_open_without_allowlist`. **164 unit/e2e verdes.**

### 2026-06-23 — SDD 19 diseñado: métricas Prometheus + dashboard Grafana
- Doc `docs/sdd-observability-metrics.md` (propuesto): `/metrics` (stdlib, sin dep) con RED de la
  API + métricas de negocio (construcciones/entrenamientos/investigación/expediciones/combate/altas/
  asistente), conectados en vivo (gauge de conexiones SSE), tick, LLM e infra. ServiceMonitor +
  dashboard Grafana versionado. Guard de cardinalidad/privacidad; `/metrics` no público. En la cola.

### 2026-06-23 — SDD 18 diseñado: GitHub Pages auto-generado desde los SDDs
- Doc `docs/sdd-github-pages.md` (propuesto, sin código aún): landing del juego en GitHub Pages
  generada por un script stdlib que lee `docs/sdd-*.md` + ROADMAP + CHANGELOG (auto-actualizable en
  cada push a `main` vía Action). URL del juego por variable de repo (no hardcodeada); guard de
  privacidad sobre el HTML. En la cola.

### 2026-06-23 — 🚀 Publicado: build Kaniko + upgrade + migraciones (SDD 15/16/17)
- **El juego está LIVE** detrás del dominio público con TLS Let's Encrypt **prod** válido, login
  OTP + allowlist (SDD 14) y asistente AI (OpenRouter free). Release `galaxy`, ns `online-game`.
- **SDD 15 — build Kaniko/Argo** (`docs/sdd-image-build-kaniko.md` + `deploy/build/online-game-kaniko.yaml`):
  build in-cluster arm64 desde `git`, push al registry interno. Reproducible.
- **SDD 16 — migraciones en deploy** (`docs/sdd-migrations-deploy.md`): el initContainer `migrate`
  corre `alembic upgrade head` antes de servir; aditivo e idempotente (no-op si no hay cambios),
  datos intactos (PVC, SDD 10). Guía expand/contract + rollback.
- **SDD 17 — runbook de upgrade** (`docs/sdd-deploy-upgrade.md`): build → `helm upgrade
  --set image.tag` → migraciones → smoke. Casos: cambió esquema / solo env / flip cert / allowlist.

### 2026-06-23 — Deploy: bootstrap reproducible del secret acme-dns (cert DNS-01)
- `deploy/gateway-tls/create-acme-dns-secret.sh` (idempotente, server-side apply) crea el secret
  `acme-dns-account` en `cert-manager` — el ÚNICO prerequisito que el chart no crea (un secret no
  va al repo en claro). `acme-dns-account.example.json` (placeholders, versionado) + el real
  `acme-dns-account.json` gitignored. Documentado en `deploy/gateway-tls/README.md` (proceso de
  emisión del cert). HAProxy/SNI-passthrough → VIP del LB del Gateway (sin IPs internas en el repo).

### 2026-06-23 — Deploy: chart con Gateway/Certificate/ClusterIssuer + values personales gitignored
- **Templates nuevos (genéricos, opt-in por values, aditivos):** `gateway.yaml` (Gateway dedicado
  cuando `gateway.create=true`, o reusar uno existente), `certificate.yaml` (Certificate público
  cuando `gateway.tls.enabled`), `clusterissuer.yaml` (Let's Encrypt staging+prod DNS-01/acme-dns
  cuando `letsencrypt.enabled`). No tocan `cluster-gateway` ni a otros tenants.
- **Privacidad (mismo concepto que `.env`):** los values con datos reales (dominio/IPs/email) van
  en `deploy/helm/values-*.yaml` **gitignored**; el repo solo lleva ejemplos genéricos con
  placeholders en `deploy/helm/examples/` (`remote.example.yaml`, perfiles local y remoto). El
  default de `values.yaml` quedó sin datos reales.
- Verificado: `helm lint` + `helm template` (default y ejemplo) OK.

### 2026-06-23 — SDD 14 v1: allowlist de altas (passwordless)
- Variante simple elegida: **`ALLOWED_EMAILS`** (env, lista por coma) gatea `/auth/request-code`
  — solo emails autorizados (o jugadores ya existentes) reciben código. Vacío = registro abierto.
  Salida uniforme (anti-enumeración); sigue passwordless (sin claves que repartir).
- `app/core/config.py` (`allowed_email_set`), `app/services/auth_otp.py` (gate). Emails reales en
  `.env`/`values-local.yaml` (gitignored), nunca en el repo.
- Tests: 3 servicio (`tests/test_auth_otp.py`) + 1 e2e + fixture autouse `_open_registration`.
  **162 unit/e2e verdes.** Doc `docs/sdd-admin-approval.md` (el panel/aprobación queda como v2).

### 2026-06-23 — Deploy: TLS público con cert-manager + Gateway API
- **Dónde va el dominio**: `gateway.host` del chart; el HTTPRoute liga por hostname al listener
  del Gateway. Comentario aclaratorio en `values.yaml`.
- **TLS (fuera del chart, en el Gateway compartido)**: `deploy/gateway-tls/` con ClusterIssuer
  Let's Encrypt (staging+prod, solver **DNS-01** por defecto — sirve detrás de NAT; HTTP-01 como
  alternativa), el listener HTTPS a agregar al Gateway (+ annotation
  `cert-manager.io/cluster-issuer` → el shim pide el cert solo) y README con pasos. Genérico/sin
  datos de infra. Nota de frente TCP/SNI-passthrough → backend a la VIP del LB del Gateway.

### 2026-06-23 — SDD 7 + SDD 9 implementados (v1): capacidad/autoscaling + LLM local en GPU
- **App (testeable):**
  - **Pool de DB tuneable** (SDD 7): `engine_kwargs()` aplica `pool_size`/`max_overflow`/
    `pool_timeout`/`pool_recycle`/`pool_pre_ping` en Postgres (SQLite intacto). El techo de
    conexiones es por réplica → de ahí PgBouncer a gran escala.
  - **Intervalo del SSE configurable** (SDD 7): `STREAM_INTERVAL` como default del stream;
    subirlo baja drásticamente la carga DB (el SSE pollea por conexión).
  - **Timeout del LLM configurable** (SDD 9): `LLM_TIMEOUT_SECONDS` (antes 20s fijo) corta la
    espera de la GPU serial y dispara el fallback (NPC→reglas, asistente→determinista).
  - **Rate-limit del asistente** (SDD 9): `/advisor/ask` limitado por jugador
    (`advisor_rate_limit_per_min`, 429 al pasarse) — protege la GPU del pico simultáneo.
- **Helm (SDD 7):** `api.resources`/`worker.resources` (requests/limits → el HPA necesita
  requests), **HPA** opt-in (`autoscaling.enabled`, CPU 70%, ignora `api.replicas`),
  **PodDisruptionBudget** opt-in, `topologySpreadConstraints`, y envs `STREAM_INTERVAL`/
  `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`/`LLM_TIMEOUT_SECONDS`. Verificado con `helm lint`/`template`.
- **Infra/ejemplos (SDD 9, fuera del chart):** `deploy/gpu-llm/` (Ollama en GPU + LiteLLM proxy
  con cola/fallback + README: topología, elección de modelo 3–4B/7B Q4, concurrencia serial).
- **Load test (SDD 7):** `tests/load/k6_ccu.js` + README con el modelo de cálculo de CCU
  (~0.8 rps/CCU) — no corre en CI.
- Tests: `tests/test_scaling.py` (4) + 1 e2e (rate-limit del asistente 429). **158 unit/e2e +
  15 browser verdes.**
- Follow-up: métrica custom rps/pod (KEDA), PgBouncer + réplicas de lectura, tick shardeado por
  galaxia (SDD 8), benchmark real de tok/s por modelo en P4/Maxwell.

### 2026-06-22 — SDD 13 implementado (v1): rigor científico del contenido
- **Propiedades físicas reales** por planeta en `content/planets.yaml` (`gravity_g`, `mean_temp_c`,
  `atmosphere`, `has_liquid_water`, `insolation`, `canon`, `sources` — NASA Fact Sheets). Sistema
  Solar = `real`; Andrómeda = `fiction`. Expuesto por `/catalog` y en el modal de planeta.
- **Restricciones físicas data-driven**: **aviones requieren atmósfera** (no en Mercurio) y
  **barcos requieren agua líquida** (solo Tierra) — gateado en `start_training`. `propulsion`
  descriptivo.
- Tests: `tests/test_science.py` (2) + 2 e2e. **153 unit/e2e + 15 browser verdes.**
- Follow-up: jerarquía sistema estelar + exosistemas reales (Proxima/TRAPPIST-1), nivel
  `speculative`, universos/spin-offs, multiplicadores físicos.

### 2026-06-22 — SDD 12 implementado (v1): métricas + historial + showcase público
- **`PlayerStats`** (contadores de por vida) incrementados en los procesadores existentes:
  batallas ganadas/perdidas, ataques, edificios, unidades, investigaciones, expediciones,
  minerales minados/saqueados/perdidos. Historial de temporadas desde el `HallOfFame` (SDD 11).
- **Endpoints públicos SIN auth** `/public/{stats,leaderboard,hall-of-fame,players/{username}}`:
  solo agregados + username (**nunca email**); perfil 404 si no existe.
- **Web**: showcase en la **página de login** (stats del universo + top-10), sin estar logueado.
- `app/services/stats.py` (`bump`/`leaderboard`/`global_stats`/`player_profile`). Migración aditiva.
- Tests: `tests/test_stats.py` (5) + 1 e2e (público/sin-email/404) + 1 browser. **149 unit/e2e +
  15 browser verdes.** Cierra el combo 11+8+12. Follow-up: cachear `/public/*` (SDD 7), backfill.

### 2026-06-22 — SDD 8 implementado (v1): límites de galaxia (shards con cupo)
- **`GalaxyInstance`** (shard con `capacity`) + `Player.galaxy_instance_id`. El onboarding asigna
  una instancia **abierta** del template elegido; al llenarse (`GALAXY_CAPACITY`, default 50) crea
  una nueva. Los **NPC son ambientales** (sin instancia, atacables desde cualquier shard).
- **Aislamiento humano↔humano**: no podés atacar a un jugador de **otra galaxia** y el scoreboard
  (`GET /players`) se **filtra a tu instancia** (+ NPCs). `GET /galaxies` lista instancias con cupo;
  `/players/me` expone `galaxy_instance`; el header de la web muestra tu galaxia.
- Backfill perezoso para cuentas legacy. Migración aditiva (FK nombrada para SQLite).
- Tests: `tests/test_galaxies.py` (5 servicio) + 2 e2e + 1 browser. **143 unit/e2e + 14 browser.**
- Follow-ups: NPCs por instancia, ranking/temporada por instancia, tick por shard (SDD 7).

### 2026-06-22 — SDD 11 implementado (v1): temporadas + Hall of Fame + newbie protection
- **Mundo persistente + temporadas**: modelo `Season` (abre/cierra en el tick), al cerrar toma
  foto del ranking → top-N al **`HallOfFame`** (persiste) y abre la siguiente; **el imperio no se
  borra**. Ranking de temporada **en vivo** por `player_score` (tabla `SeasonScore` acumulable =
  follow-up).
- **Newbie protection** (`Player.protected_until`): el onboarding te da escudo
  (`NEWBIE_PROTECTION_HOURS`, default 48 h); no se puede **atacar a un protegido**, y **atacar a un
  humano cancela tu propia protección** (opt-out); atacar NPCs no la afecta.
- **API**: `GET /seasons`, `/seasons/current/ranking`, `/seasons/hall-of-fame`,
  `POST /admin/season/close`; `/players/me` agrega `protected_until` + `season`.
- **Web**: card "📅 Temporada" (countdown + ranking + aviso de protección), i18n ES/EN.
- Config `SEASON_DAYS`/`SEASON_HALL_OF_FAME_TOP`/`NEWBIE_PROTECTION_HOURS`. Migración aditiva.
- Tests: `tests/test_seasons.py` (8 servicio) + 2 e2e + 1 browser; tests de combate existentes
  ajustados (la protección bloquea atacar novatos). **137 unit/e2e + 13 browser verdes.**

### ⏳ Pendiente de implementar (diseñado, con SDD) — al 2026-06-22
> Detalle y orden en [`ROADMAP.md`](ROADMAP.md). Cada uno entra con su test e2e + entrada acá.
- **SDD 11 — follow-ups**: `SeasonScore` acumulable, evento del mundo al cerrar, ligar temporada a
  galaxy instances (SDD 8). (v1 ya implementado.)
- **SDD 12 — follow-ups**: cachear `/public/*` en Redis, `career_points` all-time, backfill de
  contadores. (v1 ya implementado.)
- **SDD 13 — follow-ups**: jerarquía sistema estelar + exosistemas reales (Proxima/TRAPPIST-1),
  nivel `speculative`, universos/spin-offs, multiplicadores físicos. (v1 ya implementado.)
- **SDD 8 — follow-ups**: NPCs por instancia, ranking/temporada por instancia, tick por shard.
  (v1 ya implementado.)
- **SDD 7 — Capacidad y autoscaling** (`docs/sdd-capacity-autoscaling.md`): HPA + resource requests
  + PgBouncer; atacar `run_tick` O(N) y SSE.
- **SDD 9 — LLM local en GPU** (`docs/sdd-local-gpu-llm.md`): Ollama/LiteLLM en P4/Quadro,
  concurrencia serial + fallback, modelo local recomendado.
- **SDD 5 — Bot de Telegram** (`docs/sdd-telegram-bot.md`): ⛔ bloqueado, necesita `TELEGRAM_BOT_TOKEN` real.
- **SDD 10 — Durabilidad (follow-ups)**: backup offsite cifrado + PITR + runbook/drill de restore.
- **SDD 6 — Login (follow-ups)**: rate-limit por IP + entrega real de email + `OTP_SECRET` fuerte en deploy.
- **Deploy online real**: exponer (túnel/cloud) con Postgres + secretos fuertes (decisiones del usuario).
- **Backlog (sin SDD aún)**: tech `build_speed`, combate con `hp`/rondas, más galaxias/minerales premium.
- **Orden recomendado** (ver ROADMAP): **11 → 8 → 12** juntos (lifecycle + galaxy instances +
  métricas/público, comparten modelo); **13** en paralelo, incremental y data-only (empezar por el
  Sistema Solar real); **7 + 9** al armar el deploy; **5** cuando haya token; follow-ups 6/10 +
  deploy atados a publicar.

### 2026-06-22 — SDD 13 (diseño): rigor científico del contenido
- **[SDD 13](docs/sdd-scientific-accuracy.md)**: hacer científicamente correctos galaxias, planetas,
  lunas, materiales, instalaciones, naves y personal. Jerarquía real **Galaxia → sistema estelar →
  planeta → luna** (Sistema Solar real + sistemas reales de la Vía Láctea: Proxima Centauri,
  TRAPPIST-1 vía NASA Exoplanet Archive; se quitan los planetas ficticios de Andrómeda). Propiedades
  físicas (gravedad, atmósfera, agua, insolación, temperatura) con **fuentes citadas**;
  instalaciones/naves/unidades ancladas a tecnología/física reales (ISRU, fusión, propulsión) con
  restricciones (aviones solo con atmósfera, barcos solo con agua). Todo **data-driven**, aditivo.
  Incluye **niveles de canon** (`real`/`speculative`/`fiction`) para arrancar chico e ir inventando
  lo "aún no descubierto", y **universos/spin-offs** (tipo *The Expanse*) como packs de contenido
  seleccionables por partida — sin tocar código.
- En cola, solo diseño.

### 2026-06-22 — SDD 12 (diseño): métricas, historial de temporadas y showcase público
- **[SDD 12](docs/sdd-player-metrics-public.md)**: contadores de por vida por jugador
  (`PlayerStats`: batallas ganadas/perdidas, edificios, unidades, expediciones, minerales
  minados/gastados/saqueados…) incrementados en los procesadores existentes; **historial de
  temporadas** vía HoF (SDD 11); endpoints **públicos sin auth** `/public/{stats,leaderboard,
  hall-of-fame,players/{username}}` (solo agregados, sin email) y **showcase en la página de
  login** (leaderboard + stats del universo + perfiles). Cacheable (SDD 7). Depende del SDD 11.
- En cola, solo diseño.

### 2026-06-22 — SDD 11 (diseño): inicio y final del juego (mundo persistente + temporadas)
- Investigado StarKingdoms (rondas con inicio/fin, tick, newbie protection, ranking por networth,
  Hall of Fame persistente, free-to-play + Premium cosmético ~US$2.33/mes — no pay-to-win).
- Decisión del usuario: **híbrido** — mundo persistente + **temporadas** (clímax, ganadores,
  **Hall of Fame + insignias cosméticas** que persisten, **sin wipe** del imperio) + **newbie
  protection**. **Monetización: fuera de alcance por ahora.**
- **[SDD 11](docs/sdd-game-lifecycle.md)**: modelo `Season`/`SeasonScore`/`HallOfFame` +
  `Player.protected_until`, apertura/cierre de temporada en el tick, puntos de temporada (delta de
  score + bonus), endpoints `/seasons*`, e interacción con galaxy instances (SDD 8). Solo diseño.

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
