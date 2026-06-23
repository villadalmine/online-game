# Roadmap

Dónde estamos y qué sigue. El detalle cronológico de cada cambio está en
[`CHANGELOG.md`](CHANGELOG.md).

## ✅ Hecho (jugable hoy)

**Núcleo**
- API-first (FastAPI), web + CLI consumiendo la misma API.
- Contenido 100% data-driven en `content/*.yaml` (minerales, planetas, razas, edificios,
  unidades, lunas/dioses, tecnologías, tipos de alianza).
- Estado *lazy* por timestamp; **tick del mundo** automático (`AUTO_TICK_SECONDS`) + `/admin/tick`.
- DB SQLite (local) / Postgres (Docker); **migra sola al arrancar** (Alembic), sin reset manual.

**Juego**
- Onboarding: galaxia → planeta → raza. 2 galaxias (Vía Láctea + Andrómeda), 5 planetas, 3 razas.
- Economía: energía horaria, minas que producen por timestamp, recursos por raza.
- Construcción de edificios y entrenamiento de unidades (con colas/temporizadores).
- **Combate con viaje**: flotas que viajan, resuelven al llegar y vuelven con sobrevivientes+botín;
  **recall**; torretas/defensa de base; defensa mutua de alianza.
- **Expediciones** a lunas → recursos premium + boons de dioses.
- **Investigación/tecnologías** (bonus permanentes prod/ataque/defensa).
- **Alianzas** con tipos data-driven (no-agresión / defensiva / plena) y beneficios:
  bonus compartido, tech de unidades por raza, defensa mutua, visión compartida, comercio.
- **Ranking** de jugadores y de alianzas.
- **NPCs con IA**: cerebro por reglas (default) o LLM (OpenRouter) con personalidad + memoria;
  tácticos (recall/torretas, atacan al más débil); forman su propia alianza.
- **Notificaciones** + **push en tiempo real (SSE)**.

**Cliente web**
- Jugable: mapa de la galaxia, imperio (energía/minerales/unidades), bases, colas con barras,
  alianzas (tipos/beneficios/comercio/visión), investigación, ranking, guía in-game, costos y
  avisos de "te falta", pill de DB en uso.

**Infra / calidad**
- Redis (cache de catálogo + rate-limit de ataques), con degradación si no está.
- Makefile con 3 modos: `run` (full-local) · `run-lan` · `up`+`tunnel` (online).
- Docker (compose) y k8s (Helm). Repo público + `LICENSE` (MIT) + `CLAUDE.md`.
- Tests: unit + integración + **e2e HTTP** + **e2e de navegador (Playwright)** con screenshots.

## 🔜 Próximo (mañana seguimos)

1. **Asistente AI personal** — consejero por jugador que entiende el grafo de dependencias del
   juego y te dice *qué te falta / cómo conseguirlo*, con un **"hack" de emergencia** (te
   consigue el material faltante, máx **3/día**). Usa el mismo LLM que las NPC (agnóstico, con
   fallback). Diseñado en dos SDDs:
   [grafo de dependencias](docs/sdd-dependency-graph.md) +
   [asistente](docs/sdd-ai-assistant.md).
   - ✅ **SDD 1 hecho**: `depgraph.py` (grafo + análisis de bloqueos) y **RAG** (`graph_documents`
     + `retrieve` léxico ES/EN), expuesto full-API (`/catalog/graph`, `/graph/docs`,
     `/graph/search`). Con tests unit + e2e.
   - ✅ **SDD 2 hecho**: `advisor.py` + `llm.py` (transporte LLM compartido), endpoints
     `/players/me/advisor/{ask,hack,messages}`, modelo `AdvisorMessage`, hack 3/día (reset lazy),
     card "🧠 Asistente AI" en la web. Con tests servicio + e2e + browser.
2. ✅ **i18n del juego (ES/EN)** — contenido de `content/*.yaml` con `*_en` (ES default),
   `GET /catalog?lang=` + `Accept-Language`, toggle 🌐 en la web (persistido) que traduce
   contenido + chrome. [SDD](docs/sdd-i18n.md) + tests unit/e2e/browser. *(Follow-up: texto
   dinámico del server —notis/combate/asistente— y resto del chrome fijo.)*
