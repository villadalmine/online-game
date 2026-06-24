# SDD 13 — Rigor científico del contenido (galaxias, sistemas, planetas, lunas, materiales, instalaciones, naves)

> **Estado:** propuesto (en cola) · **Fecha:** 2026-06-22 · **Autor:** equipo online-game
> **Ámbito:** **contenido data-driven** (`content/*.yaml`) + esquemas/validación. Aditivo, sin
> reescribir motor. **Principio:** que galaxias, planetas, lunas, materiales, instalaciones, naves,
> militares y científicos sean **científicamente correctos / reales**, fiel al espíritu del proyecto.

## 1. Objetivo

Llevar el contenido de "aproximado/temático" a **científicamente fundamentado y verificable**: cada
cuerpo y cada material con **datos reales y fuente citada**, y cada instalación/nave/unidad
**anclada a tecnología y física reales**, con restricciones que tengan sentido (no aviones donde no
hay atmósfera, no barcos donde no hay agua líquida, etc.).

**Con rienda suelta para crecer e inventar:** se arranca con un **núcleo real y chico** y se
amplía con contenido **especulativo** (plausible, "aún no descubierto") y hasta **spin-offs de
ficción** (tipo *The Expanse*) — todo **etiquetado** por nivel de canon (§3.8) y/o **universo**
(§3.9), sin confundir dato con invento y sin tocar código (data-driven).

## 2. Estado actual (qué ya es real y qué no)

**Real / bien encaminado:**
- Planetas reales del Sistema Solar (Tierra, Marte, Venus, Mercurio) con **abundancias** mineral
  basadas en ciencia planetaria (fuentes en el plan original).
- Minerales mapeados a elementos reales (`minerals.yaml` tiene `real`/`real_en`): hierro, silicio,
  titanio (ilmenita), azufre, He-3 (regolito), KREEP, hielo de agua…
- Lunas reales: Luna, Fobos, Deimos, y la **cuasi-luna real de Venus "Zoozve" (2002 VE68)**.

**No correcto (a arreglar):**
- **Jerarquía**: los planetas cuelgan directo de la "galaxia"; falta el nivel **sistema estelar**
  (los planetas orbitan estrellas, las estrellas están en la galaxia).
- **Andrómeda con planetas inventados** (`vega_prime`, `nyx`): **no hay exoplanetas catalogados en
  Andrómeda** (está a ~2.5M años luz). Para ser reales, la expansión debe usar **sistemas reales de
  la Vía Láctea**.
- **Instalaciones/naves/unidades** sin base científica explícita; aviones/barcos usables en
  cualquier planeta sin importar atmósfera/agua.
- Abundancias y propiedades **sin campo de fuente** ni propiedades físicas (gravedad, temperatura,
  atmósfera) que el juego pueda usar.

## 3. Diseño

### 3.1 Jerarquía correcta: Galaxia → Sistema estelar → Planeta → Luna
- Nuevo nivel **sistema estelar** en `content/planets.yaml`: `galaxy: milky_way` → `systems` →
  `planets` → `moons`. La "galaxia" sigue siendo la Vía Láctea (real); dentro, **sistemas reales**.
- **Sistema Solar** completo y real. **Expansión** con **sistemas reales bien caracterizados**:
  - **Proxima Centauri** (~4.24 años luz; Proxima b en zona habitable),
  - **TRAPPIST-1** (~40 años luz; 7 planetas rocosos, masas/radios/densidades/gravedad medidos),
  - y otros del **NASA Exoplanet Archive** según necesidad.
- Reemplazar `vega_prime`/`nyx` (ficticios) por planetas reales (p.ej. `proxima_b`, `trappist_1e`).
  Es cambio de **datos** (rebalanceo), no de código.

### 3.2 Planetas: propiedades físicas reales (campos aditivos)
Cada planeta suma campos con **valores reales** y **fuente**:
```yaml
- key: mars
  name: "Marte"  # (+ name_en, SDD 4)
  gravity_g: 0.38            # relativo a la Tierra
  mean_temp_c: -63
  atmosphere: thin           # none | thin | thick (composición opcional)
  has_liquid_water: false
  insolation: 0.43           # flujo solar relativo a la Tierra (para energía solar)
  composition: {...}         # ya existe abundance por mineral
  sources: ["NASA Mars Fact Sheet", "..."]
```
Para exoplanetas, usar **mejores estimaciones publicadas** (con rango si hace falta) y citar.

### 3.3 Lunas
Reales por cuerpo (Luna, Fobos, Deimos, Zoozve). Para sistemas exoplanetarios, **solo si hay lunas
catalogadas** (hoy prácticamente ninguna confirmada) → en general los exosistemas no traen lunas.

