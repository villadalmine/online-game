# Guía de desarrollo

Cómo trabajar en el juego día a día: levantarlo, entender el flujo, y **extender sin romper**.

Lee también: [`game-design.md`](game-design.md) (qué es el juego) y
[`architecture.md`](architecture.md) (cómo está construido).

---

## 1. Setup y correr

```bash
# entorno (una sola vez)
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# server local con SQLite (sin Postgres/Redis)
.venv/bin/uvicorn app.main:app --reload            # http://localhost:8000
.venv/bin/uvicorn app.main:app --reload --port 8080  # si el 8000 está ocupado

# tests + lint
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff check --fix .                        # autofix
```

- `http://localhost:8000/docs` → OpenAPI interactivo (la forma más rápida de probar endpoints).
- `http://localhost:8000/health` → chequeo de vida.
- Empezar de cero: `rm game.db`.
- Postgres/Redis completos: `docker compose -f deploy/docker-compose.yml up --build`.

### Jugar por CLI

```bash
export API_URL=http://localhost:8000            # o el puerto que uses
.venv/bin/ogame-cli register alice secret123
.venv/bin/ogame-cli onboard milky_way mars martian
.venv/bin/ogame-cli me
.venv/bin/ogame-cli build 1 mine iron
```

---

## 2. Mapa del código (qué toca qué)

```
content/*.yaml          → DATOS del juego (sin código). El "diseño" vive acá.
app/content/registry.py → carga los YAML y resuelve roles→minerales. Fuente de reglas.
app/models/__init__.py  → tablas (SQLAlchemy): Player, Base_, Building, ResourceStock.
app/schemas/__init__.py → contratos de entrada/salida de la API (Pydantic).
app/services/           → LÓGICA del juego (no HTTP):
    energy.py           → regen de energía (funciones puras, testeables).
    production.py       → producción de minas (funciones puras).
    economy.py          → stocks, recolección de minas, finalizar colas.
    build.py            → construir: cobra energía+minerales, encola.
    training.py         → entrenar unidades: cobra energía+minerales, encola, entrega.
    onboarding.py       → elegir galaxia/planeta/raza, crear base inicial.
    state.py            → "advance on access" + snapshot del estado del jugador.
app/api/v1/             → ROUTERS HTTP (delgados; llaman a services).
app/api/deps.py         → autenticación (get_current_player).
app/main.py             → app FastAPI + arranque.
app/worker.py           → tick periódico (CronJob): cola, minas, y futuro combate/IA.
clients/cli/            → cliente de referencia (prueba que todo pasa por la API).
deploy/                 → Dockerfile, docker-compose, chart Helm.
tests/                  → unit (puras) + integración (sqlite en memoria).
```

**Regla de capas:** los routers (`api/v1`) son delgados y solo orquestan; toda la lógica
vive en `services/`; los datos del juego viven en `content/`. Nunca hardcodees reglas en
los routers ni en los modelos.

---

## 3. Flujo de una request (ejemplo: construir)

```
POST /api/v1/bases/{id}/build
  → app/api/v1/bases.py
      get_current_player (deps.py) valida el JWT
      busca la base, valida ownership
      llama services/build.py:start_build(...)
          finalize_due_builds + collect_mines  (pone la economía al día)
          spend_energy (services/energy.py)
          building_cost_in_minerals (registry.py)  ← resuelve rol→mineral por raza
          descuenta stocks, crea Building status="building" con completes_at
      commit → devuelve BuildingOut
```

El estado **avanza al leer/actuar** (lazy), no por un cron por usuario. Ver
`services/state.py:advance` (lo llama `GET /players/me`).

---

## 4. Cómo extender (recetas) — "no romper, extender"

La mayoría de los cambios de juego son **editar YAML**, sin tocar Python.

### 4.1 Agregar un mineral
`content/minerals.yaml` → agregá una entrada con `key`, `name`, `real`, `description`.
Luego dale abundancia en los planetas que lo tengan (`content/planets.yaml → abundance`).
Eso es todo: aparece en `/catalog` y se puede minar.

### 4.2 Agregar un planeta
`content/planets.yaml` → dentro de la galaxia, agregá un planeta con `key`, `name`,
`abundance` (por mineral) y `moons`. Si tiene luna nueva, agregala en `content/gods.yaml`.

