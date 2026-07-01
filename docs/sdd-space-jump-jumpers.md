# SDD 63 — Saltos espaciales: naves "jumper" para logística instantánea entre tus bases

> **Estado:** **IMPLEMENTADO + PRENDIDO** 2026-07-01 — tech capstone `space_jump` (multi-prereq: todo
> el árbol endgame) + unidad `jumper` (cap 6) + salto INSTANTÁNEO en `troops.py:start_move` (reusa
> mover-tropas SDD 62; gasta energía). `space_jump_enabled=true` en prod (aditivo, gateado por research
> carísimo). v1 solo logística propia. Tests `test_troops.py` + e2e. · **Diseño:** 2026-06-30 · usuario.
> **Relacionado (PRERREQUISITOS — es el techo del árbol):** [SDD 61 satélites](sdd-satellites-recon.md),
> [SDD 37 conquista orbital](sdd-colonization.md) (`orbital_robotics`), [SDD 49 misiles](sdd-missile-launcher.md)
> (`nuclear_fission`), [SDD 50 drones](sdd-drones-intraplanet.md), [SDD 57 hiperespacio](sdd-hyperspace-base-buster.md)
> (`hyperspace_travel`). Apoya en [SDD 62 guarnición / mover tropas](sdd-garrison-troops-per-base.md)
> y [SDD 13 rigor científico](sdd-scientific-accuracy.md). Archivos: `content/{technologies,units}.yaml`,
> `app/services/troops.py`, `app/services/combat.py` (viaje).

## 1. Idea (usuario, 2026-06-30)
Un research de **salto espacial** (alta tecnología) que, **junto con el laboratorio científico**,
desbloquea **naves saltadoras ("jumpers")** que **transportan tropas** (no muchas — definir la mejor
cantidad) y **saltan de un planeta a otro SIN tardar tiempo**. Para tenerlo hay que **haber
desarrollado todo**: satélites, conquista orbital, misiles, drones e hiperespacio. Es el **techo
tecnológico** que da una **gran ventaja logística** para mover cosas y **poblar tus bases**.

## 2. Qué es (decisión de diseño)
El jumper es **logística instantánea entre TUS bases**: mueve tropas/obreros de un planeta a otro **al
instante** (sin el viaje de SDD 62), con **capacidad limitada por nave** → no es una flota de invasión,
es un puente de suministro. Resuelve "reforzar/poblar colonias rápido" que la guarnición (SDD 62) hizo
necesario (defender cada base). **v1: solo entre bases propias** (no ofensivo — ver §6).

## 3. Diseño data-driven
### 3.1 Research capstone (`technologies.yaml`)
- **`space_jump`** — "Salto espacial (puente de Einstein-Rosen)". Es el **techo del árbol**: requiere
  TODO el endgame que pidió el usuario. Como una tech tiene un solo `requires_tech` directo, encadenamos
  por el último y **validamos el resto como prerrequisitos** (el grafo SDD 1 ya soporta multi-req vía
  `prerequisites`; si no, sumamos un campo `requires_techs: [...]`):
  - `hyperspace_travel` (SDD 57) · `satellite_tech` (SDD 61) · `nuclear_fission` (SDD 49) ·
    `attack_drones` (SDD 50) · `orbital_robotics` (SDD 37).
  - Costo por ROL (SDD 53): carísimo, `energetic`+`advanced` (fin de juego). Categoría `hyperspace`/
    `endgame`.

### 3.2 Unidad: jumper (`units.yaml`, dominio `space`)
- **`jumper`** — "Nave saltadora". `requires: research_lab` (lab científico) + `requires_tech:
  space_jump`. Carísima y lenta de construir; alto `energy_cost`.
- **Capacidad de carga** `jump_capacity` (en plazas de alojamiento que puede ferriar) = **6** (definido:
  ~6 = un puñado de tropas, p.ej. 1 tanque(6) o 6 soldados(1) o 3 científicos — "no muchas", coherente
  con `housing_size` SDD 46). Rebalanceable por YAML.
