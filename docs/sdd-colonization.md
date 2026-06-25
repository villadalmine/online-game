# SDD 37 — Colonización multi-planeta (grafo raza × planeta × atributos)

> **Estado:** propuesto (SOLO especificación — NO implementar todavía) · **Fecha:** 2026-06-24
> **Relacionado:** [SDD 13 precisión científica](sdd-scientific-accuracy.md) (atributos físicos +
> multiplicadores gravedad/insolación/temperatura), [SDD 8 límites de galaxia](sdd-galaxy-limits.md),
> `content/planets.yaml` (gravity_g, mean_temp_c, atmosphere, has_liquid_water, insolation, abundance),
> `content/races.yaml` (home_planet, resource_roles, bonuses), `app/services/physics.py`,
> `app/services/effects.py`, `app/services/onboarding.py`, modelos `Base_`/`Player`.

## 0. Cómo usar este SDD
Todo **data-driven**: los atributos de planeta ya existen (SDD 13); se agregan **rasgos de tolerancia
por raza** en `content/races.yaml`. La compatibilidad raza×planeta **se computa de los atributos**
(no es una matriz hardcodeada) → cambiar el balance = editar atributos/tolerancias en YAML.

## 1. Objetivo
Permitir **colonizar otros planetas** (fundar una base fuera de tu mundo natal) y que **importe quién
sos y a dónde vas**: cada **planeta tiene atributos** y cada **raza los suyos**, así que según la
combinación **algunas cosas son mejores, otras peores y otras imposibles**. Convertir eso en un **grafo
de opciones** que el jugador explora ("si soy terrícola y quiero Marte, ¿qué gano/pierdo?") y que
alimenta la economía/combate vía multiplicadores. Ej. del usuario: *soy terrícola, ¿cómo es colonizar
otro planeta?* → la respuesta sale del modelo, no de reglas sueltas.

## 2. Los dos lados del grafo (ya casi todo existe)
- **Planeta** (`content/planets.yaml`, SDD 13): `gravity_g`, `mean_temp_c`, `atmosphere`
  (`none|thin|thick|toxic`), `has_liquid_water`, `insolation`, `abundance{mineral→×}`.
- **Raza** (`content/races.yaml`): hoy `home_planet`, `resource_roles`, `bonuses`. **Nuevo (aditivo):**
  `tolerances` — el "ambiente ideal" de la raza y cuánto se banca apartarse:
  ```yaml
  # terran
  tolerances:
    ideal_gravity_g: 1.0
    ideal_temp_c: 15
    gravity_tol: 0.5          # cuánto desvío toleran sin gran penalidad
    temp_tol: 40
    atmospheres: [thin, thick]   # respirables para esta raza
    needs_water: false
    hostile_penalty: 0.6      # × a producción en ambiente apenas habitable
  ```
  Marcianos: `ideal_gravity_g 0.38`, toleran frío y atmósfera fina; Venusianos: toleran calor/atmósfera
  tóxica. (Valores de arranque; se afinan por YAML.)

## 3. Compatibilidad (función pura, determinista)
`compat(race, planet) -> {habitability ∈ [0,1], can_colonize: bool, modifiers, reasons}`:
```
g_pen   = clamp(1 - |planet.gravity - race.ideal_gravity| / race.gravity_tol, 0..1)
t_pen   = clamp(1 - |planet.temp   - race.ideal_temp|     / race.temp_tol,    0..1)
atmo_ok = planet.atmosphere in race.atmospheres        (si no → fuerte penalidad o imposible)
water   = (not race.needs_water) or planet.has_liquid_water
habitability = g_pen * t_pen * (1 if atmo_ok else race.hostile_penalty) * (1 if water else 0.5)

can_colonize = atmo_ok-o-no-letal  AND  habitability >= min_habitability   # umbral data-driven
```
- **Imposible** cuando el ambiente es **letal** para la raza (p.ej. atmósfera `toxic` y la raza no la
  tolera, o `habitability` bajo el umbral) → la UI lo muestra como 🔒 y explica por qué (`reasons`).
- **Mejor/peor** = el `habitability` y los **modifiers** que de él derivan.