### 4.3 Agregar una raza
`content/races.yaml` → `key`, `name`, `home_planet`, `description`, y lo importante:
`resource_roles` (mapea `structural`/`energetic`/`advanced` → un mineral) y `bonuses`.
**Cambiar qué mineral usa una raza = cambiar un valor en `resource_roles`.**

### 4.3b Agregar / ajustar una unidad
`content/units.yaml` → en `personnel` o `heavy`: `key`, `name`, `requires` (edificio que
debe estar activo para entrenarla), `energy_cost`, `train_seconds`, `cost` (en **roles**) y
`stats` (attack/defense/hp, para el combate futuro). El costo se resuelve a minerales por
raza automáticamente. No hace falta tocar Python.

### 4.3c Agregar / ajustar una luna y su dios
`content/gods.yaml` → `key`, `name`, `planet`, `god`, `expedition` (energy_cost,
duration_seconds, requires_unit), `grants` (recursos al volver) y `boon`
(`effect: production|attack|defense`, `magnitude`, `duration_seconds`). El boon se aplica
solo en los sistemas existentes (producción/combate). No hace falta tocar Python.

### 4.3d Agregar una tecnología
`content/technologies.yaml` → `key`, `name`, `requires` (edificio activo), `energy_cost`,
`research_seconds`, `cost` (roles) y `effect` (`production|attack|defense`) + `magnitude`.
El efecto se aplica solo vía `services/effects.py` (apila con boons). Sin tocar Python.

### 4.3e Ajustar alianzas (tipos y beneficios)
`content/alliances.yaml` → tipos con `benefits` (`shared_bonus`/`mutual_defense`/
`shared_vision`/`trade`/`shared_unit_tech`) y, si incluye `shared_bonus`, sus multiplicadores.
El `unit_perk` de cada raza (compartido por `shared_unit_tech`) está en `content/races.yaml`.
Los multiplicadores se aplican en `services/effects.py`; la defensa mutua y el comercio en
`services/alliances.py`. Sin tocar más Python.

### 4.4 Agregar un edificio
`content/buildings.yaml` → `key`, `name`, `category`, `energy_cost`, `build_seconds`,
y `cost` en **roles** (no minerales). El costo se traduce a minerales por raza
automáticamente (`registry.py:building_cost_in_minerals`).
- Si `category: mine`, agregá `base_output_per_hour`; el build exigirá `target_mineral`.

### 4.5 Agregar un campo de balance configurable
`app/core/config.py` (`Settings`) + documentalo en `.env.example`. Se override por env
(12-factor). Ej: `ENERGY_REGEN_PER_HOUR`, `ENERGY_MAX`.

### 4.5b NPCs y su cerebro de IA
- Los NPC son `Player` con `is_npc=True`, uno por raza (`services/npc.py:ensure_npcs`).
- Cerebro por reglas (default): editá las prioridades en `RuleBasedBrain.act`.
- Cerebro LLM (opcional): poné `NPC_BRAIN=llm` + `OPENROUTER_API_KEY` en `.env`. Usa
  `OPENROUTER_MODEL` (default `google/gemma-4-31b-it:free`). Ante cualquier error cae a
  reglas, así el tick nunca depende de la red.
- **Personalidad** por raza: editá `personality` en `content/races.yaml` (se inyecta en el
  prompt → las NPC juegan en personaje). **Memoria** corta: `Player.npc_memory` (últimas 8
  acciones) + `recent_battles`, incluidos en el `state` para continuidad.
- Para cambiar de proveedor: reemplazá `_openrouter_decide` (misma firma `state -> action`).
  El `state` y el `dispatch_action` son agnósticos del proveedor.

### 4.5c Features con Redis (cache / rate-limit)
- `app/core/redis.py`: `get_redis` (dependency, devuelve cliente o None) + `cached_json`
  y `rate_limited`. Con `REDIS_ENABLED=false` todo degrada a no-op.
- Para cachear una respuesta: `await cached_json(redis, key, ttl, producer)`.
- Para limitar: `await rate_limited(redis, f"rl:<accion>:{player.id}", limite, ventana)`.
- Tests: usá `fakeredis.aioredis.FakeRedis` y override de `get_redis` (ver `test_redis.py`
  y los e2e en `test_api_e2e.py`).
