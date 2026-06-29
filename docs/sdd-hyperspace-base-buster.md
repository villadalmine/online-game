# SDD 57 — Viajes por el hiperespacio: research de velocidad + nave capital "rompe-bases"

> **Estado:** **IMPLEMENTADO (v1)** 2026-06-29 — árbol + acorazado + bombardeo con anti-lockout.
> Pendiente v2: reducir tiempo de viaje por hiperespacio (ver §4). · **Diseño:** 2026-06-29
> **Relacionado:** `content/technologies.yaml` (árbol de research), `content/units.yaml` (unidades
> espaciales), `app/services/combat.py` (resolución de ataque + destrucción de edificios),
> `app/services/strike.py` (precedente: misiles que destruyen edificios, SDD 49),
> [SDD 37 colonización](sdd-colonization.md), [SDD 54 piso anti-lockout](sdd-economy-defense-bugs.md),
> [SDD 13 rigor científico](sdd-scientific-accuracy.md).

## 1. Idea (usuario, 2026-06-29)
Un **árbol de research de fin de juego** alrededor de la velocidad: "viajes por el hiperespacio",
un research de **velocidad de la luz** (propulsión relativista) + **fisión nuclear** para naves
súper rápidas. Con eso se desbloquea una **nave espacial de guerra capital** con un poder de
destrucción enorme que **destruye BASES/edificios** (no solo tropas), con reglas que **impiden dejar
al rival sin con qué jugar**:
- Puede destruir **todos los edificios MENOS la base central (headquarters) y las minas**.
- Solo puede romper un edificio si el rival tiene **de más** (un excedente de ese tipo); **nunca**
  puede dejarlo sin: una **mina**, sin con qué **producir trabajadores**, sin con qué **producir
  militares**, ni sin con qué **producir espías**.
- Si le destruís edificios de research (laboratorio), el rival **pierde capacidad y debe volver a
  investigar / reconstruir** (perdió la base donde se investigaba).

> Nota de modelo: en el juego, *base* (`Base_`) = colonia en un planeta; los *edificios* viven dentro
> de una base. El usuario usa "base" como "edificio/estructura". Este SDD habla de **destruir
> edificios** dentro de la base atacada (como ya hace el misil nuclear con `area:true`, SDD 49).

## 2. Diseño propuesto
### 2.1 Árbol de research "hiperespacio" (data-driven, `technologies.yaml`)
Cadena GATE (sin multiplicador, como rocketry→ballistics→nuclear_fission):
- `relativistic_drive` ("Propulsión relativista / velocidad de la luz") — requiere `antigravity`.
- `hyperspace_travel` ("Viajes por el hiperespacio") — requiere `relativistic_drive` +
  `nuclear_fission` (ya existe en el árbol strike) → naves súper rápidas (reduce tiempo de viaje de
  flotas espaciales; gancho en `start_attack`/cálculo de ETA).
- `capital_warship` ("Acorazado/Dreadnought") — requiere `hyperspace_travel` → habilita la unidad.
Costos por ROL (SDD 53): caros, energetic+advanced dominante (fin de juego, no defensa).

### 2.2 Unidad: nave capital "rompe-bases" (`units.yaml`, dominio `space`)
- Stats altísimos + nuevo atributo `siege_power` (daño a edificios) y `bombard: true`.
- Requiere `factory` + tech `capital_warship`; `housing_size` grande (varias plazas); muy cara y
  lenta de producir; alto `energy_cost`. Se aloja en hangar (space). Balance por `make balance`.
- Rigor (SDD 13): viaje intra/inter-planeta según hyperspace; bombardea desde órbita.

### 2.3 Reglas de bombardeo de edificios (en `combat.py`, tras ganar el ataque)
Cuando una flota con `siege_power` GANA el combate contra la base, además del saqueo, **destruye
edificios** del defensor según `siege_power`, respetando invariantes anti-lockout:
- **Nunca destruir**: `headquarters` ni `mine` (categoría `core`/`mine`).
- **Protección del último de cada tipo esencial**: por cada "capacidad esencial" del defensor, dejar
  al menos UNA fuente:
  - producir trabajadores/militares → `headquarters` (ya protegido).
  - producir científicos/espías + investigar → `research_lab` (proteger el último).
  - economía → `mine` (ya protegido) + dejar ≥1 `silo`/almacén si aplica.
  - alojamiento mínimo → no dejar en cero las plazas base (gracia SDD 46).
