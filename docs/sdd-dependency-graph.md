# SDD 1 — Grafo de dependencias de recursos y tecnologías

> **Estado:** propuesto · **Fecha:** 2026-06-22 · **Autor:** equipo online-game
> **Depende de:** `content/*.yaml`, `app/content/registry.py`, `app/services/economy.py`
> **Consumido por:** [SDD 2 — Asistente AI personal](sdd-ai-assistant.md) (lo usa como *skill*/grounding)

## 1. Objetivo

Construir, **de forma 100% derivada de los datos** (`content/*.yaml`), un **grafo de
dependencias** que represente cómo se relacionan minerales → minas → edificios → unidades →
tecnologías → efectos, y exponer sobre él **consultas deterministas**:

1. **Prerrequisitos** de cualquier objetivo (qué edificios/minerales/energía hace falta, en
   orden, con cierre transitivo).
2. **Bloqueos** de un jugador concreto (dado su estado, *qué exactamente* le falta para
   construir/entrenar/investigar algo, y *por cuánto*).
3. **Fuentes de un mineral** (cómo conseguirlo: mina local, expedición, saqueo, comercio de
   alianza), incluyendo el caso "tu planeta no lo produce".

El grafo es el **conocimiento del juego** que el LLM del asistente (SDD 2) usa como base para
recomendar. La parte de *razonamiento sobre el grafo* es **determinista y testeable sin red**;
el LLM solo lo redacta y prioriza. Si el LLM no está, el asistente sigue funcionando con estas
consultas.

### No-objetivos

- No cambia ninguna regla de juego ni el balance: es **solo lectura/análisis** sobre el
  contenido existente. (El único componente que *otorga* recursos es el "hack" del SDD 2, que
  vive fuera de este documento.)
- No introduce dependencias nuevas. Python + el contenido YAML que ya existe.

## 2. Modelo del grafo

El grafo es **paramétrico por raza y por planeta**, porque:

- **Raza:** las recetas piden *roles* abstractos (`structural`/`energetic`/`advanced`) y cada
  raza los resuelve a un mineral concreto (`races.yaml: resource_roles`). El costo "real" en
  minerales solo existe una vez fijada la raza (ya lo calcula
  `registry.building_cost_in_minerals` / `unit_cost_in_minerals` / `tech_cost_in_minerals`).
- **Planeta:** un mineral solo se puede **producir localmente** si la abundancia del planeta es
  `> 0` (`registry.planet_abundance`). Si es 0, ese mineral es "importado" (expedición/saqueo/
  comercio). Esto define los nodos *fuente*.

### Tipos de nodo

| Tipo        | Origen en datos                              | Notas |
|-------------|----------------------------------------------|-------|
| `mineral`   | `minerals.yaml`                              | hoja/recurso |
| `energy`    | pseudo-recurso                               | regen lazy + `power_plant` sube el tope |
| `building`  | `buildings.yaml`                             | `category=mine` produce un mineral |
| `unit`      | `units.yaml` (`personnel`+`heavy`)           | `requires` = edificio activo |
| `tech`      | `technologies.yaml`                          | `requires` = edificio activo; otorga `effect` |
| `effect`    | `production`/`attack`/`defense`              | destino de los multiplicadores de tech/dioses/alianza |

### Tipos de arista

| Arista       | De → A                       | Semántica |
|--------------|------------------------------|-----------|
| `costs`      | building/unit/tech → mineral | cantidad (resuelta por raza) + `energy_cost` |
| `produces`   | mine(mineral) → mineral      | `base_output_per_hour × abundancia` |
| `requires`   | unit/tech → building         | el edificio debe estar **activo** |
| `unlocks`    | building → unit/tech         | inverso de `requires` (para "¿qué me habilita esto?") |
| `boosts`     | tech → effect                | `magnitude` (apila en `services/effects.py`) |

> Nota: los **edificios** hoy no tienen `requires` propio (cualquier edificio se levanta sobre
> la base). El modelo deja la arista `building → building` prevista por si más adelante un
> edificio pide otro (extender, no romper).

## 3. Componentes

### 3.1 `app/services/depgraph.py` (nuevo, puro)

Sin estado, sin DB; solo lee `get_content()`. Construye y consulta el grafo.

```python
def build_graph(race_key: str, planet_key: str) -> DepGraph: ...
def prerequisites(race_key, planet_key, target_key) -> Plan: ...
def mineral_sources(race_key, planet_key, mineral_key) -> list[Source]: ...
def analyze(state: PlayerSnapshot, target_key: str) -> BlockerReport: ...
```

- **`build_graph`** arma nodos y aristas resolviendo roles→minerales y abundancias. Resultado
  cacheable por `(race, planet)` (memo en proceso; el contenido es estático por deploy).
- **`prerequisites(target)`** = cierre transitivo *estático* (ignora el estado del jugador):
  edificios a tener activos (siguiendo `requires`), minerales y energía necesarios para el
  objetivo y sus prerequisitos. Devuelve un **orden topológico** sugerido (p.ej. para entrenar
  un tanque: `factory` activo → costo del tanque).
- **`mineral_sources(mineral)`** = lista priorizada de cómo obtener el mineral:
  `local_mine` (si abundancia>0, con output estimado), `expedition` (lunas alcanzables que lo
  otorgan vía boon/recurso premium), `loot` (saqueo en combate), `alliance_trade`.
- **`analyze(state, target)`** = la consulta **dependiente del estado** (ver §4). Es pura: toma
  un *snapshot* del jugador (no toca la sesión) para que sea trivial de testear.