## 4. De compatibilidad a multiplicadores (engancha en lo que ya hay)
`modifiers` que devuelve `compat` y dónde aplican (apilan con SDD 13 y `effects.multiplier`):
| modifier | efecto | engancha en |
|---|---|---|
| `production` | × producción de las minas de esa colonia | `economy`/`effects` por-base |
| `energy_regen` | × regen de energía de esa colonia | `physics.effective_energy_regen` |
| `build_cost` / `build_speed` | construir cuesta/tarda más en mundo hostil | `build` |
| `defense` | bonus/penalidad defensiva (gravedad alta = mejor defensa, etc.) | `combat` |
- La **abundancia mineral** del planeta (ya existe) sigue mandando qué conviene extraer ahí → el
  **grafo de opciones**: "Marte te da +azufre pero -producción por gravedad baja si sos terrícola".
- Multiplicadores **por-colonia** (no globales): hoy los multiplicadores son por-jugador; este SDD
  introduce el factor **por-base** según su planeta (decisión: extender `effects.multiplier` con un
  `base_id` opcional, o calcular el factor de planeta donde se produce).

## 5. Fundar la colonia (acción nueva)
- **`POST /colonize` `{galaxy, planet_key}`** → valida `can_colonize` (raza×planeta), cobra **costo de
  colonización** (minerales + energía, escalado por nº de colonias = expansión decreciente), despacha
  una **misión de colonización** (viaje, patrón de `AttackMission`/expedición) que al llegar **crea una
  `Base_`** en ese planeta con stock inicial chico. Requiere `shuttle` (como las expediciones).
- **Límites:** máximo de colonias por jugador (data-driven), una por planeta, dentro de tu galaxia
  (SDD 8). Cada colonia es base atacable/espiable (combate y SDD 35 ya operan por base).

## 6. El "grafo de opciones" para el jugador (lo que pidió el usuario)
- **`GET /colonize/options`** (auth) → para **tu raza**, por cada planeta de tu galaxia:
  `{planet, habitability, verdict: great|ok|poor|impossible, modifiers, abundance_highlights, reasons}`.
  La web lo muestra como una **matriz/grafo** (planetas × atributos) con colores (verde/ámbar/🔒) y el
  "por qué", para decidir a dónde expandirse. Reusa el modal de planeta (SDD web) agregando el veredicto
  para tu raza.
