# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Comandos

```bash
make install          # crea .venv e instala (app + dev)
make run              # server full-local (SQLite) en http://localhost:8099/
make run-lan          # accesible en la LAN (0.0.0.0); imprime tu IP
make up / make down   # stack en Docker (Postgres + Redis + API + worker)
make demo             # levanta server efímero y corre un flujo completo por CLI
make test             # toda la suite (unit + integración + e2e)
make lint / make fmt  # ruff check / ruff --fix
make migration m="x"  # autogenera una migración Alembic tras cambiar modelos
make db-reset         # borra la DB SQLite local (solo si querés empezar de cero)
make help             # lista todos los targets
```

- Correr un test: `.venv/bin/python -m pytest tests/test_combat.py -q` (o `... -k nombre`).
- El cliente web se sirve en `/`; el CLI es `.venv/bin/ogame-cli` (usá `API_URL` para el puerto).
- Modelo/LLM de NPCs: `NPC_BRAIN=rules` (default) o `llm`. El brain LLM habla con cualquier
  endpoint **OpenAI-compatible** (OpenRouter, LiteLLM, Ollama, vLLM) vía `LLM_BASE_URL`/
  `LLM_MODEL`/`LLM_API_KEY` (si no, cae a los `OPENROUTER_*`). Siempre con fallback a reglas.

## Principios (no romper)

- **API-first**: toda la lógica vive detrás de `/api/v1`. Web, CLI y futuros clientes
  (Telegram) son consumidores delgados — no metas reglas de juego en el front.
- **Data-driven**: el contenido del juego está en `content/*.yaml` (minerales, planetas,
  razas, edificios, unidades, dioses/lunas, tecnologías, tipos de alianza). Rebalancear o
  extender = editar YAML, no código.
- **i18n del contenido**: `name`/`description`/`real` son ES (default); agregá `name_en`/
  `description_en`/`real_en` para inglés (cae al ES si falta). El catálogo se localiza con
  `GET /catalog?lang=` (`registry.localize*`). Agregar un idioma = editar YAML.
- **Extender, no romper**: cambios aditivos; API versionada.
- **Regla del proyecto: toda feature entra con su test e2e** en `tests/test_api_e2e.py`
  (happy path + al menos un caso de error), además de tests de servicio.
- **Regla estricta de documentación**: SIEMPRE que implementes un cambio o feature, DEBES documentarlo:
  1. Registrá la novedad en `CHANGELOG.md` siguiendo el formato de release.
  2. Actualizá el estado en el `ROADMAP.md` (o backlog) si corresponde.
  3. Creá o modificá un **SDD** (Software Design Document) en `docs/` detallando el diseño técnico de la feature.

## Arquitectura (big picture)

Capas: **datos** (`content/*.yaml` + `app/content/registry.py`) → **servicios**
(`app/services/`, toda la lógica) → **HTTP** (`app/api/v1/`, routers delgados). Modelos en
`app/models/` (SQLAlchemy async), contratos en `app/schemas/` (Pydantic).

Conceptos centrales:

- **Estado lazy por timestamp**: energía y producción no usan crons; se calculan desde
  `*_updated_at` al leer. `app/services/state.py:advance()` es el "advance on access" que
  finaliza colas (build/train/research/expedición), resuelve misiones y aplica regen en cada
  lectura de `/players/me`.
- **Tick del mundo**: `app/worker.py:run_tick()` avanza a todos y corre los turnos de las
  NPC. Se dispara solo con `AUTO_TICK_SECONDS` (loop en el lifespan) y por `POST /admin/tick`.
  En k8s lo hace un CronJob. Drivable sobre una sesión → testeable por HTTP.
- **Multiplicadores apilables**: `app/services/effects.py:multiplier(player, effect)` combina
  boons de dioses + tecnologías investigadas + beneficios de alianza para
  `production|attack|defense`. Economía y combate lo usan, así todo apila consistente.
- **Combate con viaje**: `start_attack` despacha una `AttackMission` (bloquea unidades);
  `process_missions` resuelve al llegar y devuelve sobrevivientes+botín. `resolve_combat()`
  es puro/determinista.
- **NPCs**: `app/services/npc.py` con cerebro enchufable (`RuleBasedBrain` determinista por
  defecto; `LlmBrain` sobre cualquier server OpenAI-compatible con fallback a reglas). Las NPC
  comparten una alianza.

## Base de datos / migraciones

- Dev usa **SQLite** (archivo `game.db`, ignorado por git); prod usa **Postgres**. La URL
  sale de `DATABASE_URL`.
- **Las migraciones se aplican solas al arrancar** (`run_migrations()` en el lifespan): tras
  cambiar modelos, generá la migración con `make migration m="..."` y el server la aplica —
  **no hace falta `make db-reset`** y no se pierde data.
- Al editar migraciones SQLite: columnas `NOT NULL` nuevas necesitan `server_default`; las
  FKs en `batch_alter_table` necesitan nombre (ver `migrations/versions/`). Hay un test
  (`tests/test_migrations.py`) que falla si una migración no crea todas las tablas del modelo.

## Más docs

`README.md` (modos de juego), `docs/development.md` (cómo extender: recetas por feature),
`docs/architecture.md`, `docs/game-design.md`, y `CHANGELOG.md` (bitácora por fecha).
