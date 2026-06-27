# SDD 49 — Lanzadera de misiles (guerra intra-planeta)

> **Estado:** **diseño** (no implementado) · **Fecha:** 2026-06-27
> **Relacionado:** SDD 1 (grafo + asistente), SDD 13 (combate/rigor), SDD 47 (energía), SDD 46
> (alojamiento), SDD 43 (UI pictográfica), SDD 50 (drones — hermano), `content/{buildings,units,
> technologies}.yaml`, `app/services/{combat,build,training,effects}.py`.

## 1. Objetivo
Una **lanzadera** (silo de misiles) que se construye en una base del planeta y dispara **misiles** a
bases enemigas **del mismo planeta** (intra-planeta; NO interplanetario). Tres tipos de misil con
**poder y dificultad de intercepción** crecientes, cada uno **detrás de su tecnología**:
**sónico → transatlántico → nuclear**. Todo **data-driven** y en el **grafo** (la IA arma la relación
sola). El misil es un golpe directo a la base objetivo, mitigado por las **defensas antimisil** del
rival (torretas) con una **fórmula determinista**.

## 2. Por qué encaja
- Reusa el modelo existente: edificio que **gatea** unidades (como fábrica→tanque), unidad con `cost`
  por roles, `requires`/`requires_tech` (SDD 1), combate con viaje corto (SDD 13), energía (SDD 47).
- Es **aditivo**: nuevas entradas de YAML + un resolver de combate de misiles. Detrás de flag.

## 3. Tecnologías (árbol, data-driven `requires_tech`)
Nuevas en `technologies.yaml` (categoría `strike`, requieren `research_lab`):

| Tech | Depende de | Habilita | Efecto |
|---|---|---|---|
| `rocketry` (Cohetería) | — | edificio `launcher` + `sonic_missile` | — (gate) |
| `ballistics` (Balística) | `rocketry` | `cruise_missile` (transatlántico) | — (gate) |
| `nuclear_fission` (Fisión nuclear) | `ballistics` | `nuclear_missile` | — (gate) |

> Las tres son **gate** (no dan multiplicador). La relación es explícita en el grafo:
> `rocketry → launcher → sonic_missile`, `ballistics → cruise_missile`, `nuclear_fission →
> nuclear_missile`.

## 4. Edificio nuevo: `launcher`
`buildings.yaml` (category `strike`):
- `requires: research_lab`, `requires_tech: rocketry`.
- `houses: { ordnance: N }` — los misiles ocupan un **dominio de alojamiento nuevo** `ordnance`
  (SDD 46): el silo guarda misiles; sin lanzadera no podés acumular. (Arranque: `ordnance: 6`.)
- `launch_energy: <int>` — energía por salva (además del costo del misil).
- `range: intra_planet` — atributo declarativo: el objetivo debe estar en el **mismo planeta**.

## 5. Misiles (unidades-munición, domain `ordnance`)
`units.yaml` (grupo nuevo `ordnance` o dentro de `heavy` con `domain: ordnance`). Atributos clave:

| Misil | tech | `power` (daño) | `intercept_cost` (cuánta defensa antimisil cuesta derribarlo) | `housing_size` | costo (roles) | ⚡ |
|---|---|---|---|---|---|---|
| `sonic_missile` 🚀 | rocketry | 60 | 1 (fácil de interceptar, pero barato → enjambre) | 1 | structural 40, energetic 30 | 6 |
| `cruise_missile` 🛩 | ballistics | 160 | 3 | 2 | structural 120, energetic 80, advanced 40 | 12 |
| `nuclear_missile` ☢ | nuclear_fission | 600 + **área** | 8 (muy difícil de interceptar) | 4 | structural 400, energetic 250, advanced 300 | 30 |

- `power` = daño que aplica al **defense_score**/edificios de la base objetivo al impactar.
- `nuclear` agrega **daño de área**: golpea defensa + daña edificios (los pasa a `building` con timer
  de reparación, o baja su nivel — decisión de balance) y deja un modificador temporal "fallout"
  (−producción) en ese planeta del defensor (gancho a SDD 36 eventos).
- Atributos de rigor (SDD 13): `propulsion: rocket`; el nuclear puede requerir `helium3`/material
  premium como parte del costo (endgame).

## 6. Mecánica de combate (determinista) — §"hace la relación matemática"
Una **salva** = `{misil: cantidad}` lanzada desde una `launcher` activa a una base enemiga del mismo
planeta. Resolución pura (como `resolve_combat`, testeable sin DB):