- Stats de combate bajos (es transporte, no combate). Se aloja en hangar (space).

### 3.3 Mecánica del salto (instantáneo, entre bases propias)
- `POST /bases/{id}/jump {to_base_id, units}` (o `instant:true` en `/move-troops`): si la base de
  origen tiene un `jumper` disponible y el jugador investigó `space_jump`, el traslado es **instantáneo**
  (no crea `TroopMove` con timer; deposita ya en destino), hasta `jump_capacity` por jumper.
- **Costo/freno por salto** (evita teletransporte infinito): cada salto **gasta energía** (config
  `jump_energy_cost`) y consume el "uso" del jumper por un **cooldown** (config `jump_cooldown_seconds`)
  o un combustible. Más jumpers → más saltos en paralelo. Define el equilibrio: caro + capacidad chica
  + cooldown ⇒ es ventaja real pero no rompe el juego.
- **Poblar bases:** también ferria obreros/científicos (no solo militares) → llenás una colonia nueva
  al toque (lo que pidió: "poblar tus bases"). Respeta el alojamiento del destino (SDD 46/62).

## 4. Por qué es "mucha tecnología que da ventaja" (lo que pidió corregir/definir)
El capstone exige las CINCO ramas endgame (satélites, órbita, misiles, drones, hiperespacio) → llegar
cuesta muchísimo, y a cambio das un salto cualitativo: **logística instantánea**. Es la recompensa
natural de tener el árbol completo, y se ata a SDD 62 (con guarnición, mover tropas importa) y SDD 57
(hiperespacio ya aceleraba flotas; el salto lo lleva a "instantáneo" para tu propia red).

## 5. Tests / validación
- `test_balance.py`: `space_jump` es de las techs más caras y exige los 5 prereqs; `jumper` carísima.
- `test_troops.py`/`test_jump.py`: con `jumper` + `space_jump`, el traslado entre bases propias es
  instantáneo (arrives_at ≈ ahora), topeado a `jump_capacity`, gasta energía y respeta el cooldown;
  sin jumper o sin tech, cae al traslado normal con viaje (SDD 62).
- e2e (`test_api_e2e.py`): investigar la cadena → construir jumper → saltar tropas a una colonia →
  llegan al instante; sin la tech, el mismo request usa el viaje normal.
- Invariante: solo entre bases PROPIAS; respeta alojamiento del destino; no esquiva los topes de ataque.

## 6. Preguntas abiertas (decidir antes de implementar)
- ¿El jumper puede **saltar a atacar** (llevar tropas a una base enemiga al instante) o es **solo
  logística propia**? (Propuesta v1: **solo propia** — instant-attack rompería el balance defensivo de
  SDD 62 y los topes SDD 55; dejar el salto ofensivo como v2 con fuerte costo/contramedida.)
- ¿Freno por **cooldown** del jumper o por **combustible** (un mineral avanzado por salto)? (Propuesta:
  cooldown + energía; combustible como v2 si hace falta más fricción.)
- ¿`space_jump` se modela con `requires_techs: [...]` (multi-prereq nuevo) o encadenado +
  `prerequisites` del grafo? (Definir al implementar; preferible multi-prereq explícito.)

## 7. Rollout / riesgos
- Aditivo y data-driven (1 tech capstone + 1 unidad + endpoint/lógica acotada sobre SDD 62). Flag
  `space_jump_enabled` (default OFF hasta balancear, gateado por un árbol carísimo). Va por el pipeline
  de Argo. e2e + tests (regla del proyecto).
- Riesgo: logística instantánea es fuerte → mitigan el costo del árbol completo, la capacidad chica, el
  costo de energía y el cooldown; y que en v1 NO sea ofensivo. Depende de implementar antes SDD 61.
