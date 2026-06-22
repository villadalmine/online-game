# SDD 8 — Límites de galaxia por usuarios (shards del mundo)

> **Estado:** propuesto · **Fecha:** 2026-06-22 · **Autor:** equipo online-game
> **Relacionado:** [SDD 7 — Capacidad/autoscaling](sdd-capacity-autoscaling.md) (el cap por
> galaxia es la unidad de sharding del tick y de la carga).

## 1. Objetivo

Que una **partida/galaxia tenga un máximo de jugadores** para que **no colapse** (ni el juego ni
la infra): densidad jugable, mapa acotado, combate balanceado, y un tick por galaxia de costo
acotado. Cuando una galaxia se llena, los nuevos jugadores entran a **otra instancia de galaxia**.

Doble beneficio: **gameplay** (un mundo no se vuelve injugable con 50k jugadores encima) +
**escalabilidad** (cada galaxia es un shard independiente, paralelizable).

## 2. Estado actual y problema

- Hoy `content/planets.yaml` define galaxias **estáticas** como regiones de mapa
  (`milky_way`, `andromeda`) con planetas y abundancias. **No** son shards de capacidad: todos los
  jugadores comparten el mismo mundo.
- El onboarding (`services/onboarding.py`) asigna galaxia/planeta **elegidos por el jugador**, sin
  límite de cuántos entran.
- Combate, ranking, NPCs, mapa y el `run_tick` operan sobre **todos** → a más jugadores, más densos
  y más caros, sin techo.

## 3. Diseño: la "instancia de galaxia" como shard

Separar el **concepto de contenido** (la plantilla de galaxia: planetas/abundancias, data-driven)
de la **instancia jugable** (un shard con un conjunto acotado de jugadores).

### 3.1 Modelo
- Nueva entidad **`GalaxyInstance`**: `id`, `template_key` (p.ej. `milky_way`), `name/seq`
  (Vía Láctea #1, #2…), `capacity` (máx jugadores humanos), `player_count`, `status`
  (`open`/`full`/`closed`), `created_at`.
- `Player` gana **`galaxy_instance_id`** (FK). El `galaxy_key`/`planet_key` actuales pasan a ser
  *dentro* de la instancia.
- Todas las interacciones (combate, mapa, ranking, alianzas, vista de enemigos) se **filtran por
  `galaxy_instance_id`**: solo ves/atacás a quien está en tu galaxia.

### 3.2 Asignación (matchmaking simple)
- En onboarding: buscar una `GalaxyInstance` con `status=open` del template elegido y
  `player_count < capacity`; si no hay, **crear una nueva** instancia (seq+1) y entrar ahí.
- Al llegar a `capacity` → `status=full` (no recibe nuevos; los actuales siguen).
- `capacity` es **config data-driven** (p.ej. `galaxy.capacity` en values/env o por template en
  YAML), para tunear sin código. Valor inicial sugerido: **acotado** (p.ej. 50–200 humanos por
  galaxia) — calibrar con SDD 7 y con sensación de juego.

### 3.3 NPCs por galaxia
- Hoy las NPCs son globales y comparten una alianza. Con shards: **un set de NPCs por instancia**
  (o un mínimo garantizado) para que cada galaxia tenga vida y rivales, sin cruzar shards.

### 3.4 Tick y carga por shard
- El tick pasa a ser **por instancia**: `run_tick(galaxy_instance_id)` recorre solo sus jugadores+
  NPCs+misiones. Esto **acota** el costo por tick y permite **paralelizar** (un Job por shard, o
  una cola de shards). Conecta directo con el SDD 7 (el O(N) global se vuelve O(N/shards) por
  worker).
- Combate/expediciones ya viajan con `arrives_at`; al filtrar por instancia, las misiones
  cross-galaxy simplemente no existen (o se prohíben explícitamente).

## 4. API / cliente
- `GET /players/me` incluye `galaxy_instance` (nombre/seq, cupo usado). El mapa y el ranking ya
  vienen acotados al shard. Opcional: `GET /galaxies` lista instancias abiertas (para un futuro
  "elegir/crear partida").
- Cambios **aditivos y versionados**; las cuentas existentes se migran a una instancia inicial.

## 5. Plan de tests (regla del proyecto)
**Servicio**: onboarding llena una instancia hasta `capacity` y el siguiente jugador cae en una
**nueva** instancia; combate/mapa solo ven jugadores de la **misma** instancia; NPCs presentes por
instancia.
**E2E HTTP** (`tests/test_api_e2e.py`): registrar `capacity+1` jugadores ⇒ aparecen ≥2 instancias;
un ataque a un jugador de **otra** instancia → 4xx claro; `/players/me` reporta su instancia.
**Migración**: test de que las tablas nuevas se crean (ya hay `tests/test_migrations.py`).

## 6. Riesgos / decisiones
- **Migración de datos**: meter a todos los jugadores actuales en una instancia "génesis" por
  template; aditivo, sin pérdida.
- **Fragmentación social**: amigos en distinta galaxia. Mitigar permitiendo elegir/“unirse a la de
  un amigo” si tiene cupo (follow-up).
- **`capacity` mal elegido**: muy chico fragmenta; muy grande no protege. Es config → se ajusta con
  los datos del SDD 7 y feedback de juego.
- **Cross-shard**: explícitamente no soportado en v1 (combate/alianzas dentro del shard). Simplifica
  y es lo que da el aislamiento de carga.
