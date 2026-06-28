# SDD 50 — Drones intra-planeta: espías orbitales (tiempo real) + ataque

> **Estado:** **implementado (flag OFF)** · **Fecha:** 2026-06-27 (impl. 2026-06-28)
> Mecánica lazy + API + grafo + tests/e2e listos detrás de `drones_enabled` (default off). Pendiente
> v1.5: prender el flag tras balance, panel web pictográfico (calculadora de duración) y uso por el
> NPC. Ver CHANGELOG 2026-06-28.

> **Estado original:** **diseño** (no implementado) · **Fecha:** 2026-06-27
> **Relacionado:** SDD 35 (espionaje — los drones son su evolución "en vivo"), SDD 49 (misiles —
> hermano), SDD 47 (energía/upkeep), SDD 46 (alojamiento), SDD 1 (grafo), SDD 43 (UI pictográfica),
> SDD 13 (combate), `content/{buildings,units,technologies}.yaml`, `app/services/*`.

## 1. Objetivo
Una **fábrica de drones** que produce **drones intra-planeta** (NO van a otros planetas). Dos familias:
1. **Drones espía** (3 tipos, durabilidad/consumo crecientes): **orbitan** el objetivo y dan **intel en
   tiempo real** mientras tengan energía. Mejores que el espía clásico (SDD 35: snapshot puntual) →
   acá ves **qué pasa ahora**, continuo. **Consumen TU energía** mientras orbitan; al quedarse sin
   energía **mueren**. El enemigo solo los derriba si tiene **torretas** (depende de cuántas/cuáles y
   de cuántos drones mandes). 
2. **Drones de ataque masivo:** oleada que castiga la base objetivo (también orbitan, drenan energía y
   caen ante torretas).

Todo **data-driven**, en el **grafo**, **lazy por timestamp** (sin crons; el consumo y los derribos se
calculan al leer, como energía/producción) y con **panel pictográfico** para calcular cuánto durarán.

## 2. Tecnologías y edificio (grafo)
`technologies.yaml` (categoría `drones`, requieren `research_lab`):

| Tech | Depende de | Habilita |
|---|---|---|
| `dronework` (Dronística) | — | edificio `drone_factory` + dron espía liviano |
| `drone_endurance` (Autonomía) | `dronework` | drones espía medio/pesado (más durables) |
| `attack_drones` (Drones de ataque) | `dronework` | drones de ataque masivo |

Edificio `drone_factory` (`buildings.yaml`, category `drones`): `requires: research_lab`,
`requires_tech: dronework`, `houses: { drone: N }` (dominio nuevo `drone`, SDD 46; arranque 12).

## 3. Unidades dron (atributos data-driven)
`units.yaml`, `domain: drone`, `range: intra_planet`. Atributos nuevos por dron:
`hp` (durabilidad), `energy_per_tick` (consumo mientras orbita), `intel_quality` (0..1, profundidad de
la intel en vivo), `attack` (solo los de ataque).

| Dron | tech | rol | `hp` | `energy_per_tick` | `intel_quality` / `attack` | costo (roles) |
|---|---|---|---|---|---|---|
| `recon_drone` 🛸 (liviano) | dronework | espía | 20 | 1.0 | intel 0.6 | structural 30, energetic 30, advanced 10 |
| `recon_drone_mk2` 🛰 (medio) | drone_endurance | espía | 45 | 2.0 | intel 0.8 | structural 50, energetic 50, advanced 25 |
| `recon_drone_mk3` 📡 (pesado) | drone_endurance | espía | 90 | 4.0 | intel 0.95 | structural 90, energetic 80, advanced 50 |
| `strike_drone` 🤖 (ataque) | attack_drones | ataque | 35 | 3.0 | attack 25 | structural 70, energetic 60, advanced 40 |

> Trade-off del pedido: **más durable (hp↑) ⇒ más consumo (energy_per_tick↑)**. El pesado aguanta más
> torretas pero te drena la energía más rápido → menos duración por la misma energía. Elegís según si
> el problema es **las torretas** (→ pesado) o **tu energía** (→ liviano, o mandás pesados solo si
> estás "energy-rich", como dijiste).

## 4. Matemática (determinista, lazy por timestamp) — el corazón del pedido

### 4.1 Supervivencia vs torretas
El defensor tiene `antiair = Σ ( turret.antiair_power )` (torretas activas) `× defense_mult`. Cada
**tick** que el escuadrón orbita, las torretas reparten ese fuego sobre los drones:
```
daño_por_tick   = antiair
hp_total_vivo   = Σ ( hp(dron) )  de los drones aún vivos
derribados_tick = min( drones_vivos , floor( daño_por_tick / hp_promedio_efectivo ) )
```
- **Más drones ⇒ más `hp_total` ⇒ tardan más ticks en caer todos** (las torretas no escalan con tu
  enjambre): "depende de cuántos mandes". 
- **Drones más durables (hp↑) ⇒ menos derribos por tick.** 
- **Sin torretas (`antiair = 0`) ⇒ no muere ninguno por fuego** (solo por energía, §4.2): "solo si
  tienen torretas los pueden ir matando".
- `vida_por_torretas (ticks) ≈ (Σ hp del escuadrón) / max(1, antiair)`  (cota superior; se simula tick
  a tick para repartir bien).

### 4.2 Energía y duración (lo que calculás en el panel)
Mientras orbitan, drenan TU energía: `drenaje = Σ ( energy_per_tick(dron vivo) )`. Tu energía regenera
`regen` (SDD 47). El **balance por tick** = `regen − drenaje`.
```
si drenaje ≤ regen:  duran indefinido por energía (se sostienen solos) → el límite es las torretas
si drenaje >  regen:  vida_por_energia (ticks) = energía_actual / (drenaje − regen)
```
Al llegar la energía a 0 (o si los **retirás**), **mueren/vuelven**. 

