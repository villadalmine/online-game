# SDD 62 — Guarnición: tropas estacionadas por base + mover tropas entre planetas

> **Estado:** **DISEÑO** 2026-06-30 (sin implementar) · **Pedido:** usuario, 2026-06-30 (eligió
> "guarnición real" sobre dejar el ejército global).
> **Relacionado:** [SDD 46 alojamiento por edificio/base](sdd-unit-housing-capacity.md) (ya es por
> base — la guarnición lo vuelve coherente), [SDD 42 stock de minerales por planeta](sdd-per-planet-stocks.md)
> (mismo patrón para unidades), [SDD 47 minería/staffing](sdd-mining-workers-storage.md),
> combate con viaje (`app/services/combat.py`), [SDD 60 paneles por planeta](sdd-collapsible-planet-panels.md),
> `app/models/__init__.py` (`UnitStock`), `app/services/training.py`, `app/services/state.py`.

## 1. Problema (usuario, 2026-06-30)
En "Tu imperio" las unidades salen en **global**, no por planeta. Hoy el ejército es **uno solo que
defiende TODAS tus bases a la vez** (`combat.py`: `defender_force = player_units(defender.id)` = todas
las unidades; `UnitStock` guarda `(player_id, unit_key)` sin base/planeta). El usuario quiere que las
tropas estén **estacionadas por base/planeta** y que **solo las de la base atacada defiendan**, pudiendo
**mover tropas** entre planetas.

## 2. Decisión de diseño
- **Las unidades pasan a ser POR BASE** (`UnitStock` suma `base_id`). El combate del defensor usa **solo
  las unidades de la base atacada** (las torretas/edificios ya eran por base). El ataque **sale de una
  base** (la fuerza se descuenta de esa base). Mover tropas = **misión con tiempo de viaje** (como una
  transferencia, reusa el patrón de `TransportMission`/`AttackMission`).
- **Por base, no por planeta**: el combate apunta a `target_base_id` y un planeta puede tener varias
  bases (superficie/orbital/lunar, SDD 37). El **panel** agrupa por planeta (suma sus bases) reusando
  SDD 60 (colapsable).
- **Alojamiento (SDD 46) se vuelve coherente**: hoy las plazas son por edificio (por base) pero la
  ocupación se cuenta global; con guarnición, ocupación y plazas son **ambas por base** → el headroom
  por base es real (cierra la inconsistencia que ya se sentía en SDD 56).
- **Rollout detrás de flag** `garrison_enabled` (default **OFF**): con OFF, comportamiento actual
  (ejército global) — no rompe balance en vivo; con ON, guarnición. Igual que 46/47/49/50.

## 3. Cambios concretos
### 3.1 Modelo + migración
- `UnitStock`: nueva columna `base_id` (FK `bases.id`, nullable para compat OFF), unique
  `(player_id, unit_key, base_id)`. Migración Alembic: para filas existentes, `base_id = base natal`
  del jugador (su HQ). Helper `units_at_base(session, base_id)` y `player_units` sigue existiendo
  (suma global, para vistas/agregados y para el modo OFF).
- Nuevo modelo **`TroopMove`** (o reusar `TransportMission` con `cargo` de unidades): `player_id`,
  `from_base_id`, `to_base_id`, `units` (json), `arrives_at`, `status`. Se resuelve lazy/al tick
  (deposita en `to_base` al llegar). Bloquea las unidades en tránsito (salen del `from_base`).

### 3.2 Servicios
- **Entrenamiento** (`training.py`): `start_training` YA recibe `base` → al completar, depositar en
  `UnitStock(base_id=base.id)` (con OFF: base natal / global como hoy).
- **Combate defensor** (`combat.py`): con ON, `defender_force = units_at_base(target_base_id)` (solo esa
  base). Con OFF, el global de hoy. Sobrevivientes vuelven a ESA base. El piso de obreros (SDD 54) se
  aplica por base.
- **Ataque** (`combat.py:start_attack`): la `force` se descuenta del `from_base` elegido (nuevo campo
  `source_base_id`, default = base natal). Los sobrevivientes vuelven a esa base.
- **Alojamiento** (`housing.py`): `housing_report` por base (plazas y ocupación de ESA base). El panel
  de capacidad (SDD 60) ya está listo para por-planeta.