- Avanzá el mundo a mano con `POST /admin/tick` (o `ogame-cli tick`), o automáticamente con
  `AUTO_TICK_SECONDS>0` (loop en el server; dev usa 15s en `.env`). En prod multi-réplica
  dejá `AUTO_TICK_SECONDS=0` y usá el CronJob de Helm para no duplicar ticks.

### 4.6 Agregar un endpoint nuevo
1. Schema en `app/schemas/__init__.py` (request/response Pydantic).
2. Lógica en un service de `app/services/` (puro/testeable; sin HTTP).
3. Router en `app/api/v1/<recurso>.py`; registralo en `app/api/v1/__init__.py`.
4. **Test unitario del service** + **test e2e HTTP en `tests/test_api_e2e.py`** (ver §5).
Mantené el router delgado: validar entrada → llamar service → mapear a schema.

> **Regla del proyecto:** toda feature nueva entra con su **test e2e** que pega contra el
> endpoint por HTTP (happy path + al menos un caso de error). Si no hay e2e, no está hecha.

### 4.7 Cambiar el modelo de datos (tablas) — con Alembic
1. Editá `app/models/__init__.py`.
2. Generá la migración (`make migration m="descripcion"`; autogenerate compara modelos vs esquema).
   Revisá el archivo en `migrations/versions/` (en SQLite, columnas NOT NULL nuevas necesitan
   `server_default`; FKs en batch necesitan nombre).
3. **No hace falta reset**: el server aplica migraciones a head **al arrancar**
   (`run_migrations()` en el lifespan), tanto en SQLite local como en Postgres.
4. El test `tests/test_migrations.py` falla si la migración no crea todas las tablas de los
   modelos — corré `pytest` antes de dar por hecho el cambio.

Manejo de la DB:
- **Local/dev**: SQLite, un archivo (`game.db`) en el repo, ignorado por git. Es por máquina.
- **Prod/contenedores**: Postgres. La URL sale de `DATABASE_URL`. Migraciones idempotentes:
  el `api` migra al arrancar; además compose tiene un servicio `migrate` y Helm un
  initContainer (para ordenar el arranque). `make db-reset` solo si querés empezar de cero.

---

## 5. Tests

- **Puras** (`test_energy.py`, `test_production.py`, `test_content.py`, `test_combat.py`):
  rápidas, sin DB.
- **Integración** (`test_flow.py`, `test_training.py`): usan `session` (sqlite en memoria,
  ver `conftest.py`) y ejercitan services reales (onboard → build → train → producir).
- **E2E HTTP** (`test_api_e2e.py`): pegan contra **todos los endpoints** por HTTP usando el
  fixture `client` (app FastAPI real + DB en memoria). Patrón: arrange por DB
  (`client.session_maker`), act por HTTP (`client.http`), assert por HTTP. Es la red de
  seguridad para verificar que "todo anda" de punta a punta.
- Patrón para integración: pedí el fixture `session`, creá un `Player`, llamá services,
  `commit`, y asertá sobre `player_stocks` / atributos.
- Convención de tiempo: usá `datetime.now(UTC)`; SQLite pierde tz, por eso los services
  normalizan con `_aware()` (tratan naive como UTC). Mantené esa convención.

Corré uno solo: `.venv/bin/python -m pytest tests/test_flow.py -q`.

---

## 6. Deploy

- **Laptop (todo en contenedores):** `docker compose -f deploy/docker-compose.yml up --build`.
- **k8s (kind/minikube/nube):**
  ```bash
  helm template galaxy deploy/helm        # ver manifiestos
  helm install galaxy deploy/helm         # desplegar
  ```
  Incluye: API (Deployment+Service, 2 réplicas), worker (CronJob cada 5 min),
  Postgres y Redis. Config por `deploy/helm/values.yaml`.
- Misma imagen en todos lados; config 100% por variables de entorno.
- **Prod:** poné `JWT_SECRET` de ≥32 bytes y usá Postgres (no SQLite).

---

## 7. Pendientes conocidos / próximos pasos

