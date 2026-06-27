# SDD 46 — Alojamiento y capacidad de unidades (grafo unidad ↔ edificio)

> **Estado:** **v1 implementado** (enforce detrás de flag `housing_enforced`, default OFF) ·
> **Fecha:** 2026-06-27
> Hecho: `domain`/`housing_size` en units, `houses` en edificios + `port` (naval) en YAML
> (→ /catalog); `app/services/housing.py` (capacity/occupancy/can_train/`housing_matrix`, puras +
> tests); enforce en `start_training` (mensaje accionable i18n); bloque `housing` en `/players/me`;
> aristas unidad→edificio (`housed_in`/`houses`) + grounding `mech_housing` en el grafo; e2e en
> `tests/test_api_e2e.py`. **Pendiente:** UI (barras de plazas + tooltips), NPC respeta capacidad
> en su build order, balance antes de prender el enforce en prod, v2 por base/planeta.
> **Relacionado:** SDD 1 (grafo de dependencias + asistente IA), SDD 13 (rigor científico:
> `propulsion`/`requires_atmosphere`/`requires_liquid_water`), SDD 37 (colonización), SDD 42
> (mercado: `hangar` aloja naves, stat `cargo`), `content/{units,buildings}.yaml`,
> `app/services/training.py`, `app/services/depgraph.py`, `app/content/registry.py`.

## 1. Objetivo
Hoy podés entrenar **unidades infinitas**: nada limita cuántas guardás. Este SDD agrega un
**límite de capacidad data-driven**: cada unidad **pertenece a un dominio de alojamiento** y cada
**edificio provee plazas** para uno o más dominios. Si no tenés plazas libres, **no podés entrenar
esa unidad** hasta construir/ampliar el edificio que la aloja. Esto:

- Da una **relación explícita unidad ↔ edificio** (un grafo/matriz versionado) — "el militar va al
  cuartel, el trabajador a la base central, el científico al laboratorio, el avión al hangar…".
- Hace que **construir tenga sentido estratégico** (crecer ejército ⇒ crecer infraestructura).
- Es **clave para la IA** (asistente + NPC): el grafo le dice *por qué* no puede entrenar y *qué*
  construir ("te faltan plazas de infantería: construí otro cuartel"). Sin alucinar: lee la matriz.

**No** cambia el combate ni el costo de entrenar; sólo agrega un **chequeo de plazas** antes de
encolar y expone la capacidad en `/catalog` y en `/players/me`.

## 2. Estado actual (verificado 2026-06-27)
- **Unidades** (`content/units.yaml`): grupos `personnel` (worker, soldier, scientist, spy) y `heavy`
  (tank, ship, aircraft, shuttle, cargo_ship). Cada una con `requires` = edificio que debe estar
  **activo para entrenarla** (gate), `stats`, y atributos de rigor (`propulsion`,
  `requires_atmosphere`, `requires_liquid_water`).
- **`requires` ≠ alojamiento**: es sólo "dónde se entrena". Hoy `soldier requires headquarters` (no
  cuartel). Este SDD introduce el **alojamiento** como capa separada (un edificio puede entrenar una
  unidad pero no necesariamente alojarla, y viceversa).
- **`UnitStock` es por jugador (global)**: `(player_id, unit_key, quantity)` — las unidades **no están
  ubicadas en una base/planeta**. → decisión de granularidad en §7.
- **Precedente de capacidad (SDD 42)**: `hangar` ya limita cuántas naves de carga despachás por
  ventana, y `cargo_ship` tiene stat `cargo`. Reusamos ese patrón, generalizado a dominios.
- **Edificios** ya tienen `category` (core/mine/energy/economy/military/heavy/science/defense) y la
  IA ya consume el grafo de dependencias (`depgraph.py`, SDD 1).

## 3. Concepto: dominios de alojamiento (housing domains)
Introducimos un **dominio** por unidad (atributo data-driven `domain`). El dominio es el "tipo de
plaza" que la unidad ocupa. Un **edificio** declara cuántas plazas ofrece por dominio
(`houses: { <domain>: <plazas> }`). **Capacidad de un dominio = suma de `houses[domain]` de todos
tus edificios activos**. **Ocupación = suma de unidades de ese dominio** (× su tamaño, §5).