### 3.2 Estructuras (`app/schemas/`)

```python
class Cost(BaseModel):       minerals: dict[str, float]; energy: float
class Source(BaseModel):     kind: Literal["local_mine","expedition","loot","alliance_trade"]
                             detail: str; estimate_per_hour: float | None = None
class Blocker(BaseModel):    kind: Literal["mineral","energy","building","not_producible"]
                             key: str; have: float; need: float; sources: list[Source] = []
class BlockerReport(BaseModel):
                             target: str; buildable: bool; blockers: list[Blocker]
                             prerequisites: list[str]            # orden topológico
class GraphNode/GraphEdge:   # para el endpoint estático del catálogo
```

### 3.3 Endpoint estático: `GET /api/v1/catalog/graph`

```
GET /api/v1/catalog/graph?race=martian&planet=mars
→ { nodes:[...], edges:[...], minerals_local:[...], minerals_imported:[...] }
```

- Pensado para que **cualquier cliente** (web/CLI/Telegram) dibuje el árbol tecnológico y la
  web muestre "para esto necesitás…". Estático por `(race,planet)` → **cacheable en Redis**
  igual que `/catalog` (degradable si Redis no está).
- Reusa `app/content/registry.py`; no toca la base de datos → no requiere auth de jugador.

### 3.4 `PlayerSnapshot` y el puente con el estado

`analyze()` no consulta la DB; recibe un `PlayerSnapshot` que el llamador arma una vez:

```python
@dataclass
class PlayerSnapshot:
    race_key: str; planet_key: str
    minerals: dict[str, float]; energy: float
    active_buildings: set[str]; queued_buildings: set[str]
    mines: set[str]                 # minerales que ya minás
```

Un helper `await snapshot(session, player)` lo construye reutilizando
`player_stocks`, `_current_energy` y la query de edificios (las mismas piezas que ya usa
`npc._npc_state`). Así el SDD 2 puede pedir `analyze` para *cada* objetivo sin N consultas.

## 4. Algoritmo de `analyze(state, target)`

Determinista, sin LLM. Para un objetivo (building/unit/tech):

1. **Resolver costo** real: `Cost = registry.*_cost_in_minerals(race, target)` + `energy_cost`.
2. **Prerrequisito de edificio** (`requires`): si el edificio no está `active`:
   - si está en cola (`queued`) → blocker `building`/"en construcción" (no fatal, esperar);
   - si no existe → blocker `building` + (recursivo) los bloqueos para *construir ese edificio*.
3. **Minerales**: por cada mineral del costo con `have < need` → blocker `mineral`
   con `have/need` y `sources = mineral_sources(...)`. Si además **abundancia==0 y no hay mina**
   posible → marcar `not_producible` (caso "tu planeta no lo da; tenés que importarlo").
4. **Energía**: si `energy < energy_cost` → blocker `energy` (con la regen/h para estimar la
   espera).
5. `buildable = (blockers vacíos)`. `prerequisites` = orden topológico de `prerequisites()`.

`mineral` shortfall = `need - have` es justamente **lo mínimo que el "hack" del SDD 2 debe
otorgar** para desbloquear. Por eso el cálculo vive acá (única fuente de verdad) y el hack lo
consume.

## 5. Casos de uso (los que el usuario pidió)

- *"No puedo seguir construyendo porque me falta un material."* → `analyze` devuelve el/los
  `mineral` blockers con `have/need` y `sources`. La web ya muestra "te falta X"; ahora además
  dice **cuánto** y **cómo conseguirlo**.
- *"¿Qué necesito para un tanque?"* → `prerequisites("tank")` = `factory` activo + costo. Si no
  tenés factory, encadena sus prerequisitos.
- *"Mi planeta no produce titanio."* → `mineral_sources("titanium")` sin `local_mine` →
  sugiere expedición a la luna que lo otorga o saqueo/comercio.

## 6. Plan de tests (regla del proyecto)

**Unit** (`tests/test_depgraph.py`, sin DB, puros):
- `prerequisites("tank")` incluye `factory`; `prerequisites("mining_efficiency")` incluye
  `research_lab`.
- Por raza: el costo de `mine` para `martian` usa `iron`/`sulfur`; para `terran` usa
  `iron`/`silicon` (verifica resolución de roles).
- `mineral_sources` marca `not_producible` para un mineral con abundancia 0 en el planeta y
  ofrece `expedition` cuando una luna alcanzable lo da.
- `analyze` con stock insuficiente → blocker `mineral` con `need-have` exacto; con todo cubierto
  → `buildable=True`.

**E2E HTTP** (`tests/test_api_e2e.py`):
- `GET /catalog/graph?race=...&planet=...` 200 con `nodes`/`edges` no vacíos y coherentes con el
  catálogo; caso de error: raza inexistente → 422/404.

**CHANGELOG**: entrada al mergear.

## 7. Riesgos / decisiones

- **Recursión en `requires`:** hoy el árbol es poco profundo (unit→building→base). Igual se
  implementa con cierre transitivo + detección de ciclos por las dudas (extender sin romper).
- **Costo estático vs. multiplicadores:** `analyze` compara contra el **costo base** (lo que
  cobran los servicios). No mete multiplicadores de producción/ataque acá; eso es de economía.
- **Cache:** el grafo es estático por `(race,planet)` → memo en proceso + Redis en el endpoint.
  Nunca depende de Redis para funcionar (degradable).