**Deuda técnica a saldar pronto:**
- **JWT_SECRET** fuerte en prod (PyJWT avisa con el default corto).
- **Redis locks** distribuidos para acciones mutantes (hoy hay cache + rate-limit; falta
  lock por jugador para correctitud con múltiples réplicas).

**Hecho:**
- ✅ Entrenamiento de personajes y unidades pesadas (`services/training.py`,
  `POST /bases/{id}/train`). Reusa el patrón energía+minerales+cola; las unidades
  requieren el edificio activo correspondiente (`requires` en `content/units.yaml`).
- ✅ Combate PvP (`services/combat.py`, `POST /combat/attack`, `GET /combat/reports`).
  `resolve_combat()` es puro/determinista; usa `stats` de unidades + bonus de raza
  (marciano +ataque, venusiano +defensa). Bajas en ambos lados y botín al ganar.
  Balance en `ATTACK_ENERGY_COST` / `LOOT_FRACTION`.
- ✅ Expediciones a lunas + boons de dioses (`services/expedition.py`, `services/boons.py`,
  `POST /expeditions`, `GET /expeditions/moons`). Cuesta energía + requiere transbordador;
  al volver entrega recursos premium (He-3, tierras raras, hielo) y un **boon temporal**
  (`production`/`attack`/`defense`) que se aplica en producción/combate. Todo en `gods.yaml`.

- ✅ Razas NPC con IA (`services/npc.py`). Cerebro enchufable: `RuleBasedBrain` (default)
  y `LlmBrain` (OpenRouter, `NPC_BRAIN=llm`) con fallback a reglas. Toman 1 acción/tick
  vía los mismos servicios. `POST /admin/tick` para avanzar el mundo; `GET /players`
  scoreboard. Modelo free `google/gemma-4-31b-it:free`.

- ✅ Combate con viaje/tiempo (`services/combat.py`): `start_attack` despacha una flota
  (`AttackMission`, unidades bloqueadas), `process_missions` resuelve al llegar y devuelve
  sobrevivientes + botín (ida y vuelta). Tiempo por distancia entre planetas.
- ✅ Defensas de edificio (torreta, `defense_power`) que refuerzan al defensor, y **recall**
  de flotas en vuelo (`POST /combat/missions/{id}/recall`).
- ✅ Notificaciones (`services/notifications.py`): emitidas en los procesadores diferidos
  (combate/economía/training/expedición). `GET/POST /notifications`. Para agregar un evento:
  llamá `notify(session, player_id, tipo, mensaje, data)` donde ocurre el cambio de estado.

- ✅ NPCs tácticos: `RuleBasedBrain` reacciona a amenazas (recall/torreta), fabrica tanques,
  ataca al más débil con margen y manda expediciones. El LLM recibe `incoming_attacks`,
  `my_missions`, `defense_estimate`, `reachable_moons` y puede `recall`/`expedition`.

- ✅ Push en tiempo real: SSE en `GET /notifications/stream` (`stream_events`), y un
  **cliente web** jugable en `GET /` (`web/index.html`) que lo consume con `EventSource`.

- ✅ Alianzas (`services/alliances.py`): crear/unirse/salir/listar; no se ataca a aliados
  (chequeo en `start_attack`). `/me` y scoreboard muestran la alianza.
- ✅ Investigación, ranking y más planetas/galaxias (ver arriba).

**Iteración 2 (todo aditivo, se engancha en `app/worker.py` sin tocar el request path):**
- Exponer research/ranking/alianzas en la **web** con UI dedicada (hoy ya vienen en `/me`,
  `/catalog`, `/players/ranking`, `/alliances`).
- Bot de Telegram (consume la misma API, incl. notificaciones).
- Ranking por alianza; NPCs que forman/usan alianzas.

---

## 8. Convenciones

- **Idioma:** nombres de contenido y mensajes de usuario en español; código en inglés.
- **Sin acentos en YAML de contenido** (evita problemas de encoding en algunos clientes).
- **Lint antes de commitear:** `ruff check --fix .` y `pytest`.
- **Capas:** datos→`content/`, reglas→`services/`+`registry.py`, HTTP→`api/`. No mezclar.
- **Extender, no romper:** API versionada (`/api/v1`); cambios aditivos; nunca rompas
  contratos ni el esquema de contenido existente.