El grafo es: **unidad → dominio → edificio(s) que alojan ese dominio**. Un edificio puede alojar
**varios dominios** (p.ej. un hangar para "las que vuelan" y "las espaciales"); un dominio puede ser
alojado por **varios edificios** (p.ej. infantería en cuartel **y** un futuro búnker).

### 3.1 Dominios propuestos (data-driven; tunables por YAML)
| dominio | "qué es" (lenguaje del pedido) | unidades hoy |
|---|---|---|
| `personnel` | gente civil/de soporte | worker, scientist, spy |
| `infantry`  | militares (gente en armas) | soldier |
| `ground`    | unidades pesadas terrestres | tank |
| `naval`     | "las de mar" | ship |
| `air`       | "las que vuelan" | aircraft |
| `space`     | espaciales | shuttle, cargo_ship |

> Los dominios son **strings en el YAML**: agregar uno nuevo = editar contenido, sin tocar código.

## 4. La matriz (grafo unidad ↔ dominio ↔ edificio) — valores de arranque
**Quién aloja cada dominio** (qué edificio da plazas, y cuántas por nivel/edificio):

| dominio | edificio(s) que alojan | plazas por edificio (arranque) |
|---|---|---|
| `personnel` | `headquarters` (base) + `research_lab` | HQ: 20, lab: 10 |
| `infantry`  | `barracks` | 30 |
| `ground`    | `factory` | 10 |
| `air`       | `hangar` | 8 |
| `space`     | `hangar` (comparte) | 8 |
| `naval`     | **`port`** (edificio NUEVO, aditivo) | 8 |

**Unidad → dominio → dónde vive** (la tabla "cuál pertenece a cuál" que pediste):

| unidad | dominio | se entrena en (`requires`, ya existe) | se aloja en (NUEVO) |
|---|---|---|---|
| worker     | personnel | headquarters | headquarters / research_lab |
| scientist  | personnel | research_lab | headquarters / research_lab |
| spy        | personnel | research_lab | headquarters / research_lab |
| soldier    | infantry  | headquarters → *(mover a `barracks`)* | barracks |
| tank       | ground    | factory      | factory |
| aircraft   | air       | factory      | hangar |
| shuttle    | space     | factory      | hangar |
| cargo_ship | space     | factory      | hangar |
| ship       | naval     | factory      | port (nuevo) |

> **Ajuste de coherencia (opcional, recomendado):** alinear el gate de `soldier` a `barracks`
> (`requires: barracks`) para que "el militar va al cuartel" valga tanto para entrenar como para
> alojar. Es un cambio de balance (más caro empezar a hacer soldados); se decide al implementar.

## 5. Atributos nuevos (data-driven, aditivos)
### 5.1 En `units.yaml` (por unidad)
- `domain: <string>` — a qué dominio pertenece (tabla §4). **Si falta** ⇒ `personnel` (default seguro).
- `housing_size: <int>` (default `1`) — cuántas plazas ocupa **una** unidad. Una unidad pesada ocupa
  más que una persona. Arranque sugerido: worker/scientist/spy/soldier = 1; tank/aircraft/ship = 2;
  shuttle/cargo_ship = 3.

### 5.2 En `buildings.yaml` (por edificio)
- `houses: { <domain>: <plazas> }` — cuántas plazas aporta **cada** instancia activa de ese edificio.
  Un edificio puede alojar varios dominios (p.ej. `hangar: { air: 8, space: 8 }`). **Si falta** ⇒ no
  aporta plazas.

> Ambos son **opcionales**: el contenido viejo sin estos campos sigue cargando (compat total). El
> default de capacidad (§8) decide qué pasa si un dominio no tiene ningún edificio que lo aloje.

