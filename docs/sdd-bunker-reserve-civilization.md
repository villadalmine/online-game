# SDD 69 — El búnker como civilización de reserva + vida artificial (IA autónoma)

> **Estado:** **DISEÑO** 2026-07-02 · **Pedido:** usuario, 2026-07-02.
> Evolución mayor del [SDD 64 (búnkeres atómicos)](sdd-atomic-bunkers.md): el búnker deja de ser solo
> "medidores + sabotaje" y pasa a ser una **mini-base subterránea completa** — tu **civilización de
> reserva** para sobrevivir una guerra nuclear y **volver a salir a conquistar** cuando la superficie
> quedó arrasada. Incluye **naves de carga para escapar/colonizar** y un **super-proyecto de vida
> artificial**: IA con robots de trabajo autónomos que gestionan minería, exploración, colonización y
> comercio **solos**, corriendo sobre la GPU local (SDD 9/28/65). Vos **desarrollás la inteligencia**
> por niveles; eso también **potencia a los NPC**.
> **Relacionado:** [SDD 64 búnkeres](sdd-atomic-bunkers.md), [SDD 65 NPC autónoma](sdd-npc-autonomous-intelligence.md)
> (mismo cerebro/observabilidad), [SDD 61 satélites](sdd-satellites-recon.md), [SDD 37/42 colonización/
> materiales por planeta](sdd-colonization.md), [SDD 47 minería/obreros](sdd-mining-workers-storage.md),
> [SDD 57 hiperespacio](sdd-hyperspace-base-buster.md) (viaje), [SDD 9/28 LLM/GPU](sdd-llm-usage-metrics.md),
> [[unified-graph-model-for-ai]] (todo entra al grafo data-driven).

## 1. Pedido (usuario, 2026-07-02, textual resumido)
- El búnker es **una mini-base como la de superficie, pero bajo tierra**. Hay que darle **las mismas
  prestaciones**: defensa y ataque **mínimos**, y **mucho research + acopio de los materiales más
  importantes**, para que **si pasa algo en una guerra nuclear**, la civilización pueda **volver a
  salir y conquistar**, aprovechando que "se fue todo al carajo".
- **Naves de carga** para **salir a explorar otro planeta** por si ya no se puede vivir en el tuyo.
- **Super-proyecto: vida artificial** → evoluciona a tener **IA con robots de trabajo autónomos**.
  Estos se manejan **solos** y se encargan de que **toda tu exploración minera de todos los tipos esté
  siempre al día**, e incluso **exploran otros planetas en naves para colonizar minerales y traerlos**
  a tu planeta, y **hasta comercian**. Todo usando **GPU local y aprendizaje**.
- Pero **vos** tenés que **desarrollar la inteligencia en el búnker**. Hay que definir **varios niveles
  de inteligencia** basados en **qué tan bueno puede ser explorando cada tipo de mineral, cada tipo de
  viaje al espacio para explorar planetas, eficiencia de velocidad, calidad**, y cosas realistas. Eso
  **activa más inteligencia a los NPC** y **dalmine puede definir si quiere más**.
- Si **te quedás sin espacio** en el búnker, hay que tener el tipo de construcción **"explorar
  subterránea"** y el **research de construcción subterránea** (expandir el búnker hacia abajo).

## 2. Principio rector
Data-driven y aditivo (no romper): **habitaciones, naves, niveles de IA y sus efectos viven en YAML**
(`content/underground.yaml`, `content/*_tech`, un nuevo `content/artificial_life.yaml`). El motor solo
lee esos números. Todo detrás de flags (default OFF) hasta balancear. La IA autónoma reusa el **cerebro
y la observabilidad ya existentes** (SDD 65: cadena GPU→cloud→reglas, `game_llm_*`), no inventa un stack
nuevo.

## 3. Fases

### Fase 1 — Búnker = mini-base subterránea (defensa/ataque/acopio/research)  ⟵ en curso
Hoy el búnker solo tiene salas de vida (comida/agua/gente) + electrónica. Sumar salas que lo hagan una
**base completa en miniatura**, todas `requires_tech` (árbol subterráneo) y con costo por rol (SDD 53):
- **`vault` (bóveda de materiales)** ✅ **HECHO (1.142.0):** acopia minerales a salvo del saqueo/
  guerra (la superficie se puede arrasar; la bóveda no — el loot solo toca `ResourceStock` de
  superficie, así que lo guardado queda intacto). Sala `vault` (`vault_storage` 5000 c/u) da capacidad;
  `POST /bunker/stash` (superficie→bóveda, topeado) y `/bunker/withdraw` (bóveda→superficie); modelo
  `BunkerStock` (migración `343867d85a30`); snapshot `vault`/`vault_cap`; panel con guardar/sacar. Es
  tu reserva para **reconstruir y volver a conquistar**. Tests: `test_vault_stash_withdraw_safe_from_loot`
  + e2e `test_bunker_vault_stash_withdraw_e2e`.