3. ✅ **Paneles de la web colapsables** — cada card se pliega a su título (clic en la cabecera),
   estado persistido en `localStorage`, botones plegar/expandir todo. Front-only.
   [SDD](docs/sdd-web-panels.md) + test de navegador. *(Follow-up: columnas redimensionables /
   reordenar por drag-and-drop — requiere su propio SDD.)*
4. **Bot de Telegram** — otro cliente sobre la misma API (jugar y recibir notificaciones desde
   Telegram). Cierra la premisa multi-cliente. 📝 **[SDD listo](docs/sdd-telegram-bot.md)** (sin
   deps: long-poll con `httpx`, opt-in por token). ⛔ **Implementación bloqueada**: necesita un
   `TELEGRAM_BOT_TOKEN` real (de @BotFather) para verificar el smoke end-to-end.
5. 🟢 **Login para producción (email + código OTP)** — **hecho**: passwordless `request-code`/
   `verify-code` (signup=login, JWT mantiene sesión), HMAC+TTL+intentos+constant-time, mailer
   agnóstico sin deps (console/SMTP/Resend), i18n del email; el login usuario+contraseña sigue para
   dev. [SDD](docs/sdd-auth-login.md) + tests servicio/e2e/browser. Follow-up: rate-limit por IP +
   entrega real de email + `OTP_SECRET` fuerte en deploy.
