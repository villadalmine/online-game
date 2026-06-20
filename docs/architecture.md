# Arquitectura

## Stack

- **API:** Python 3.12 + FastAPI (async) + Uvicorn. OpenAPI auto-generado.
- **Datos:** Postgres (fuente de verdad) + Redis (cache/locks/rate-limit — opcional en el slice).
- **ORM:** SQLAlchemy 2.x async. Migraciones: Alembic (prod). `init_models()` crea tablas en dev/sqlite.
- **Auth:** JWT (pbkdf2 para passwords, sin deps nativas).

## API-first

Un solo contrato HTTP `/api/v1` sirve a todos los clientes (web, móvil, Telegram, WhatsApp, CLI).
El cliente CLI en `clients/cli/` es la prueba viviente de que toda la jugabilidad pasa por la API.

Routers:
- `auth`     — register / login → JWT
- `players`  — `GET /me` (estado completo), `POST /onboard`
- `catalog`  — todo el contenido data-driven (los clientes no hardcodean nada)
- `bases`    — `POST /{id}/build`

## Por qué escala

- **API stateless** → réplicas horizontales detrás de un LB; HPA en k8s.
- **Estado lazy por timestamp** (`services/energy.py`, `services/production.py`): la energía y la
  producción se calculan al leer, desde `*_updated_at`. No hay tareas por usuario → el costo no
  crece con usuarios inactivos (sin "cron-storms").
- **`advance on access`** (`services/state.py`): cada lectura finaliza colas vencidas, recolecta
  minas y aplica regen; luego hace snapshot.
- Postgres es el único punto con estado (futuro: réplicas de lectura); Redis absorbe lecturas
  calientes y locks. Turn-based asíncrono = sin baja latencia → barato de escalar.

## Data-driven (extender sin romper)

`content/*.yaml` → `app/content/registry.py` (carga + valida + resuelve roles).
El motor nunca hardcodea minerales/edificios/razas. Cambiar el juego = cambiar datos.

La pieza central: `building_cost_in_minerals(race, building)` traduce el costo en **roles**
de un edificio a **minerales concretos** según el mapeo de la raza.

## Worker / tick

`app/worker.py` (k8s CronJob o loop): finaliza colas y recolecta minas para todos los jugadores.
Es el **seam** donde la iteración 2 enchufa combate, boons de dioses y turnos de IA, **sin tocar
el camino de request**.

## Portabilidad

Un `Dockerfile`. `deploy/docker-compose.yml` para laptop. `deploy/helm/` para k8s
(api Deployment+Service, worker CronJob, Postgres y Redis). Misma imagen en todos lados;
config 100% por variables de entorno (12-factor). Funciona en kind/minikube → cualquier nube.

## Modelo de datos

`Player` (energía + timestamp + galaxia/planeta/raza) · `Base_` · `Building`
(status building/active, `completes_at`, `production_mineral`, `last_collected_at`) ·
`ResourceStock` (unique por player+mineral).
