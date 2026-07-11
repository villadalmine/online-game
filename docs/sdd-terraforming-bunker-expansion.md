# SDD 75 — Terraformación (búnker más grande)

## Problema
La expansión subterránea (SDD 69, `dig_deeper`) agranda el búnker de a **+1 lado por excavación**,
cara y lenta. El usuario pidió una vía de **salto grande** de tamaño, gateada por research y con un
edificio propio.

## Diseño (data-driven, sin migración)
- **Tech `terraforming`** (`content/technologies.yaml`, categoría `underground`, requiere
  `underground_construction`). Nadie la tiene hasta investigarla.
- **Sala `terraformer`** (`content/underground.yaml`, `requires_tech: terraforming`) con un campo
  nuevo **`grid_bonus: 3`**. Mientras esté **activa**, suma su bonus al **lado de la grilla** de ese
  búnker (y sube también el tope, para poder seguir excavando).
- **Flag** `terraforming_enabled` (default OFF; ON en `values-prod.yaml`).

## Implementación
- `bunkers.grid_side(bunker, settings, bonus=0)` — el lado efectivo ahora acepta el bonus de
  terraformación (`min(bunker_grid_max + bonus, bunker_grid + grid_level + bonus)`).
- `bunkers.grid_bonus(session, bunker_id, settings)` — suma `grid_bonus` de las salas `terraformer`
  ACTIVAS (0 si el flag está OFF). Data-driven: el bonus vive en el YAML de la sala.
- `dig_deeper` / `build_room` / `bunker_state` computan el bonus y lo pasan a `grid_side` → el mapa
  subterráneo crece y habilita más celdas.
- **Front**: cero cambios (la sala sale sola en el selector del búnker y la tech en Investigación; el
  `side` del snapshot ya dibuja la grilla más grande).

## Balance
`grid_bonus=3` lleva un búnker de 4×4 (16 celdas) a 7×7 (49) de una. Costo alto de la sala
(`structural 600 / energetic 300 / advanced 400`) + energía + tiempo de obra + el costo de la tech.
Ocupa 1 celda (neto muy positivo). Reversible por flag.

## Tests
- `tests/test_bunkers.py::test_terraformer_room_enlarges_bunker` (servicio: +3 lado con sala activa;
  0 con el flag OFF).
- `tests/test_api_e2e.py::test_terraformer_enlarges_bunker_e2e` (happy path por HTTP + error de sala
  desconocida).

## Follow-ups
- Salto cuántico / teletransportador entre búnkeres (SDD 76): mover electrónica de un búnker a otro.
- IA conversacional que actúa (SDD 77).

## Addendum (2026-07-11, v1.207.0) — tope de excavaciones y demolición

Bug de UX reportado: en el tope de excavaciones (`grid_level=4` → 8×8) el juego se contradecía
("excavá para agrandarlo" al construir vs "ya está en su tamaño máximo" al excavar), y con el búnker
**lleno** en 8×8 era un deadlock real: sin celda libre no entraba ni el Terraformador. El bonus de
terraformación NO habilita más excavaciones (sube lado y tope por igual): 11×11 se ve solo con la
sala activa. El autopiloto (SDD 85) excava solo al fallar un build, así que llegar al tope "sin
darse cuenta" es lo esperable. Arreglos (`fix(búnker)` 65aeb69):

- Mensaje del tope explica la salida: `"Tope de excavaciones alcanzado (8×8). Un Terraformador
  activo la agranda (+3 de lado, tech Terraformación)."` (data-driven: lee `grid_bonus` del YAML).
- **`POST /api/v1/bunker/demolish-room`** (`bunkers.demolish_room`): libera la celda, sin reembolso.
  Guardas: no dejar salas fuera del mapa (demoler un terraformador achica la grilla) ni material
  perdido (bóveda cuyo contenido no cabría — vaciar primero). Demoler una sala "en obra" funciona
  como cancelar construcción (sin reembolso). Journal: `bunker_demolish_room`.
- Front: botón ⛏ se apaga en el tope (`bunker_grid_max` ahora sale en `/catalog` → costs; ojo cache
  Redis 300s), click en una sala del corte lateral = demoler (con confirm), y la bóveda muestra el
  desglose `usado/capacidad (N 🗄 × vault_storage)`.
- Tests: `test_bunkers.py::test_dig_deeper_cap_message_suggests_terraformer`,
  `::test_demolish_room_frees_cell_and_guards`, `test_api_e2e.py::test_bunker_demolish_room_e2e`.