- **`bunker_turret` (defensa subterránea)** — `defense_power`/`intercept_power` **bajos** (el búnker
  no es un fuerte; es refugio). Defiende contra la invasión física (Fase 4 del SDD 64 / abajo).
- **`bunker_armory` (arsenal subterráneo)** — permite **fabricar/almacenar** un ataque **mínimo**
  (unidades para re-emerger, no una flota). Ataque de re-conquista, no de guerra total.
- **Research subterráneo fuerte** — `research_room`/`atomic_lab` ya dan electrónica; sumar salas que
  aporten **velocidad de investigación** (multiplicador `research`) mientras la superficie está caída.
- **Re-emerger:** los **sets de repoblación** (`content/repopulation_sets.yaml`, ya existe) son el
  mecanismo de "volver a salir": gastás la electrónica acumulada → reconstruís edificios de superficie
  de una. Enlazar narrativamente: el búnker es lo que te deja **volver a conquistar**.

### Fase 2 — Expansión subterránea (quedarse sin espacio)  ✅ HECHO (1.141.0)
- **Tech `underground_construction`** ("Construcción subterránea", cat underground) — habilita
  **agrandar el búnker**.
- **Acción "excavar"** (`dig_deeper`, `POST /bunker/dig-deeper`): expande la **grilla** del búnker
  (+1 lado, `Bunker.grid_level`; lado efectivo = `bunker_grid` + nivel, tope `bunker_grid_max=8`),
  con **costo estructural creciente por nivel** (`bunker_dig_cost_structural × (nivel+1)`) + energía
  (`bunker_dig_energy_cost`). Detrás de `bunker_expansion_enabled` (default OFF). `build_room` usa el
  lado por-búnker; el snapshot expone `side`/`grid_level`; el front muestra "⛏ excavar (N×N)".
  Migración `a0c34235e05b`. Tests: `test_dig_deeper_expands_grid`/`_needs_tech_and_flag` + e2e
  `test_bunker_dig_deeper_e2e`. Es el "explorar subterránea" del pedido.

### Fase 3 — Naves de carga y escape/colonización desde el búnker
- **Unidad `colony_ship` (nave de carga/colonización)** — se fabrica en el cosmódromo o en una sala del
  búnker (`launch_bay`). Sirve para **salir a otro planeta** llevando material/gente cuando el tuyo ya
  no es habitable. Reusa el sistema de **colonización (SDD 37/42)** y **viaje/hiperespacio (SDD 57)**.
- **Escape:** si tu planeta natal queda inhabitable (fallout severo/repetido), la nave de carga permite
  **trasladar la sede** (o fundar la colonia que se vuelve tu nueva base fuerte). v1: fundar colonia +
  mover acopio del búnker; "mudar el HQ" es v2 (evaluar balance).

### Fase 4 — Vida artificial: IA con robots autónomos (super-proyecto)  ⟵ el corazón del pedido
El **super-proyecto** del búnker. Se **investiga por niveles** (`artificial_life` L1..Ln en YAML). Cada
nivel cuesta electrónica + minerales avanzados + tiempo, y **desbloquea automatización**:
- **Robots autónomos que trabajan solos.** A partir de cierto nivel, tareas del jugador **se ejecutan
  automáticas** en el `advance`/tick (nunca crons por jugador — sigue el patrón lazy del proyecto):
  - **Minería siempre al día:** auto-asignar obreros, auto-recolectar, auto-construir/mejorar minas de
    **todos los tipos** de mineral que el nivel domina.
  - **Exploración/colonización autónoma:** despachar naves a colonizar minerales de otros planetas y
    **traer** el material (viaje real, SDD 57).
  - **Comercio autónomo:** vender excedente / comprar faltante (reusa el mercado, SDD 42).
- **Niveles de inteligencia = qué tan bueno es en cada eje (realista y data-driven):**
  | Eje | Qué escala con el nivel |
  |---|---|
  | `mining_skill` por tipo de mineral | qué minerales sabe explotar bien (rinde más / desperdicia menos) |
  | `travel_skill` por tipo de viaje | superficie / orbital / interplanetario / hiperespacio |
  | `speed_efficiency` | qué tan rápido hace cada tarea (menos tiempo de viaje/tarea) |
  | `quality` | tasa de éxito / calidad del resultado (menos fallos, mejor botín/colonia) |
  | `autonomy_scope` | qué tareas puede hacer solo (minar → colonizar → comerciar) |
  Todo en `content/artificial_life.yaml`: cada nivel declara sus skills. **Extender = editar YAML.**