### 3.4 Materiales: provenencia real verificada
- Revisar/confirmar cada `resource → elemento/mineral real` y su **abundancia por cuerpo** contra
  fuentes (corteza terrestre, Marte, Venus, regolito lunar, condritas). Agregar `sources` por
  mineral. Premium (He-3, KREEP, hielo) ya están justificados; documentar dónde son realistas.

### 3.5 Instalaciones (buildings) con base tecnológica real
Cada edificio suma `real`/`real_en` (como los minerales) explicando su contraparte real:
- **mine** → **ISRU** (in-situ resource utilization);
- **power_plant** → solar / nuclear / **fusión** (su rendimiento depende de `insolation` para solar);
- **research_lab** → laboratorio/I+D;
- **factory** → **manufactura aditiva**/fundición;
- **barracks**, **turret** (defensa) → instalaciones reales plausibles.

### 3.6 Naves/unidades con propulsión real + **restricciones físicas**
- Campo `propulsion` real (`chemical` | `ion` | `nuclear_thermal` | `electric`…) y **requisitos
  ambientales** data-driven:
  - **aircraft** requiere `atmosphere != none` (no hay aviones en el vacío) → solo en planetas con
    atmósfera;
  - **ship** requiere `has_liquid_water: true` (océanos) → solo donde hay líquido;
  - **shuttle/space** → propulsión de lanzamiento; **tank** → terrestre.
- Estas restricciones se chequean en `train`/uso, leyendo los flags del planeta. Aditivo y
  data-driven (cambiar la regla = editar YAML).

### 3.7 Personal: militares, científicos, trabajadores
Anclar a roles reales (operarios/ingenieros, investigadores, fuerzas) con `real`/`real_en`. Sin
mecánica nueva; es descripción fundamentada (mejora la guía in-game).

### 3.8 Niveles de "canon": real / especulativo / ficción (rienda suelta honesta)
Empezamos con **poco y real**, y crecemos pudiendo **inventar** sin perder la honestidad. Cada
entidad (sistema/planeta/luna/material/instalación/nave) lleva un campo **`canon`**:
- `real` → dato verificado, con `sources` (obligatorio).
- `speculative` → plausible pero **aún no descubierto/confirmado** (p.ej. un exoplaneta hipotético,
  un mineral teórico); `sources` opcional + `rationale` (por qué es plausible). La UI puede mostrar
  un badge "hipotético".
- `fiction` → lore de un spin-off (no pretende ser real).

Así arrancás con un núcleo `real` chico y vas sumando `speculative`/`fiction` cuando quieras, todo
**etiquetado** (nadie confunde dato con invento). El test de contenido exige `sources` solo a los
`real`.

### 3.9 Universos / spin-offs (tipo *The Expanse*)
Como TODO el contenido vive en YAML y el motor es **agnóstico del contenido**, podemos tener
**varios universos** seleccionables:
- un universo **"hard-real"** (Sistema Solar + exosistemas reales), y
- **spin-offs** ambientados (p.ej. estilo *The Expanse*: Cinturón/Belters, motor Epstein, facciones
  Tierra/Marte/OPA, recursos como agua/Helio-3) marcados `canon: fiction`.
- Estructura: `content/universes/<nombre>/*.yaml` (o un campo `universe` por entidad). El **universo
  se elige por galaxy instance / temporada** (liga con SDD 8 y SDD 11): cada partida corre un
  universo. El engine no cambia; cambia el pack de datos.
- Beneficio: el rigor científico (núcleo real) y la creatividad (spin-offs) **conviven** sin tocar
  código — solo se agregan packs de contenido.

## 4. Cómo afecta el juego (opcional, todo data-driven)
Multiplicadores físicos opt-in (extender, no romper): `gravity_g` → costo/tiempo de construcción;
`insolation` → salida de energía solar; `atmosphere`/`has_liquid_water` → gating de aviones/barcos;
`mean_temp_c` → energía de refrigeración. Valores por YAML; si no se setean, comportamiento actual.

## 5. Validación / tests (regla del proyecto)
- **Test de contenido** (`tests/test_content.py` o ampliar el registry test): todo planeta tiene
  los campos físicos requeridos + `sources`; toda abundancia referencia minerales existentes; cada
  mineral/edificio/unidad tiene `real`/`sources`.
- **Servicio**: `train` rechaza aircraft en planeta sin atmósfera y ship sin agua (mensaje claro);
  energía solar escala con `insolation`.
- **E2E**: `GET /catalog` expone los nuevos campos; un caso de error de gating.
- **i18n** (SDD 4): `real_en` para los nuevos textos `real`.

## 5.ter Estado de implementación (2026-06-22) — v1 (incremental, data-only)
- **Propiedades físicas reales** en `content/planets.yaml` por planeta: `gravity_g`, `mean_temp_c`,
  `atmosphere` (none/thin/thick), `has_liquid_water`, `insolation`, **`canon`** (real/fiction) y
  `sources` (NASA Planetary Fact Sheets). Sistema Solar = `real`; Andrómeda marcada `fiction` (no
  hay exoplanetas catalogados ahí). Expuesto por `GET /catalog` (y el modal de planeta lo muestra).