```
intercept_capacity = Σ ( turret.intercept_power )  de las torretas ACTIVAS del defensor
                     × defense_mult(defensor)        # tech 'shields' + boons + alianza (SDD 1)
# se reparte la capacidad de intercepción sobre los misiles entrantes, por orden de intercept_cost
# (primero los baratos/fáciles). Un misil es interceptado si queda capacidad ≥ su intercept_cost:
restante = intercept_capacity
para cada misil (orden asc por intercept_cost):
    si restante ≥ misil.intercept_cost: interceptado++ ; restante -= misil.intercept_cost
    si no: impacta
daño_total = Σ ( misil_que_impacta.power ) × attack_mult(atacante)   # tech 'weapons' etc.
```
- **Consecuencia (la intuición del pedido):** muchas torretas ⇒ alta `intercept_capacity` ⇒ derriban
  más; **enjambre de sónicos** satura (cada uno cuesta poco interceptar, pero si mandás más que la
  capacidad, los que sobran impactan); el **nuclear** es casi imposible de frenar (intercept_cost 8)
  salvo mucha defensa, y si impacta hace daño masivo + área.
- **Resultado:** baja el `defense_score` del defensor (y daña edificios si nuclear); **no saquea por
  sí mismo** (el misil destruye, no roba) — sirve para **ablandar** una base antes de un ataque de
  flota (SDD 13) o de drones (SDD 50). El defensor recibe notificación + entra al feed de batallas
  (SDD 35, sin revelar unidades).
- **Intercepción nueva:** `turret` (existente) gana `intercept_power` (p.ej. 30); opcional edificio
  dedicado `aa_battery` (batería antiaérea) con `intercept_power` alto — abre un mini-árbol defensivo.

## 7. Intra-planeta (restricción declarativa)
- `launcher.range: intra_planet` → en `start_strike` se valida `target_base.planet_key ==
  launcher_base.planet_key`; si no, error claro ("los misiles no salen del planeta; usá una flota").
- Viaje corto determinista (reusa `travel_seconds_same_planet`, SDD 13) → la salva "vuela" y resuelve
  al llegar. Se puede **interceptar/avisar** en ese lapso (SDD 35 shared_vision para aliados).

## 8. Energía y costo
- Construir misiles: `cost` (roles→minerales del planeta, SDD 42) + `energy_cost` por unidad.
- Lanzar: `launcher.launch_energy` por salva. Sin upkeep (el misil se gasta al lanzarse).
- Tope: los misiles ocupan `ordnance` (SDD 46) → no infinitos sin ampliar lanzaderas.

## 9. Exposición data-driven + IA (grafo)
- `/catalog`: techs `strike`, edificio `launcher`/`aa_battery`, misiles con `power`/`intercept_cost`.
- `/catalog/graph`: aristas `rocketry→launcher`, `launcher→sonic_missile` (unlocks), `ballistics→
  cruise_missile`, `turret→intercepts→missile`. Grounding `mech_missiles` (cómo funciona la salva y la
  intercepción, con números) → el asistente y el **NPC** deciden cuándo ablandar con misiles.
- `/players/me`: salvas en vuelo (como `missions_outgoing`).
- Helper `simulate_strike(force, defender_turrets)` puro → para una **calculadora** (como SDD 34) y
  tests.

## 10. UI — incluye modo pictográfico (SDD 43, "sin leer")
- Panel **Atacar → Misiles**: selector de objetivo (mismo planeta), contadores por tipo, botón Lanzar.
- **Pictográfico:** íconos por misil (🚀 sónico / 🛩 transatlántico / ☢ nuclear) y por edificio
  (🗼 lanzadera / 🛡 antiaérea); chips de costo con ícono+símbolo de mineral; pre-cálculo inline
  "impactan X / interceptados Y" usando `simulate_strike` con tu intel del rival (SDD 35). Sin texto:
  ✓/❌ de afford, barra de daño estimado.
- Calculadora "¿cuántos sónicos para saturar N torretas?" (deriva de la fórmula §6).

## 11. API
- `POST /combat/strike {launcher_base_id, target_base_id, force:{missile:qty}}` → despacha salva.
- `POST /combat/strike/simulate {force, defender_turrets}` → resultado determinista (calculadora).
- `GET /catalog` extendido. Errores claros: sin tech, sin lanzadera, objetivo de otro planeta,
  sin `ordnance` libre.

## 12. Tests / validación
- **Pureza:** `simulate_strike` (intercepción por capacidad, enjambre satura, nuclear casi no se frena).
- **Servicio:** lanzar sin `rocketry` ⇒ error; objetivo de otro planeta ⇒ error; impacto baja
  `defense_score` y (nuclear) daña edificios; ocupa/consume `ordnance`.
- **e2e** (`tests/test_api_e2e.py`): construir launcher (con tech) → fabricar misiles → strike a base
  enemiga del mismo planeta → ver daño; caso error (interplanetario, sin tech).
- **IA:** grounding `mech_missiles` recuperable; NPC usa misiles para ablandar antes de atacar.

## 13. Rollout / riesgos
- Flag `strike_enabled` (default off) → contenido carga pero no se puede lanzar hasta prender.
- Balance: `power`/`intercept_cost`/`intercept_power` se afinan por YAML. Nuclear caro + premium para
  que sea endgame, no spam. Newbie protection (SDD 11) aplica.
- No rompe combate existente: es una vía paralela (golpe), la flota (SDD 13) sigue igual.