## 6. Fórmula de capacidad (pura, determinista, testeable)
```
capacity[domain]  = Σ ( houses[domain] de cada edificio ACTIVO del jugador )
occupancy[domain] = Σ ( quantity(u) · housing_size(u) )  para toda unidad u con domain == domain
                    + unidades de ese dominio EN COLA de entrenamiento (reservadas)
free[domain]      = capacity[domain] − occupancy[domain]
```
- **Entrenar N de la unidad u** se permite sólo si `N · housing_size(u) ≤ free[domain(u)]`.
- **Las unidades en cola cuentan** como ocupación (reservan plaza al encolar) para no sobrevender
  capacidad con varias colas en paralelo.
- **Unidades fuera de la base** (flotas en viaje de ataque/expedición/espionaje) **siguen contando**
  como ocupación del jugador (son tuyas; "están en algún lado"). Simplicidad v1; ver §7.

## 7. Granularidad: por jugador (v1) vs por planeta (v2)
El pedido dice "límite **por planeta** en tu base". Pero `UnitStock` es hoy **global por jugador**.
Dos fases:

- **v1 — capacidad total del jugador (sin refactor):** `capacity[domain]` suma `houses` de **todos**
  tus edificios activos en **todas** tus bases; la ocupación es tu stock global. Cumple "en algún
  lugar tiene que estar" (tu infraestructura total te limita) y es **aditivo**, sin migrar el modelo
  de unidades. **Recomendado para arrancar.**
- **v2 — capacidad por base/planeta (refactor):** ubicar las unidades por base (`UnitStock` pasa a
  `(player_id, base_id, unit_key)` o nueva tabla) y calcular capacidad/ocupación **por base**. Permite
  el límite "por planeta" literal y abre logística (mover unidades entre planetas). Es un SDD propio
  (toca entrenamiento, combate —de qué base salen las tropas—, transporte). Se deja **stubbeado**:
  el cálculo de §6 ya es por-conjunto-de-edificios, así que reusarlo por base es directo.

## 8. Enforcement y defaults
- **Dónde:** `app/services/training.py:start_training`, **antes** de gastar energía/minerales: calcular
  `free[domain(unit)]`; si `N·size > free` ⇒ `TrainingError` con mensaje claro y accionable
  (i18n ES/EN): *"No hay plazas de {dominio}. Construí/ampliá {edificios que alojan}."* La UI lo
  muestra como toast (SDD 33/feedback) y pre-cálculo inline.
- **Default si un dominio no tiene edificio que lo aloje:** configurable
  (`config.py: housing_enforced: bool = True`, `base_housing_per_domain: int = 0`). Con
  `base_housing_per_domain=0` y sin edificio ⇒ no podés tener esa unidad (fuerza construir el
  alojamiento). Para **no romper partidas existentes** al activar la feature: arrancar con
  `housing_enforced=False` (solo medir/mostrar) y prender el enforce en una release posterior, o dar
  un `base_housing_per_domain` generoso de gracia. **Decisión de rollout, no de código.**
- **Compat:** todo aditivo. Sin los campos YAML ⇒ capacidad 0 + enforce off ⇒ comportamiento de hoy.

## 9. Exposición data-driven + para la IA (clave del pedido)
- **`/catalog`** (`registry.localize*`): cada unidad incluye `domain`/`housing_size`; cada edificio
  incluye `houses`. Así **web, CLI y la IA** ven el grafo sin hardcodear. (Recordar: catálogo
  cacheado 300s en Redis — los campos nuevos tardan ≤5min tras deploy.)
- **`/players/me`**: agrega `housing: { <domain>: { capacity, occupancy, free } }` para que el cliente
  muestre "Infantería 30/30 — lleno" y la IA sepa el estado real.
- **Grafo para el asistente (SDD 1, `depgraph.py`):** añadir las aristas **unidad→dominio→edificio** y
  un doc de grounding (`unit_housing`) que enseñe la regla: "para más X, construí Y". El NPC
  (`npc.py`) usa la misma matriz al decidir su build order (no entrena lo que no puede alojar; si
  quiere más infantería, encola un cuartel primero). **La matriz es la fuente de verdad compartida
  IA ↔ juego.**
