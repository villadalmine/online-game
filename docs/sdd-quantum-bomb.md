# SDD 87 — Bomba cuántica (gusano de IA que infecta, drena y extorsiona)

Idea del usuario. Decisiones confirmadas: **lanzamiento intra-planeta** (arsenal), **release completo**,
**las NPC también la usan**.

## Mecánica
- **Munición `quantum_bomb`** (`domain: ordnance`, gate `quantum_warfare` que requiere `quantum_jump`).
  Se fabrica en la lanzadera y se lanza como un misil intra-planeta (reusa SDD 49): viaja, es
  interceptable por torretas (`intercept_cost: 40` ≈ 4 torretas para bloquearla) y `power: 0` (no
  destruye edificios; su efecto es la INFECCIÓN).
- **Al impactar** (`strike._resolve_strike` → `quantum.on_bomb_impact`): crea una `QuantumInfection` en
  la base y **DRENA** — roba `quantum_drain_fraction` (50%) de los minerales del planeta al atacante +
  esa fracción de la energía del defensor.
- **Penalización progresiva:** mientras la infección está `active`, penaliza la PRODUCCIÓN del jugador
  (player-wide, "el gusano se reproduce") de **1% → `quantum_max_penalty` (80%)** lineal en
  `quantum_decay_days` (7). Se aplica en `effects.multiplier('production')` (derivado del tiempo, sin
  persistir el %).
- **Desactivar (3 formas):** (a) **tropas** — `quantum_disarm_soldiers` soldados en la base (purga);
  (b) **rescate** — paga `quantum_ransom_fraction` (30%) del stock al atacante (el chantaje); (c)
  **tech cuántica** (`quantum_warfare` investigada) — gratis, PERO deja `leaking=True`: la base se
  transmite al atacante (mapa 100% permanente, SDD 61) **hasta que orbite un satélite `inhibitor`**
  (que se degrada como cualquier satélite → hay que reponerlo).

## Piezas
- **Modelo:** `QuantumInfection` (migración `8587a5090248`).
- **Servicio:** `app/services/quantum.py` (penalty, on_bomb_impact, disarm_troops/ransom/quantum,
  has_active_inhibitor, leaked_base_ids, infection_state).
- **Hooks:** `strike._resolve_strike` (impacto→infección), `effects.multiplier('production')`
  (penalización), `satellites.satellites_state` (fuga→enemy_map del atacante; `launch` deja al
  inhibidor orbitar tu planeta), snapshot `state.py` → `quantum_infection`.
- **Content:** tech `quantum_warfare`, units `quantum_bomb` + `inhibitor_satellite`.
- **API:** `POST /quantum/disarm/{troops|ransom|quantum}`. Lanzar = arsenal existente (`/combat/strike`).
- **Front:** panel de infección + botones desactivar (en el Arsenal); `quantum_bomb` aparece solo en el
  arsenal y `inhibitor_satellite` en satélites. Feature flag `quantum_bomb`.
- **NPC (usan la bomba):** `_npc_state` expone `my_infection` + `can_quantum_bomb`; `dispatch_action`
  suma `quantum` (lanzar) y `quantum_disarm`; el prompt las explica.
- **Flags:** `QUANTUM_BOMB_ENABLED` (values-prod ON). Anti-abuso: gate tech + intercept + reusa topes.

## Tests
- `tests/test_quantum.py`: impacto infecta+drena, penalización crece, disarm tropas/rescate/tech,
  fuga hasta inhibidor. e2e `test_quantum_infection_disarm_e2e` (snapshot + disarm por API).

## v2 (HECHO) — anti-farmeo + autopiloto defensivo + reporte del drenaje
- **Anti-farmeo:** `quantum.can_launch_bomb` (llamado desde `start_strike` cuando la salva trae
  `quantum_bomb`): rechaza re-infectar una base ya infectada, y 1 bomba por par (atacante→defensor)
  cada `quantum_cooldown_hours` (24). Test `test_antifarm_no_reinfect_and_cooldown`.
- **Autopiloto defensivo:** skill `quantum_defense` (grafo SDD 78, nivel 5) → `_auto_quantum_disarm`:
  si tu base está infectada, la desactiva sola con tech cuántica (si la tenés) o con tropas; NO paga
  rescate (decisión cara, queda para el jugador). Test `test_auto_quantum_disarm`.
- **Reporte del drenaje:** `_resolve_strike` guarda `details["quantum"]` (`{stolen, energy_drained}`)
  en el CombatLog del strike → el reporte muestra qué robó la bomba.
