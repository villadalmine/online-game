# SDD 64 — Búnkeres atómicos: túneles, mapa subterráneo, brechas y guerra de sabotaje

> **Estado:** **DISEÑO** 2026-07-01 (sin implementar) · **Pedido:** usuario, 2026-07-01.
> **Relacionado:** [SDD 61 satélites](sdd-satellites-recon.md) (mapear al enemigo → ubicar su HQ bajo
> tierra), [SDD 62 guarnición](sdd-garrison-troops-per-base.md) (unidades por base), [SDD 49 misiles/
> nuclear](sdd-missile-launcher.md) (`nuclear_fission`), [SDD 46 alojamiento](sdd-unit-housing-capacity.md),
> [SDD 43 pictográfico](sdd-play-without-reading.md) (mapa visual), combate (`app/services/combat.py`).

## 1. Idea (usuario, 2026-07-01)
Un **research de "búnkeres atómicos"** que habilita **fabricar túneles**: se abre un **mapa debajo de la
tierra**. Si ya mapeaste al enemigo con satélites (SDD 61) **ves dónde está su headquarters**; si no, es
**al azar**. En los túneles construís **habitaciones**: viviendas, comedores, sala de investigación,
reservas de agua, cultivos y **armas atómicas**. Podés poner **varias entradas** por todos lados; si no
sabías dónde estaba la base enemiga podés hacer una **brecha** para meterte — pero **el enemigo ve la
puerta en su mapa**, así que hay que desarrollar **búnkeres defensivos** con **cerraduras y
ventilación**. Hasta que no los pongas, **cualquiera se te mete y ataca adentro**. El ataque a un búnker
(si descubriste uno) es en la **misma pantalla del mapa de búnkeres**: si el rival no tiene defensa pero
le metiste una entrada, le hacés **clic y atacás**, y ahí podés meter **gas tóxico** (la gente se enferma;
con **ventilación** es menor), o **ratas** (se te pudre la comida), o **contaminar el agua** (se enferma
la gente). El búnker tiene **estado de salud de comida, gente y agua**. Por ahora hasta acá.

## 2. Cómo encaja con lo existente
- **Satélites (SDD 61)** ya dan `discovered_pct` del enemigo: reusarlo para **revelar la posición del
  HQ enemigo** en el mapa subterráneo (100% → ves su HQ; parcial → área aproximada; 0% → azar).
- **Guarnición (SDD 62)**: las tropas ya viven por base → dentro del búnker defienden las tropas de esa
  base; una incursión por una brecha es un combate localizado.
- **Nuclear (SDD 49)**: `nuclear_fission` como prerrequisito temático de los búnkeres atómicos + las
  "armas atómicas" que se guardan/fabrican abajo.
- **Nueva capa**: hoy todo es de superficie. El búnker es una **segunda capa** (subterránea) del mismo
  planeta, con su propio mapa y su propia economía de vida (comida/agua/gente).

## 3. Diseño data-driven
### 3.1 Research
- **`bunker_engineering`** — "Ingeniería de búnkeres (atómicos)". Habilita cavar túneles + construir
  habitaciones. Prereq: `nuclear_fission` (SDD 49). Categoría nueva `underground`.
- **`bunker_defense`** — "Defensa de búnkeres": habilita **cerraduras** (sellar entradas) y
  **ventilación** (mitiga gas). Prereq: `bunker_engineering`.
- (v2) `deep_boring` — túneles más rápidos/profundos; `water_recycling` — mitiga contaminación de agua.

### 3.2 Túnel + mapa subterráneo (nueva capa)
- Al investigar `bunker_engineering` y **cavar** (edificio `tunnel_entrance` en una base de superficie),
  se abre el **mapa subterráneo** del jugador: una grilla/grafo de **celdas** bajo su base. Cavar túneles
  conecta celdas; en cada celda se construye una **habitación** (§3.3).
- Data-driven: `content/underground.yaml` (o extender `buildings.yaml` con `layer: underground`). El
  tamaño de la grilla y el costo de cavar salen de config/YAML.

### 3.3 Habitaciones (edificios subterráneos)
Cada una es un edificio con `layer: underground` (data-driven, costos por rol SDD 53):
- **`quarters`** (viviendas): alojan **gente** (población del búnker). Cuanta más gente, más produce/
  investiga, pero más comida/agua consume.
- **`canteen`** (comedor) + **`farm`** (cultivos): producen/almacenan **comida**.
- **`water_reserve`** (reserva de agua): produce/almacena **agua**.
- **`research_room`** (sala de investigación): investiga bajo tierra (a salvo de bombardeo de superficie).
- **`atomic_lab`** (armas atómicas): fabrica/almacena armas atómicas (cruza SDD 49 nuclear).
- **`bunker_door`** (entrada): conecta el búnker con la superficie/exterior. Varias = más acceso propio
  pero **más superficie de ataque** (cada puerta es visible al que te mapea).
- **`lockdown`** (cerradura) + **`ventilation`** (ventilación): defensas (§3.5), requieren `bunker_defense`.

### 3.4 Entradas, brechas y visibilidad
- **Tus puertas** aparecen en **tu** mapa. Una **brecha** (`breach`) es una entrada que un ATACANTE
  te abre desde afuera para meterse.