- **Resumen IA-friendly:** un helper `housing_matrix()` (deriva de `content`) que devuelve el grafo
  serializable {dominio: {units:[...], houses_by_building:{...}}} para inyectar en el prompt del
  asistente y para tests.

## 10. UI (web)
- En el panel de **bases/entrenamiento**: barra "plazas por dominio" (X/Y), pintada cuando está cerca
  del tope; el botón de entrenar se deshabilita con tooltip "sin plazas de {dominio}" (pre-cálculo
  inline, igual que energía/minerales hoy).
- En el modal de **edificio**: "aloja: {dominios} (+N plazas c/u)".
- Modo pictográfico (SDD 43): íconos por dominio (👷/🪖/🛡/🚢/✈/🚀) + chip "X/Y".

## 11. API
- `GET /catalog` — extendido (domain/housing_size/houses). Aditivo.
- `GET /players/me` — agrega bloque `housing` (capacity/occupancy/free por dominio).
- `POST /bases/{id}/train` — ahora puede devolver error `no_housing` (4xx) con `{domain, need, free,
  built_by:[edificios]}` para que el cliente guíe al jugador.

## 12. Tests / validación
- **Pureza:** `housing_capacity(buildings)`, `housing_occupancy(units, queue)`, `can_train(unit, n,
  free)` testeables a mano (umbrales de la matriz §4/§6).
- **Servicio:** entrenar hasta el tope OK; uno más ⇒ `TrainingError no_housing`; construir el edificio
  que aloja sube la capacidad y desbloquea; unidades en cola reservan plaza (no se sobrevende).
- **Default/rollout:** `housing_enforced=False` ⇒ comportamiento idéntico al actual (invariante).
- **Catálogo:** `/catalog` expone domain/houses (localizado ES/EN).
- **IA:** `housing_matrix()` coherente con el YAML; el NPC no entrena sin plazas y antepone el edificio.
- **e2e** (`tests/test_api_e2e.py`, regla del proyecto): happy path (entrenar dentro de capacidad +
  ver `housing` en `/players/me`) + error (`no_housing` al pasarse) + desbloqueo al construir.

## 13. Plan de implementación (cuando se decida)
1. **Contenido:** agregar `domain`/`housing_size` a `units.yaml` y `houses` a `buildings.yaml` (matriz
   §4) + edificio `port` (naval). Validar carga (esquema Pydantic en `registry`).
2. **Cálculo puro** (`app/services/housing.py`): capacity/occupancy/free + `housing_matrix()`. Tests.
3. **Enforcement** en `start_training` (flag `housing_enforced`, default off al principio) + error i18n.
4. **Exposición:** `/catalog` + bloque `housing` en `/players/me`. Tests + e2e.
5. **IA:** aristas en `depgraph.py` + grounding `unit_housing`; NPC respeta capacidad en su build order.
6. **UI:** barras de plazas + tooltips + pictográfico.
7. **Rollout:** medir con enforce off → prender enforce en release posterior (o gracia inicial).
8. **(Futuro) v2:** capacidad por base/planeta (refactor de ubicación de unidades) — SDD aparte.

## 14. Riesgos / decisiones
- **No romper partidas vivas:** un jugador con más unidades que su capacidad actual al activar el
  enforce no debe perder unidades. Regla: el enforce **bloquea entrenar nuevas**, **nunca destruye**
  las existentes (podés quedar "sobrepoblado" hasta que amplíes o pierdas unidades en combate).
- **Balance:** plazas por edificio + `housing_size` se afinan por YAML; arrancar generoso para no
  frustrar, ajustar con datos.
- **Cardinalidad/UX:** 6 dominios es manejable; no explotar en micro-dominios.
- **Coherencia `requires` vs alojamiento:** mantener ambos conceptos separados pero **alineados** en la
  doc (la matriz §4 es la referencia única que leen humanos **y** la IA).
- **Granularidad:** v1 por jugador es honesto con el modelo actual; "por planeta" literal es v2 y se
  documenta como tal para no prometer de más.
