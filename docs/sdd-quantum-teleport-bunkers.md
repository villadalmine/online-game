# SDD 76 — Salto cuántico: teletransporte de electrónica entre búnkeres

## Problema
La **electrónica** (moneda de reserva del búnker: repuebla edificios tras un ataque y sube la vida
artificial) queda atrapada en el búnker donde se produce. Si te arrasan una base, no podés mover esa
reserva a otra para recuperarte. El usuario pidió un teletransportador para consolidar.

## Diseño (data-driven, sin migración)
- **Tech `quantum_jump`** (`content/technologies.yaml`, rama `underground`, requiere `artificial_life`).
- **Sala `quantum_gate`** (Puerta cuántica, `content/underground.yaml`, `requires_tech: quantum_jump`)
  con el marcador **`teleporter: true`**. El búnker **origen** necesita una Puerta cuántica ACTIVA.
- **Acción**: `POST /bunker/teleport {from_base_id, to_base_id, amount}` → mueve electrónica del búnker
  origen al destino, **instantáneo**, con una **merma** `quantum_teleport_fee` (10%).
- **Flag** `quantum_teleport_enabled` (default OFF; ON en `values-prod.yaml`).

## Implementación
- `bunkers.quantum_teleport(...)` — valida flag, búnkeres del jugador y distintos, puerta activa en el
  origen (`_has_teleporter`), electrónica suficiente; `advance_bunker` primero (electrónica lazy al
  día); descuenta del origen y acredita al destino menos la merma; `journal.record("quantum_teleport")`.
- `POST /bunker/teleport` (`app/api/v1/bunker.py`) con `QuantumTeleportRequest`.
- **Front** (`renderBunker`): si hay ≥2 búnkeres y alguno tiene `quantum_gate` activa, muestra un
  control origen→destino + cantidad + botón ⚛; `bunkerTeleport()` pega al endpoint. La sala/tech salen
  solas del catálogo. La historia rotula `quantum_teleport` como "⚛ teletransportes".

## Balance
Merma del 10% (`quantum_teleport_fee`) → mover no es gratis. Costo alto de la sala + la tech (requiere
vida artificial). Reversible por flag.

## Tests
- `tests/test_bunkers.py::test_quantum_teleport_moves_electronics` (servicio: mueve −merma; falla sin
  puerta / mismo búnker).
- `tests/test_api_e2e.py::test_quantum_teleport_e2e` (happy path por HTTP + error sin electrónica).

## Follow-ups
- v2: teletransportar también minerales de la bóveda (hoy solo electrónica, como pidió el usuario).
- SDD 77: IA conversacional que puede DISPARAR este teletransporte a pedido.