- **Ubicar el enemigo**: para atacar el búnker enemigo primero tenés que **saber dónde está** su HQ →
  sale de la intel satelital (SDD 61): con `discovered_pct` alto ves su búnker/HQ; si no, cavás "a
  ciegas" y hay **azar** de dar con él. Al abrir una brecha, **el defensor ve la puerta nueva en su
  mapa** (alerta) → corre a sellarla (cerradura) o defenderla con tropas.
- Mientras no tengas **cerraduras** en tus entradas, **cualquiera con una brecha entra** y pelea adentro.

### 3.5 Defensas del búnker
- **Cerradura (`lockdown`)**: sella una entrada/brecha → bloquea el ingreso hasta que el atacante la
  fuerce (tiempo/fuerza). Sin cerradura, la entrada está **abierta**.
- **Ventilación (`ventilation`)**: reduce el daño del **gas tóxico** (§3.6). Nivel de ventilación =
  Σ de las salas de ventilación → factor de mitigación (p.ej. cada una −25% al daño de gas, tope).

### 3.6 Ataque dentro del búnker + estado (salud de comida/agua/gente)
El búnker tiene tres **medidores de salud (0–100)**: **comida**, **agua**, **gente** (moral/salud).
Un atacante que entró (por brecha en una entrada sin cerradura) elige una acción de **sabotaje** en la
misma pantalla del mapa de búnkeres (clic en la puerta → atacar):
- **Gas tóxico**: baja la salud de **gente**; mitigado por `ventilation` (con ventilación, el golpe es
  menor).
- **Ratas**: baja la **comida** (se pudre); mitigado por sellado/limpieza (v2).
- **Contaminar agua**: baja el **agua** → arrastra la salud de **gente** con el tiempo; mitigado por
  `water_recycling` (v2).
- Combate directo: si el defensor tiene tropas en esa base, se resuelve un combate localizado (reusa
  `resolve_combat`, SDD 62) antes de que el atacante pueda sabotear.
- **Consecuencias**: gente a 0 → el búnker queda inoperante (deja de producir/investigar) hasta
  recuperarse; comida/agua a 0 → la gente empieza a caer (lazy by timestamp, como energía). NUNCA se
  "pierde" el búnker/HQ (coherente con SDD 62): se degrada y se recupera.
- **Recuperación**: comida (farm/canteen) y agua (water_reserve) regeneran los medidores lazy; sellar la
  brecha corta el sabotaje.

## 4. Modelo de datos
- **`Bunker`** (o extender `Base_` con `layer`): por jugador/base; medidores `food_health`,
  `water_health`, `people_health` (0–100), `updated_at` (regen lazy).
- **`BunkerCell`/rooms**: celdas del mapa subterráneo + su habitación (reusar `Building` con
  `layer=underground` y una coord). **`BunkerDoor`**: entradas (propias) + brechas (status: sealed/open).
- **`BunkerRaid`**: incursión de un atacante (entró por brecha) + acción de sabotaje en curso.
- Snapshot `/players/me`: `bunker` (tus medidores + mapa + puertas) y, si mapeaste, `enemy_bunkers`.
  API: `/bunker/dig`, `/bunker/build-room`, `/bunker/seal`, `/bunker/breach`, `/bunker/raid`.

## 5. Tests
- `test_bunker.py`: cavar abre el mapa; construir habitaciones sube capacidad; los medidores regeneran
  lazy; el gas baja `people_health` y la ventilación lo mitiga; ratas bajan comida; agua contaminada
  arrastra gente; sellar corta el sabotaje; sin cerradura una brecha permite el raid.
- e2e (`test_api_e2e.py`): investigar `bunker_engineering` → cavar → construir sala → (con satélite al
  100% del enemigo) abrir brecha → raid con gas → el defensor ve la puerta y su `people_health` baja
  (menos si tiene ventilación).
- Invariante: un búnker nunca se "pierde" (se degrada y recupera); ubicar al enemigo depende de la intel
  satelital (sin mapeo, azar).

## 6. Rollout / flags / riesgos
- Feature grande y NUEVA (capa subterránea) → varios pasos detrás de `bunkers_enabled` (default OFF):
  (1) research + túnel + mapa + habitaciones (economía de comida/agua/gente lazy), (2) entradas +
  brechas + visibilidad por intel satelital, (3) defensas (cerradura/ventilación), (4) sabotaje (gas/
  ratas/agua) + combate localizado, (5) panel web (mapa subterráneo, misma pantalla) + NPC + prender.
- Data-driven (habitaciones/costos en YAML), aditivo, por el pipeline de Argo. e2e + tests por paso.
- Riesgo: mucha superficie nueva (2ª capa) → arrancar simple (grilla chica, 3 medidores) y expandir.
  Depende de SDD 61 (satélites) para la parte de ubicar al enemigo.

## 7. Preguntas abiertas
- ¿El mapa subterráneo es una **grilla** (coordenadas) o un **grafo** de celdas conectadas? (Propuesta:
  grilla chica NxN por base para v1.)
- ¿Las "armas atómicas" del `atomic_lab` son las mismas del SDD 49 (nuclear_missile) guardadas abajo, o
  una nueva arma de búnker? (Propuesta: reusar SDD 49; el lab subterráneo las protege del bombardeo.)
- ¿El raid de sabotaje respeta los topes de ataque diarios (SDD 55)? (Propuesta: sí, para no farmear.)
- ¿La gente del búnker es un recurso nuevo o reusa `worker`/población? (Propuesta: recurso nuevo
  "población de búnker" con su salud, separado de las unidades de superficie.)