6. **Deploy online real** — exponer para jugar a distancia (tunnel/cloud) con Postgres + secreto fuerte.
   Dominio en `gateway.host`; TLS público con cert-manager + Gateway API (`deploy/gateway-tls/`:
   ClusterIssuer Let's Encrypt + listener HTTPS en el Gateway). Falta: ClusterIssuer aplicado
   (DNS-01 detrás de NAT, o HTTP-01 si el :80 llega al Gateway), `JWT_SECRET`/`OTP_SECRET` fuertes
   + mailer real.
7. 🟢 **[SDD 14 — Alta moderada](docs/sdd-admin-approval.md)**: **v1 hecho (variante simple)** —
   allowlist `ALLOWED_EMAILS` (env) gatea `/auth/request-code`, passwordless, sin claves que
   repartir. Emails reales fuera del repo (`.env`/`values-local.yaml`). v2 (opcional): panel de
   admin + aprobación `pending` + `is_admin`/gate de `/admin/*` + 2FA para remoto.

### 🧭 Orden de implementación recomendado (de los SDDs en cola)
1. **SDD 11 → 8 → 12** juntos: comparten el modelo de **ronda/instancia/temporada** (lifecycle +
   galaxy instances + métricas/HoF públicas). Es el combo de mayor impacto jugable.
2. **SDD 13** en paralelo, **incremental y data-only**: empezar por el **Sistema Solar real** y
   sumar exosistemas / `speculative` / spin-offs cuando se quiera (no bloquea nada).
3. ✅ **SDD 7 + 9 hechos (v1)**: escalado/autoscaling (HPA/PDB/pool/SSE) + LLM local en GPU
   (timeout/rate-limit + ejemplos Ollama/LiteLLM). Falta calibrar con load test/benchmark reales.
4. **SDD 5 (Telegram)**: cuando haya `TELEGRAM_BOT_TOKEN`. **Follow-ups SDD 6/10** + **deploy**:
   atados a publicar (secretos fuertes, email real, backup offsite/PITR, target de hosting).

### Diseño de juego (diseñado, pendiente de implementar)
- 🟢 **[SDD 11 — Inicio y final del juego](docs/sdd-game-lifecycle.md)**: **v1 hecho** — mundo
  persistente + **temporadas** (abre/cierra en el tick, **Hall of Fame** persistente, sin wipe) +
  **newbie protection** (escudo al empezar; atacar a un humano lo cancela). API `/seasons*` +
  card "📅 Temporada". Follow-up: `SeasonScore` acumulable, evento de cierre, ligar a galaxy
  instances (SDD 8). Monetización fuera de alcance.
- 🟢 **[SDD 12 — Métricas + historial + showcase público](docs/sdd-player-metrics-public.md)**:
  **v1 hecho** — `PlayerStats` de por vida (batallas/construido/entrenado/explorado/minado/saqueado),
  historial de temporadas (HoF), endpoints públicos `/public/*` (sin auth, sin email) y **showcase
  en el login**. Follow-up: cachear `/public/*` (SDD 7), `career_points`, backfill.
- 🟢 **[SDD 13 — Rigor científico del contenido](docs/sdd-scientific-accuracy.md)**: **v1 hecho** —
  propiedades físicas reales por planeta (gravedad/atmósfera/agua/insolación/temperatura + `canon` +
  `sources`, NASA Fact Sheets) en el catálogo + modal de planeta; **restricciones físicas** (aviones
  requieren atmósfera, barcos requieren agua). Follow-up: jerarquía **sistema estelar** + exosistemas
  reales (Proxima/TRAPPIST-1), nivel `speculative`, **universos/spin-offs** (tipo *The Expanse*),
  multiplicadores físicos.

### Escalado / producción (diseñado, pendiente de implementar)
- 🟢 **[SDD 7 — Capacidad y autoscaling](docs/sdd-capacity-autoscaling.md)**: **v1 hecho** —
  pool de DB tuneable + SSE configurable (app); HPA/PDB/`topologySpreadConstraints`/resources en
  el Helm (opt-in `autoscaling.enabled`); load test `tests/load/k6_ccu.js`. Follow-up: métrica
  rps/pod (KEDA), PgBouncer + réplicas de lectura, tick shardeado por galaxia (SDD 8).
- 🟢 **[SDD 8 — Límites de galaxia](docs/sdd-galaxy-limits.md)**: **v1 hecho** — `GalaxyInstance`
  con `capacity` (overflow a nueva instancia); aislamiento humano↔humano (no atacás otra galaxia,
  scoreboard filtrado), NPCs ambientales, `GET /galaxies`. Follow-up: NPCs/ranking/temporada por
  instancia y tick por shard.
- 🟢 **[SDD 9 — LLM local en GPU](docs/sdd-local-gpu-llm.md)**: **v1 hecho** — timeout del LLM
  configurable + rate-limit del asistente (app); ejemplos `deploy/gpu-llm/` (Ollama en GPU +
  LiteLLM proxy con cola/fallback, fuera del chart). Follow-up: benchmark real de tok/s por
  modelo en P4/Maxwell + prueba de saturación.
- 🟢 **[SDD 10 — Durabilidad / backup / restore](docs/sdd-durability-backup-restore.md)**:
  **hecho lo crítico** — Postgres es `StatefulSet`+PVC (pod muere ≠ pérdida), soporte de DB externa
  (managed/operador), backup `pg_dump` opt-in. Follow-up: backup offsite cifrado + PITR + runbook/
  drill de restore. La app ya era crash-safe (stateless + estado lazy + tx atómicas).

(✅ NPCs LLM mejorados: proveedor agnóstico OpenAI-compatible en app + Helm — OpenRouter/
LiteLLM/Ollama/vLLM —, JSON mode, few-shot, taunts in-character y rivalidad coordinada
contra el humano líder.)

## 💡 Backlog / ideas

- Tech `build_speed` (acelerar construcción/entrenamiento) — ya hay framework de efectos.
- Combate que use `hp` de unidades; daño por rondas.
- Chat / mensajes de alianza; eventos del mundo; misiones.
- Más galaxias/planetas y minerales premium con usos reales (He-3, hielo).
- (✅ Web pulida: naves viajando, mapa por galaxia, detalle de planeta, chat de alianza,
  eventos del mundo, sonidos.)

## ⚠️ Deuda técnica

- `JWT_SECRET` fuerte en prod (PyJWT avisa con el default corto).
- Redis **locks** distribuidos para acciones mutantes (hoy hay cache + rate-limit).
- Web sin test de navegador para *todos* los flujos (cubrimos los principales).