- **Minería/staffing** (`economy.py:mining_staffing`): hoy es GLOBAL (pool de obreros global ÷ todas las
  minas). Con obreros por base pasa a ser **por base/planeta**: cada planeta muestra sus obreros vs sus
  minas (cierra el pedido "capacidad solo agrupa almacén, no minería/trabajadores"). El panel de
  capacidad (SDD 60) ya agrupa almacén por planeta; con esto, **minería y alojamiento también** por
  planeta.
- **Expediciones/strike/drones**: las unidades requeridas (transbordador, misiles, drones) se toman de
  la base que lanza (coherencia; con OFF, global).
- **NPC** (`npc.py`): entrena/defiende/ataca desde sus bases; mueve tropas a la frontera amenazada.

### 3.3 API
- `POST /bases/{id}/move-troops` `{to_base_id, units}` → crea `TroopMove` (valida que las unidades
  estén en `from_base`, alojamiento en destino, tiempo de viaje por distancia intra/inter-planeta).
- `POST /combat/attack` suma `source_base_id` (opcional; default natal).
- Snapshot `/players/me`: `units` global (compat) **+** `units_by_base` (`{base_id: {unit: qty}}`) y
  `troop_moves: [...]`. El front arma el "por planeta" sumando las bases del planeta.

### 3.4 UI (`web/index.html`)
- **Tu imperio**: unidades **agrupadas por planeta/base**, colapsable (SDD 60). Con OFF, el global de
  hoy + nota "ejército global".
- **Entrenar**: ya elegís base; el headroom de plazas (SDD 56) pasa a ser de ESA base (real).
- **Atacar**: selector de **base de origen** (de dónde salen las tropas).
- **Mover tropas**: mini-panel (base origen → base destino + cantidades + ETA), como el transporte de
  minerales (SDD 42).

## 4. Balance / riesgos
- **Cambia el balance defensivo**: hoy una guarnición + torretas cubre todo; con guarnición tenés que
  **defender cada colonia** → colonizar tiene un costo defensivo real (bueno para el juego, pero hay que
  recalibrar protección de novato y los topes de ataque SDD 55 para que no farmeen colonias indefensas).
- **Riesgo de quedar trabado** (cruza SDD 54): el piso de obreros se aplica **por base**; cuidar que
  perder una colonia no te deje sin economía global.
- **Mitigación de rollout**: flag OFF por default; prender en prod recién tras balancear con datos
  (mover el `min_surviving_workers`, novato por base, etc.). e2e que cubran ON y OFF.

## 5. Tests (regla del proyecto)
- `test_combat.py`: con ON, atacar la base A no usa las unidades de la base B; sobrevivientes vuelven a
  su base; con OFF, comportamiento global de hoy (no romper los tests existentes).
- `test_training.py`: entrenar en una base deposita ahí (ON); housing por base topea.
- `test_troops_move.py`: mover tropas bloquea en origen, viaja, deposita en destino; respeta alojamiento.
- e2e (`test_api_e2e.py`): flujo completo ON (entrenar en colonia → te atacan la colonia → pelean solo
  esas → mover refuerzos desde el natal). e2e OFF: el global sigue igual.

## 6. Rollout
- Aditivo + migración + flag. Va por el pipeline de Argo. Implementar en pasos: (1) modelo+migración+
  `base_id` con flag OFF (no cambia nada visible) → (2) training/combate/housing por base tras el flag →
  (3) mover tropas + UI → (4) balance y recién ahí prender `garrison_enabled` en prod.

## 7. Preguntas abiertas
- ¿La fuerza de ataque sale de UNA base o se puede combinar de varias (rally)? (Propuesta v1: una base.)
- ¿El tiempo de mover tropas intra-planeta es 0/instantáneo y solo inter-planeta tiene viaje?
  (Propuesta: intra-planeta rápido, inter-planeta usa la distancia como el ataque/transporte.)
- ~~¿Los obreros/científicos (no combatientes) también se estacionan?~~ **RESUELTO (usuario 2026-06-30):
  SÍ, por base** — el usuario pidió que la capacidad muestre minería/trabajadores por planeta, lo que
  exige obreros por base. Mismo cambio que las tropas.