- **Solo excedentes**: si el defensor tiene 3 laboratorios, podés bajarlo a 1 (destruís 2); si tiene
  1, no se toca. Igual para cuarteles/fábricas/etc.
- **Consecuencia de research**: al destruir un `research_lab` excedente, si había investigaciones
  EN CURSO ahí, se cancelan/pierden el progreso (deben re-investigar). Las techs YA completadas son
  permanentes (no se "desaprenden") salvo decisión futura — **pregunta abierta** (§4).

### 2.4 Defensa contra el rompe-bases
- Las torretas / escudos planetarios (`shields`) reducen `siege_power` (la base puede aguantar el
  bombardeo si está bien defendida) → coherente con SDD 53 (defensa = structural, siempre disponible).
- Aviso al defensor (journal/notificación + 📈 historia, SDD 51): "perdiste el edificio X por
  bombardeo".

## 3. Tests / validación
- `test_balance.py`: la cadena hyperspace progresa en costo; la nave capital es la unidad más cara.
- `test_combat.py`: una flota con `siege_power` que gana destruye SOLO excedentes; **nunca** HQ/mina
  ni el último `research_lab`; cancela research en curso del lab destruido.
- e2e (`test_api_e2e.py`): investigar la cadena → construir la nave → bombardear → el defensor queda
  con HQ + ≥1 mina + ≥1 lab (anti-lockout) y con menos edificios excedentes.
- Invariante anti-lockout (cruza SDD 54): un jugador bombardeado **siempre** conserva con qué minar,
  hacer obreros, militares y espías → nunca queda en un pozo sin salida.

## 4. Preguntas abiertas (decidir antes de implementar)
- ¿Destruir un lab hace **perder techs ya investigadas** (más castigo, riesgo de espiral) o solo
  cancela las EN CURSO y baja capacidad? (Propuesta del SDD: solo en curso; techs completas son
  permanentes.)
- ¿El bombardeo es parte del ataque normal de flota (si llevás nave capital) o una acción aparte
  (como `strike` de misiles)? (Propuesta: parte del ataque de flota, gateado por `siege_power`.)
- ¿`hyperspace_travel` reduce el tiempo de viaje de TODA flota espacial o solo de la nave capital?

## 5. Rollout / riesgos
- Mayormente data-driven (techs + unidad) + lógica acotada de bombardeo en `combat.py`; aditivo,
  flag `siege_enabled` (default ON, gateado por el árbol carísimo → naturalmente fin de juego).
  Va por el pipeline de Argo. e2e + tests (regla del proyecto).

## 6. Implementación (2026-06-29, v1)
- **Techs** (`content/technologies.yaml`, categoría `hyperspace`): `relativistic_drive` (req
  `antigravity`) → `hyperspace_travel` (req `relativistic_drive`). Costos energetic+advanced altos.
- **Unidad** (`content/units.yaml`): `dreadnought` ("Acorazado estelar"), dominio `space`, req
  `factory` + `hyperspace_travel`, `housing_size=6`, `siege_power=900`, carísima (energetic 1200 +
  advanced 900, SDD 53). Va en flota normal (no es ordnance/drone).
- **Bombardeo** (`app/services/combat.py:_bombard_buildings`, llamado al resolver una victoria si
  `siege_enabled`): demuele edificios EXCEDENTES de la base atacada según el `siege_power`
  sobreviviente / `siege_per_building` (config, 300). **Nunca** HQ ni minas (cat core/mine), **nunca**
  el último de cada tipo (solo excedentes). Si vuela un `research_lab`, cancela la investigación EN
  CURSO (`ResearchOrder.status="cancelled"`). `razed` va al CombatLog y a la notificación del defensor.
- **Front** (`web/index.html`): categoría `hyperspace` agregada al panel de Investigación (sino las
  techs nuevas no se listaban) + label 🌌.
- **Tests**: e2e `test_dreadnought_razes_surplus_buildings_e2e` (gana → vuela 1 cuartel excedente,
  deja el otro + el HQ).
- Config: `siege_enabled=True`, `siege_per_building=300`.
- Riesgo: arma de fin de juego muy fuerte → snowball. Mitigan: invariantes anti-lockout, costo altísimo,
  defensa (shields/torretas) que absorbe `siege_power`, y los topes de ataque (SDD 55).
