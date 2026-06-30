# SDD 61 — Satélites: cosmódromo, mapeo orbital del enemigo, inhibidores de señal y escudos

> **Estado:** **IMPLEMENTADO (backend, flag OFF)** 2026-06-30 — techs/edificios/unidades + modelo
> `SatelliteMission` + `advance_satellites` (mapeo %, inhibidores, escudos, energía/órbita, destrucción
> por drones) + API `/satellites/*` + snapshot `satellites`/`enemy_maps`. **Pendiente:** panel web
> (mapa emergente) + NPC + prender `satellites_enabled`. · **Diseño:** 2026-06-30 · **Pedido:** usuario
> **Relacionado:** [SDD 50 drones intra-planeta](sdd-drones-intraplanet.md) (modelo lazy de orbitar +
> caída por antiaéreo — el satélite se modela igual), [SDD 35 espionaje](sdd-espionage.md) (intel de
> bases enemigas + visión de alianza), [SDD 37 colonización/órbita](sdd-colonization.md),
> [SDD 53 balance por rol](sdd-resource-balance.md), [SDD 13 rigor científico](sdd-scientific-accuracy.md),
> `content/{technologies,buildings,units}.yaml`, `app/services/drones.py`, `app/services/espionage.py`.

## 1. Idea (usuario, 2026-06-30)
Una **unidad satélite** que se construye/lanza desde una **base nueva tipo cosmódromo** ("de donde
salen los cohetes a la luna"), gateada por un **research de creación de satélites**. Hay **varios
tipos**:
- **Satélites propios**: orbitan **tu** planeta.
- **Satélites espía**: orbitan el planeta de un **enemigo** y te van **armando el mapa**: sus bases,
  cuántas unidades tiene cada base, y un **% de descubierto**. Cuantos más satélites tengas sobre ese
  enemigo, **más rápido** se llena. Por lo general **~2 días** para mapear un enemigo entero, **máx ~4
  días con uno solo**, pero depende de cuántos **inhibidores de señal** tenga el enemigo.
- **Inhibidor de señal** (edificio): protege tus bases del mapeo. Necesita su propio research
  (**señales avanzadas**). Cada inhibidor protege "tanto" hasta llegar al **100%**; **cuanto más tenés
  (más edificios), más inhibidores necesitás** (hay que calcular el ratio).
- Los satélites pueden ser **destruidos**: si el enemigo tiene **drones** en sus bases, al azar lo ven
  pasar y lo bajan.
- **Escudo de satélite**: mejora por research, **grados 1–3** (cambia el material, más resistente a los
  disparos de drones), pero la **energía va bajando al orbitar** → calcular el período orbital. **Vida
  útil ~1 semana** (se degrada o se la bajan).
- **Panel emergente**: clic → ves un **mapa de los enemigos**, sus bases, unidades por base y el **%
  descubierto** de cada uno.

## 2. Cómo encaja con lo existente (no reinventar)
- **Drones (SDD 50)** ya modelan "orbitar lazy-by-timestamp + drenar energía + caer ante antiaéreo +
  intel en vivo" (`DroneSquadron`, `advance_drones`, `squadrons_state`→`intel_live`). El satélite es el
  **primo estratégico**: en vez de intel de UNA base, mapea **TODO el planeta** del enemigo de a poco
  (un %), y vive **días** (no minutos). Reusamos el patrón (modelo + `advance_*` + snapshot).
- **Espionaje (SDD 35)** da una **foto puntual** de una base (misión que va y vuelve). El satélite es
  **persistente y acumulativo** (mapa completo creciente). Coexisten: el espía es rápido y barato para
  una base; el satélite es caro, lento y total.
- **Diferenciación clara** (que cada mecánica tenga sentido): espía = 1 base, ya; dron = 1 base, en
  vivo, frágil, drena TU energía; **satélite = planeta entero, % creciente, dura ~1 semana, lo bajan
  los drones del rival**.

## 3. Diseño data-driven
### 3.1 Research (nombres elegidos)
Cadena nueva en `technologies.yaml`:
- **`satellite_tech`** — "Tecnología satelital". Habilita el cosmódromo y los satélites. Prereq:
  `antigravity` (ya gatea lo orbital, SDD 37). Categoría nueva `orbital`.
- **`advanced_signals`** — "Señales avanzadas". Habilita el edificio inhibidor. Prereq:
  `counter_espionage` (línea defensiva de guerra electrónica). Categoría `espionage`.
- **`sat_shield_mk1` → `sat_shield_mk2` → `sat_shield_mk3`** — "Blindaje de satélites I/II/III". Cadena
  GATE (como rocketry→ballistics→nuclear). Prereq de mk1: `satellite_tech` + `shields`. Cada grado:
  más resistencia a drones, **pero más drenaje de energía** (vida útil más corta). Categoría `orbital`.

Costos por ROL (SDD 53): `energetic`+`advanced` dominante (alta tecnología, casi fin de juego). El
inhibidor, al ser defensa, lleva `structural`+`advanced` (defensa pagable con tu mineral base, SDD 53).

### 3.2 Edificio: cosmódromo + inhibidor (`buildings.yaml`)
- **`cosmodrome`** — "Cosmódromo / Centro de lanzamiento orbital". `category: orbital`, `requires:
  research_lab`, `requires_tech: satellite_tech`. Es donde se **construyen/lanzan** los satélites
  (aloja el dominio `satellite`, `houses: { satellite: N }`) — análogo a `drone_factory` para drones.
- **`signal_inhibitor`** — "Inhibidor de señal". `category: defense`, `requires: research_lab`,
  `requires_tech: advanced_signals`. Aporta `inhibit_power` (jamming) que **reduce el mapeo** de tus
  bases (ver §4.2). Como toda defensa: structural+advanced.

### 3.3 Unidades: tipos de satélite (`units.yaml`, dominio `satellite`)
- **`survey_satellite`** — "Satélite de reconocimiento (propio)". Orbita **tu** planeta. Te da el
  **mapa lindo de tus propias bases** en el panel + una **alerta temprana** chica (bonus a tu radar de
  ataques entrantes; opcional v1). No mapea enemigos.
- **`spy_satellite`** — "Satélite espía". Se **lanza contra un planeta enemigo**; orbita y **acumula %
  de descubierto** de ese enemigo (revela bases + unidades por base). Es el corazón de la feature.
- (v2) `relay_satellite` — comms: acelera el mapeo de aliados / comparte visión (SDD 35 shared_vision).

Atributos nuevos por unidad: `domain: satellite`, `housing_size`, `sat_scan_power` (cuánto escanea por
hora), `sat_energy` (reserva), `orbit_minutes`. Caros y lentos de producir; alto `energy_cost`.

## 4. Mecánica de mapeo (discovery %) — con cálculos
### 4.1 Velocidad de escaneo (satélites del atacante)
- Config: `sat_scan_hours_solo = 96` → **1 satélite, sin inhibidores ⇒ 100% en 96 h (4 días)**.
- Tasa base por satélite: `R = 100 / 96 ≈ 1.04 %/h`.
- **N satélites** sobre el MISMO enemigo (lineal): `tasa = N · R` ⇒ 100% en `96/N` horas.

| Satélites sobre el enemigo | Tiempo a 100% (sin inhibidores) |
|---|---|
| 1 | 96 h (**4 días**, el máximo) |
| 2 | 48 h (**2 días**, el "típico") |
| 3 | 32 h |
| 4 | 24 h (1 día) |

### 4.2 Inhibidores del defensor (cobertura) — con cálculos
- **Exposición** del defensor: `E = (total de edificios en todas sus bases) · signal_per_building`,
  con `signal_per_building = 1`. (Más cosas = más señal que ocultar.)
- **Jamming**: `J = (nº de inhibidores activos) · inhibitor_jam`, con `inhibitor_jam = 8`.
- **Cobertura**: `coverage = min(1, J / E)`.
- **Efecto sobre el atacante**: `tasa_efectiva = N · R · (1 − coverage)` y **techo de descubierto** =
  `100 · (1 − coverage)` (con cobertura total, NO te pueden mapear).

Cuántos inhibidores para 100% de protección = `ceil(E / inhibitor_jam) = ceil(edificios / 8)`:

| Edificios del defensor | Inhibidores para 100% protección |
|---|---|
| 8 | 1 |
| 16 | 2 |
| 24 | 3 |
| 40 | 5 |

Ejemplo: defensor con 24 edificios y **2** inhibidores ⇒ `coverage = 16/24 = 0.67` ⇒ el atacante solo
llega al **33%** y a **1/3** de velocidad. "Más cosas ⇒ más inhibidores" sale solo del ratio.

## 5. Destrucción por drones + escudos + energía/vida útil — con cálculos
### 5.1 Período orbital (rigor, SDD 13)
- **LEO real ≈ 90 min/órbita** ⇒ `orbit_minutes = 90` ⇒ **16 órbitas/día**. Cada órbita: tira el dado
  de destrucción y drena energía.

### 5.2 Caída por drones del defensor
- El defensor con **D drones** en sus bases: por **órbita**, prob. de baja del satélite
  `p = base_loss · D / shield_resist[grado]`, con `base_loss = 0.005` y
  `shield_resist = [1, 2, 4, 8]` (grados 0/1/2/3).

| Drones del defensor | Grado 0 (p/órbita, ~supervivencia/día) | Grado 3 |
|---|---|---|
| 5 | 2.5% → ~0.67/día (~2-3 días) | 0.31% → ~0.95/día (semanas) |
| 10 | 5% → ~0.44/día (<1 día) | 0.62% → ~0.90/día (~10 días) |

⇒ **sin escudo, 10 drones te bajan el satélite en ~1 día**; el **escudo mk3** lo hace casi inmune a
drones (pero la energía lo limita igual, §5.3).

### 5.3 Energía / vida útil (~1 semana, baja al orbitar; más escudo = más drenaje)
- Reserva `sat_energy = 112`. Drenaje por órbita `drain = 1 + 0.3·grado`. Vida útil por decaimiento =
  `sat_energy / drain / 16` días.

| Grado de escudo | Drenaje/órbita | Vida útil por energía | Resistencia a drones |
|---|---|---|---|
| 0 (sin escudo) | 1.0 | **7 días** | ×1 |
| 1 | 1.3 | ~5.4 días | ×2 |
| 2 | 1.6 | ~4.4 días | ×4 |
| 3 | 1.9 | ~3.7 días | ×8 |

⇒ **tradeoff explícito**: subir el grado te salva de los drones pero **acorta la vida** (más material/
peso = más consumo). Sin escudo dura la semana nominal pero cualquier dron lo voltea.

> Todos los números viven en `config.py`/YAML (data-driven) → rebalanceables sin tocar código.

## 6. Panel emergente (mapa del enemigo)
- Botón en el panel de **espionaje/mapa** → modal con un **mapa por enemigo**: sus bases (posición),
  **unidades por base** y un **% descubierto** (barra) por enemigo. Lo no descubierto sale "niebla"
  (`???`). Más satélites ⇒ la barra sube más rápido (se ve en vivo, lazy-by-timestamp).
- Reusa el render de mapa existente (`renderMap`) + `intel_live` (SDD 50). Datos de
  `GET /players/me` (snapshot) o `GET /satellites/intel`.
- **Pictográfico/TTS (SDD 43)**: íconos para base/unidad/% y lectura del estado.

## 7. Modelo de datos + API (lazy-by-timestamp, como drones)
- Modelo **`SatelliteMission`** (o `Satellite`): `owner_id`, `target_player_id` (null = propio),
  `target_planet`, `kind` (survey/spy), `shield_grade`, `energy`, `discovered_pct`, `launched_at`,
  `updated_at`, `status` (orbiting/lost/deorbited).
- **`advance_satellites(session, player, now)`** (estilo `advance_drones`): por el tiempo transcurrido
  (en órbitas), (a) suma `discovered_pct` según §4 con el coverage actual del defensor, (b) drena
  energía §5.3, (c) tira destrucción por drones §5.2, (d) deorbita si energía≤0 o baja. Se llama desde
  `state.advance` (sin cron).
- API: `POST /satellites/launch` (kind, target), `POST /satellites/recall`, `GET /satellites/intel`
  (mapa + %). Snapshot `/players/me` suma `satellites: [...]` + `enemy_maps: {player_id: {pct, bases}}`.
- Migración Alembic nueva. Grafo (SDD 1): aristas `requires_tech`/`houses`/`inhibits` + grounding
  `mech_satellites` para que el asistente y las NPC lo entiendan.

## 8. NPC (SDD 29) y balance
- La NPC con cosmódromo lanza satélites espía antes de atacar (recon) y pone inhibidores al crecer
  (defensa de información), coherente con sus posturas (raid/turtle). Frena: novato/aliados.
- Riesgo snowball (el que mapea ataca mejor): mitigan inhibidores (defensa), costo alto, vida útil
  corta, y que mapear NO saquea — solo informa (el ataque sigue gobernado por SDD 55 topes).

## 9. Tests (regla del proyecto: e2e + servicio)
- `test_satellites.py`: el % sube a `100/96 %/h` por satélite; N satélites escalan lineal; los
  inhibidores bajan techo y velocidad (`coverage`); los drones del defensor bajan satélites (prob por
  órbita); el escudo reduce la baja pero acorta la vida por energía; deorbita a energía 0.
- e2e (`test_api_e2e.py`): investigar `satellite_tech` → cosmódromo → lanzar `spy_satellite` →
  avanzar el tiempo → `GET /satellites/intel` muestra %>0 y bases del enemigo; con inhibidores del
  defensor el % queda topeado.
- Invariantes: el mapeo respeta protección de novato y NO revela más allá del techo por cobertura.

## 10. Rollout / flags / riesgos
- Aditivo y data-driven (tech + 2 edificios + unidades + servicio acotado + 1 panel). Flag
  `satellites_enabled` (default OFF hasta balancear, como 49/50). Va por el pipeline de Argo. e2e+tests.
- Riesgo: otra capa de intel encima de espías/drones → mantener la diferenciación (§2) y los números
  en config para rebalancear.

## 11. Preguntas abiertas (decidir antes de implementar)
- ¿El `survey_satellite` propio da solo el mapa lindo o también un bonus defensivo real (alerta
  temprana / +detección de drones enemigos sobre vos)? (Propuesta: v1 solo mapa + alerta chica.)
- ¿El % descubierto **decae** si retirás/pierden todos los satélites, o queda "memorizado" un tiempo?
  (Propuesta: decae lento — la info envejece, coherente con SDD 35.)
- ¿Los inhibidores también estorban a los **drones**/espías (EW general) o solo a satélites?
  (Propuesta: v1 solo satélites; v2 EW general.)
- ¿Período orbital real 90 min hace que un "tick" de mundo (`AUTO_TICK_SECONDS`) resuelva varias
  órbitas de una? Sí → todo es lazy por timestamp (se calculan las órbitas transcurridas), sin cron.
