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
   Telegram). Cierra la premisa multi-cliente.
5. **Deploy online real** — exponer para jugar a distancia (tunnel/cloud) con Postgres + secreto fuerte.

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