- **Corre sobre la GPU local + aprendizaje (SDD 9/65):** las decisiones "no triviales" del piloto
  autónomo (qué planeta colonizar, qué comerciar) pueden delegarse al **mismo cerebro LLM** (cadena
  GPU→cloud→reglas, con presupuesto). Lo determinista (recolectar, asignar obreros) es reglas puras
  (barato, cada tick). Observabilidad reusa `game_llm_*` (SDD 65) + métricas nuevas de automatización.
- **Potencia a los NPC:** el nivel de vida artificial que la comunidad/tu imperio desarrolla **sube el
  techo de inteligencia de los NPC** — p.ej. NPCs con vida-artificial alta usan más presupuesto LLM /
  mejor modelo / más autonomía. **dalmine (admin) define el techo** con un knob de config
  (`artificial_life_npc_ceiling`), "si quiere más".

## 4. Data-driven (esquemas nuevos)
- `content/underground.yaml`: nuevas `rooms` (vault, bunker_turret, bunker_armory, launch_bay, salas de
  research-speed) con `requires_tech`, costo por rol, y el efecto (storage/defense/intercept/research).
- `content/technologies.yaml`: `underground_construction`, `artificial_life` (o niveles L1..Ln con
  `requires_techs` encadenados), en cat `underground`.
- `content/artificial_life.yaml` (**nuevo**): niveles con `mining_skill{mineral:0-1}`,
  `travel_skill{tipo:0-1}`, `speed_efficiency`, `quality`, `autonomy_scope[]`, costo y tiempo.
- `content/units.yaml`: `colony_ship` (carga/colonización).
- `app/core/config.py`: flags `bunker_base_enabled`, `underground_expansion_enabled`,
  `artificial_life_enabled`, `bunker_autonomy_enabled` + params (grid por nivel, techo NPC, presupuesto
  LLM del piloto autónomo).

## 5. Cómo encaja / reúso (no reinventar)
- **Combate/defensa:** el búnker reusa `_building_defense` y la intercepción (SDD 49/67) con valores
  bajos; la invasión física es el combate localizado del SDD 62/64.
- **Colonización/viaje/mercado:** Fase 3 y el piloto autónomo reusan SDD 37/42/57 tal cual (el robot es
  "un jugador que juega por vos", igual que un NPC juega su imperio).
- **Cerebro/observabilidad:** el piloto autónomo y el techo NPC reusan SDD 65 (cadena de modelos +
  `game_llm_*`). No hay stack de IA nuevo.
- **Lazy, no crons:** toda la automatización corre en `advance()`/`run_tick()` (patrón del proyecto).

## 6. Tests (regla del proyecto: e2e por feature)
- Fase 1: e2e cavar + construir vault/bunker_turret + que el acopio de la bóveda **sobrevive** a un
  nuclear que arrasa la superficie; que la defensa subterránea suma en una invasión.
- Fase 2: e2e `dig_deeper` agranda la grilla y permite una sala que antes no entraba.
- Fase 3: e2e fabricar `colony_ship` + colonizar otro planeta desde el búnker.
- Fase 4: e2e subir un nivel de `artificial_life` → con `bunker_autonomy_enabled`, un `advance`
  auto-recolecta/auto-coloniza según el `autonomy_scope` del nivel; test de que el techo NPC sube.
- Servicio: puros para skills (mining/travel/speed/quality) y para el planificador autónomo determinista.

## 7. Decisiones del usuario (2026-07-02)
1. **Escape (Fase 3):** **fundar colonia + trasladar acopio** (conservador; no muda el HQ en v1).
2. **Alcance de la automatización (Fase 4):** **TODO — el robot también ataca/defiende** (no solo
   economía). El piloto autónomo juega por vos como un NPC completo. (Máxima ambición → llega detrás de
   flags y con más balance/tests; se habilita por partes: economía → defensa → ataque.)
3. **Presupuesto LLM del piloto autónomo:** **GPU local + reglas, nube solo como rescate** (barato y
   sostenible; lo determinista por reglas cada tick, lo no trivial por GPU).
4. **Orden:** **Fase 1 completa primero** (búnker mini-base + expansión subterránea), después Fases 3/4.
5. **Techo de IA para NPC (`artificial_life_npc_ceiling`):** knob admin (lo fija dalmine) + tope por
   partida (pendiente de detalle al llegar a Fase 4).
```
```