- **Restricciones físicas data-driven** en `start_training` (SDD §3.6): `aircraft`
  `requires_atmosphere` (no en el vacío → Mercurio no puede) y `ship` `requires_liquid_water`
  (solo planetas con océano → Tierra). Campos `propulsion` descriptivos en esas unidades.
- **Tests**: `tests/test_science.py` (2 servicio) + 2 e2e (catálogo con campos físicos; barco
  bloqueado sin agua). 153 unit/e2e + 15 browser ✅.

## 5.quater Estado v2 (2026-06-24) — aditivo, sin romper jugadores
- **Nivel `system`** (jerarquía sistema estelar) como campo por planeta (Sistema Solar para los 4;
  sistemas ficticios para Andrómeda). Localizado ES/EN (`LOCALIZED_FIELDS`).
- **Exosistemas REALES** (nueva región `solar_neighborhood`, `canon: real`): **Proxima Centauri b**
  y **TRAPPIST-1e** con datos físicos publicados + `sources` + `confidence: low` (atmósfera/agua no
  confirmadas). Es la "expansión" científica honesta (Andrómeda ficticia se mantiene, tagueada).
- **Nivel `speculative`**: `nova_terra` (`canon: speculative` + `rationale`, sin `sources`) — demuestra
  "inventar lo aún no descubierto" sin confundir dato con invento.
- Expuesto en `/catalog` (+ `?lang=en`) y en el **modal de planeta** (system, canon, confidence,
  rationale). Tests `tests/test_science.py` (exosistemas/speculative + sources/rationale + i18n).

## 5.quinquies Estado v3 (2026-06-24) — multiplicadores físicos (§4) implementados
- `app/services/physics.py`: multiplicadores **opt-in** (`physics_enabled`) y **data-driven**,
  anclados a la Tierra=1.0 (off o sin datos ⇒ neutral, comportamiento actual) y **acotados** a
  `[physics_min_mult, physics_max_mult]` (evita que extremos como la insolación de Mercurio rompan el
  balance). Mapeos: **`gravity_g` → tiempo de construcción** (más gravedad ⇒ build más lento;
  `start_build`), **`insolation` → regen de energía** (más sol ⇒ más energía) y **`mean_temp_c` →
  refrigeración** (temperaturas lejos del confort, frío o calor, **drenan** energía; nunca la suben).
  La regen efectiva = base × insolación × temperatura (helper `effective_energy_regen` usado en
  advance/build/train/research/expedición/ataque + display advisor/NPC). Sensibilidad y techos
  configurables (`physics_*` en config). Ej.: Venus tiene mucho sol pero 464 °C ⇒ la penalización
  térmica compensa su alta insolación (trade-off realista).
- **Encendido en prod** por env (`PHYSICS_ENABLED=true`); off en dev/tests por default.
- Tests: `tests/test_physics.py` (unit: Tierra neutral, Marte build más rápido, Venus/Mercurio
  energía con clamp, planeta/campo faltante neutral, regen efectiva) + e2e (gravedad cambia el
  tiempo de build; off ⇒ neutral). **212 verdes.**

**Pendiente (follow-up)**: jerarquía anidada real (galaxy→system→planet en el árbol, no solo campo);
**universos/spin-offs** ([SDD 26](sdd-spinoff-universes.md)) seleccionables por partida;
`real`/`canon` en edificios/unidades.

## 6. Riesgos / decisiones
- **Realismo vs. jugabilidad**: las restricciones físicas deben sumar, no frustrar → gating
  configurable y abundancias balanceadas. Decisión: empezar con constraints **suaves** (penalización)
  antes que **duras** (prohibición), salvo casos obvios (avión en vacío).
- **Incertidumbre de exoplanetas**: usar estimaciones publicadas + rango + cita; marcar
  `confidence` cuando sea débil.
- **Romper balance actual**: cambiar Andrómeda ficticia por sistemas reales rebalancea; es
  data-only y se ajusta. Mantener keys estables donde se pueda (earth/mars/venus/mercury).
- **Alcance**: Sistema Solar primero (datos sólidos); exosistemas como expansión incremental.

## 7. Fuentes (autoritativas)
- **NASA Exoplanet Archive** (exoplanetas: masa/radio/densidad/gravedad): exoplanetarchive.ipac.caltech.edu
- **NASA Planetary Fact Sheets** (gravedad, temperatura, atmósfera, insolación).
- TRAPPIST-1 (NASA): science.nasa.gov/exoplanets/trappist1 · Proxima Centauri b (NASA).
- Minerales/abundancias: fuentes del plan original (corteza terrestre, Marte, Venus, Luna, Fobos/Deimos).