### 4.3 Vida efectiva e intel
```
vida_efectiva (ticks) = min( vida_por_torretas , vida_por_energia , tope_que_elegís_en_el_panel )
```
- Mientras quede **≥1 dron espía vivo**, recibís **intel en tiempo real** del objetivo con profundidad
  = `max(intel_quality de los drones vivos)` (mejor que SDD 35, que era un snapshot que se desactualiza).
- Drones de ataque: por tick aplican `Σ attack` × `attack_mult` al `defense_score`/edificios del
  objetivo mientras vivan → "oleada" sostenida (cuanto más duren, más daño; por eso conviene energía).

## 5. Intra-planeta (no salen del planeta)
- `range: intra_planet` (dron) + validación: el objetivo debe estar en el **mismo planeta** que la
  `drone_factory` desde la que despachás. **Construir** drones se puede en cualquier planeta tuyo;
  **enviarlos** fuera del planeta **no** (error claro). (Coherente con "solo dentro del planeta".)

## 6. Estado lazy (sin crons)
- Un **escuadrón** orbitando es una fila (`DroneSquadron`: owner, target_base, {dron:qty vivos},
  `last_tick_at`, `status`). Al leer (`/players/me` o el panel), un `advance_drones()` calcula los ticks
  transcurridos: aplica derribos (§4.1), drena energía (§4.2), aplica daño de ataque, y **mata el
  escuadrón** si energía=0 o no quedan drones. Igual que `collect_mines`/`advance` (SDD 47): barato,
  determinista, sin worker dedicado.
- Intel en vivo = derivada del escuadrón vivo (no se "guarda" desactualizada como SDD 35).

## 7. Exposición data-driven + IA
- `/catalog`: techs `drones`, `drone_factory`, drones con `hp`/`energy_per_tick`/`intel_quality`.
- `/catalog/graph`: `dronework→drone_factory`, `drone_factory→recon_drone`, `drone_endurance→mk2/mk3`,
  `attack_drones→strike_drone`, `turret→shoots_down→drone`. Grounding `mech_drones` (la matemática §4
  con números) → el asistente explica "para que duren X ticks con Y torretas enemigas, mandá N mk2 y
  tené E energía"; el **NPC** decide espiar-en-vivo/atacar con drones y retirarlos antes de quedarse
  sin energía.
- `/players/me`: bloque `drones` (escuadrones propios: vivos, drenaje, ETA de muerte por energía) +
  `intel_live` por objetivo.
- Helper puro `simulate_drones(squadron, antiair, energy, regen)` → calculadora + tests.

## 8. UI — panel pictográfico (SDD 43, "sin leer") — pedido explícito
- Panel **Drones** (intra-planeta): selector de objetivo (mismo planeta), contadores por tipo de dron.
- **Calculadora de duración (clave):** sliders pictográficos "cuántos drones" + lectura en vivo:
  🔋 barra de energía con **ETA** ("durarán ⏳ N ticks"), 🛡 estimación de derribos por las torretas
  del rival (de tu intel), 👁 calidad de intel. Todo con íconos y barras, **sin texto**:
  - 🛸/🛰/📡 espía liviano/medio/pesado, 🤖 ataque.
  - chip "drenaje 🔋−X/h vs regen +Y/h" → verde si se sostiene, rojo si se agota (con ⏳ETA).
  - botón ▶ lanzar / ⏹ retirar (traer de vuelta antes de que mueran).
- Mientras orbitan: mini-feed pictográfico del objetivo en vivo (iconos de lo que ve la intel).

## 9. API
- `POST /drones/launch {factory_base_id, target_base_id, force:{drone:qty}, max_ticks?}` → despacha
  escuadrón (valida tech, mismo planeta, `drone` libre, energía).
- `POST /drones/{squadron_id}/recall` → los trae de vuelta (sobreviven).
- `POST /drones/simulate {force, antiair, energy, regen}` → duración/derribos/intel (calculadora).
- `GET /players/me` extendido (bloque `drones` + `intel_live`).

## 10. Tests / validación
- **Pureza:** `simulate_drones` — sin torretas no muere ninguno; más drones ⇒ más vida; más durables ⇒
  menos derribos/tick; drenaje>regen ⇒ muerte por energía en el ETA calculado; intel = max quality vivo.
- **Servicio:** lanzar sin tech ⇒ error; objetivo de otro planeta ⇒ error; `advance_drones` mata por
  energía y por torretas; ataque baja defense_score por tick.
- **e2e** (`tests/test_api_e2e.py`): fábrica+tech → lanzar recon → ver `intel_live` → quedarse sin
  energía → escuadrón muere; recall trae de vuelta; strike_drone daña.
- **IA:** grounding `mech_drones` recuperable; NPC retira drones antes de morir y no los manda
  interplanetario.

## 11. Rollout / riesgos
- Flag `drones_enabled` (default off). Balance por YAML (`hp`/`energy_per_tick`/`antiair_power`).
- **No invalida el espionaje (SDD 35):** el espía clásico es barato y de un tiro; los drones son caros,
  continuos y arriesgados (energía/torretas) → coexisten (snapshot vs vivo).
- **Anti-abuso:** el drenaje de energía es el freno natural (no podés tener un enjambre eterno gratis);
  newbie protection (SDD 11) aplica; intra-planeta acota el alcance.
- Comparte el dominio de alojamiento y el modelo de energía con SDD 46/47 → "todo tiene un tope físico"
  y "todo consume energía".