- **Asistente IA:** puede leer `colonize/options` (grounded) y aconsejar ("para terrícola, la Luna es
  🔒 por gravedad/atmósfera; Marte es 'poor' (-prod) pero te da azufre").

## 7. Tests / validación
- **Pureza de `compat`:** casos a mano (terrícola→Tierra ≈ 1.0; terrícola→Luna/Venus → impossible o
  muy bajo; marciano→Marte alto). Umbrales y `reasons` correctos.
- **Gate:** `POST /colonize` a un planeta imposible → 400 con motivo; a uno válido → crea base tras el
  viaje (fast-forward), con stock inicial.
- **Modifiers:** una mina en un planeta hostil produce menos que la misma en el mundo natal (mismo
  mineral) — verificado por la API.
- **e2e:** `GET /colonize/options` lista veredictos coherentes con la raza; colonizar y luego ver la
  nueva base en `/players/me`.

## 7.bis Estado de implementación (2026-06-24) — v1 (grafo de opciones, read-only)
- **Contenido:** `tolerances` por raza en `content/races.yaml` (ambiente ideal + tolerancias +
  atmósferas respirables); ajustado para que el mundo natal dé "great".
- **Servicio `colonization.py`:** `compat(race, planet)` puro (habitability, can_colonize, verdict
  great|ok|poor|impossible, modifiers prod/energía/costo, reasons) + `options(race, galaxy)` (el
  grafo por planeta de tu galaxia, con `is_home` y `abundance_highlights`).
- **API:** `GET /colonize/options` (tu raza). **Web:** el modal de planeta muestra el veredicto para
  tu raza (🟢/🟡/🟠/🔒 + por qué + modifiers). Bilingüe.
- **Tests:** compat (home=great, mercurio imposible por atmósfera, Venus imposible para terran por
  calor), options ordenado + home flag; e2e. **260 verdes.**
- **Pendiente (follow-up estructural, NO en v1):** `POST /colonize` (fundar base en otro planeta) +
  aplicar los **modifiers por-colonia** (producción/energía/costo por base) — es el cambio de
  por-jugador a por-base que marca el §8; se hace con el usuario presente.

## 7.ter Estado v1.5 (2026-06-25) — fundar colonia + tech-gating
- **Tech-gating (clave):** en el sistema solar **ningún** mundo no-natal es habitable sin tecnología
  (Marte −63 °C, Venus 464 °C, Mercurio sin atmósfera). `compat(race, planet, techs)` ahora relaja
  los límites con tecnologías de colonización investigadas: **Antigravedad** (gravedad ×3),
  **Blindaje térmico** (temperatura ×4), **Cúpulas selladas** (cualquier atmósfera, incl. ninguna)
  — en `content/technologies.yaml` (`effect: colonize`). Razas con `tolerances` más amplias
  necesitan menos tech.
- **Fundar colonia:** `POST /colonize {planet_key}` (`found_colony`): valida compat (con tus techs) +
  galaxia + límite (`max_colonies`), consume 1 transbordador + energía (escala con nº de colonias),
  crea la `Base_` (instantáneo en v1, sin viaje). Botón **🪐 Colonizar** en el modal de planeta.
- **Producción por-colonia:** `collect_mines` produce según el **planeta de cada base** (antes usaba
  el natal) × el modificador de habitabilidad de la colonia. El mundo natal queda idéntico
  (compat no se aplica) → backward-compatible.
- Tests: tech desbloquea mundos hostiles, cúpulas vencen "sin atmósfera", fundar requiere
  tech+transbordador, e2e. **266 verdes.**

## 7.quater Visión v2 (diseño, NO implementado) — colonización rica
Idea (del usuario): la colonización se entrelaza con **edificios, investigación y exploración**, con
tecnología sci-fi que vence lo "imposible":
- **Tipos de base:** terrestre (hoy), **orbital** (estación que orbita el planeta) y **lunar** (sobre
  una luna). La orbital + **robots** permite **extraer recursos sin habitabilidad** (nadie vive ahí;
  naves van y vienen) → rinde menos y cuesta más, pero abre mundos letales.
- **Árbol de tecnologías** de colonización más profundo: antigravedad, escudos/cúpulas presurizadas,
  regulación térmica, **robótica autónoma** (base orbital), terraformación parcial. Cada una habilita
  un eje o un tipo de base; encadenadas, vuelven colonizable casi cualquier mundo.
- **Por raza:** además de `tolerances`, **descuentos/precondiciones** de tech (algunas razas traen una
  colonización "gratis" o más barata; otras necesitan más ciencia). Data-driven.
- **Exploración:** explorar un sistema/luna **revela** sus atributos antes de poder colonizar (link con
  expediciones/espionaje) — colonizás lo que conocés.
- **Modifiers por-colonia ampliados:** energía/costo/velocidad de cola/defensa por base (hoy solo
  producción), reusando el patrón de `compat().modifiers`.

## 8. Riesgos / decisiones
- **Multiplicador por-base vs por-jugador:** hoy es por-jugador; introducir por-base es el cambio
  estructural principal (decidir: `effects.multiplier(..., base_id=)` o factor de planeta en el punto
  de producción). Empezar por **producción/energía por-colonia**, dejar combate por-jugador.
- **Balance de expansión:** costo de colonización creciente para que expandir no sea siempre óptimo;
  mundos hostiles dan acceso a minerales raros pero penalizan → trade-off real (el grafo de opciones).
- **Atributos faltantes:** las `tolerances` por raza son nuevas; sin ellas, `compat` cae a un default
  neutro (no rompe partidas). Aditivo y data-driven.
- **No reinventar viaje/base:** reusar misiones (viaje) y `Base_`/edificios/combate/espionaje ya
  existentes; lo nuevo es el **gate + los modifiers raza×planeta** y el **grafo de opciones**.
