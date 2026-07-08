# SDD 78 — Grafo de habilidades de la IA robot (vida artificial)

## Idea (del usuario)
Desarrollar la IA en el búnker es para **dejarla jugando sola de forma que sepa qué hacer**. Hay que
definir bien el **grafo de habilidades**: qué hace cada una, en qué nivel se desbloquea, cómo la
obtenés al mejorar tu IA, cómo hace que tu IA juegue **casi como vos**, y **mostrar cómo aprende**.
Al final debe igualar o superar a la NPC.

## Modelo (data-driven, `content/artificial_life.yaml`)
- **`skills`**: catálogo de cada habilidad — `key` (coincide con el `autonomy_scope` y el despacho del
  autopiloto), `icon`, `name`/`description` (ES/EN). Habilidades:
  `workers` 👷 · `mines` ⛏ · `trade` 💱 · `colonize` 🪐 · `defend` 🔫 · `research` 🔬 · `attack` ⚔ ·
  `diplomacy` 🕊 · `learn` 🧠.
- **`levels`** (1..7): cada uno DESBLOQUEA más skills (`autonomy_scope` acumulativo), con `quality`
  (base de acierto) y `speed_efficiency`. Subir de nivel = electrónica del búnker + minerales
  avanzados + tiempo (`evolve_ai`, ya existía).
  - L1 embrionaria `[workers]` · L2 operativa `+mines` · L3 mercante `+trade` · L4 colona `+colonize`
  - **L5 guardiana `+defend +research`** (se protege sola) · **L6 soberana `+attack`** (= nivel NPC)
  - **L7 trascendente `+diplomacy +learn`** (supera a la NPC).

## Autopiloto (`run_ai_autopilot`, corre en el tick)
Despacha por `autonomy_scope`. Implementado: `workers`/`mines`/`trade`/`colonize`/`attack` (previos) +
**`defend`** (`_auto_defend`: torreta en una base sin defensa activa — requiere research_lab+weapons,
si no puede, no hace nada) y **`research`** (`_auto_research`: investiga la tech de economía/defensa más
barata y asequible). Todo acotado, con try/except por skill, y detrás de `bunker_autonomy_enabled` +
el botón STOP del jugador.

## Cómo APRENDE (visible)
`ai_learning(session, player)`: **xp = nº de jugadas del autopiloto** (del journal `ai_autopilot`, sin
migración). La **calidad efectiva** sube con la experiencia: `quality_eff = quality_base +
min(0.5, 0.06·log10(1+xp))`, topeada. Se expone en el snapshot (`ai.learning`).

## UI (panel 🤖)
Muestra el **grafo completo**: cada skill con ✓ (desbloqueada, `nivel ≥ nivel que la abre`) o 🔒 + el
nivel que la abre, con su descripción en el tooltip. Y la línea de **aprendizaje**: "🧠 aprendió N
jugadas · calidad efectiva X% (base Y%)". El detalle de qué hizo está en 📈 Tu historia → 🤖 Tus robots.
Todo data-driven (catálogo `ai_skills`/`ai_levels`), front sin lógica hardcodeada.

## Tests
`test_ai_life.py`: `test_auto_defend_builds_turret_on_undefended_base`,
`test_ai_learning_grows_with_experience`, `test_auto_attack_hits_a_beatable_enemy` (ahora L6).

## v2 (HECHO) — la IA juega como vos + sube el techo de las NPC
- **El aprendizaje MODULA las decisiones**: la calidad efectiva (`quality_eff`) afila el autopiloto —
  el cap de obreros por tick escala (`* (0.5 + q)`) y el margen de ataque se ajusta
  (`ai_attack_margin - (q-0.5)*0.6`, piso 1.05): una IA entrenada staffea más rápido y se anima a
  peleas más ajustadas, como un jugador con experiencia.
- **Behavior `diplomacy`** (`_auto_diplomacy`): ante un nuclear entrante, si tenés government +
  diplomacy, ofrece un tributo modesto (10% del estructural, tope 2000) para que lo cancelen.
- **Tu IA sube el techo de las NPC**: el tick calcula el mayor `ai_level` humano y lo pasa a
  `npc.set_player_ai_ceiling`; `npc_effective_epsilon` usa `max(admin_ceiling, player_ceiling)` →
  entrenar TU IA hace que TODAS las NPC exploren más estrategias (más inteligentes).

## v3 (HECHO) — espionaje autónomo + aprende de sus batallas
- **Skill `spy`** (L6+): `_auto_spy` lanza un satélite espía a un rival que aún no espía (conocer su
  defensa antes de atacar; requiere satélites ON + un `spy_satellite`).
- **Aprende de sus batallas**: `_own_attack_winrate` mira los últimos 10 ataques propios (del
  `CombatLog`); si viene perdiendo (≥4 batallas, win-rate <40%) el `_auto_attack` sube el margen +0.5 →
  ataca más cauto. Sumado a la modulación por experiencia (v2).

## v4 (HECHO) — expediciones autónomas
- **Skill `expedition`** (L6+): `_auto_expedition` manda 1 expedición a una luna de tu galaxia que no
  tengas ya en viaje (bonus de dioses/recursos); `start_expedition` valida la unidad requerida (shuttle)
  + energía. Skills totales de la IA: 11 (workers/mines/trade/colonize/defend/research/spy/expedition/
  attack/diplomacy/learn).

## v5 (HECHO) — repoblación autónoma + repopulate idempotente
- **`repopulate` ahora es IDEMPOTENTE**: reconstruye solo lo que FALTA para llegar a los conteos del
  set (respeta multiplicidad, ej. 2 minas) y cobra electrónica proporcional a lo que realmente levanta.
  Si ya está completo, avisa "nada que reconstruir". Fix útil también para el botón manual.
- **Skill `repopulate`** (L5+): `_auto_repopulate` — si te ATACARON en la última hora y a una base le
  faltan edificios de algún set, gasta electrónica para reconstruir lo que falta (1 set/tick).
- La IA robot cubre **12 skills**: workers/mines/trade/colonize/defend/research/repopulate/spy/
  expedition/attack/diplomacy/learn.

## v6 (HECHO) — composición por meta aprendida
- Con el skill `learn` (L7), `_auto_attack` usa `_meta_best_unit` (de `insights`/SDD 41): prioriza la
  unidad con mejor win-rate real (full de esa, 0.6x de las otras). Aprende del meta global, no solo de
  sus batallas. La IA robot queda COMPLETA: 12 skills + aprendizaje por experiencia, por batallas propias
  y por meta global.

## v7 (HECHO) — postura aprendida (tipo bandit)
- **`ai_posture(session, player)`**: la IA elige POSTURA con el win-rate de sus últimos ataques —
  **agresiva** (≥60%), **defensiva** (<40%), **balanceada** (sin evidencia). En `_auto_attack` la
  postura modula el **margen** (agresiva −0.2, defensiva +0.5) y la **reserva** (agresiva ×0.7,
  defensiva ×1.5): confiada pelea más ajustado comprometiendo tropa; cauta solo golea y guarda en casa.
  Se registra en el journal del ataque y se **muestra en el panel 🤖** (postura + calidad + experiencia).

## v8 (HECHO) — la IA cuida su búnker y su alojamiento
- Pedido del usuario: *"la IA debería focalizarse también en el búnker, y darse cuenta si no tiene
  suficiente espacio para unidades o si le faltan tecnologías"*.
- **Skill `bunker`** (L2+): `_auto_bunker` — si tiene `bunker_engineering` y `bunkers_enabled`, cava el
  búnker si falta (`dig`) y si ya existe construye una **sala de investigación** (electrónica, la moneda
  que sostiene y evoluciona la IA). Así la IA se autoabastece de electrónica para subir de nivel.
- **Skill `housing`** (L2+): `_auto_housing` — lee `housing_report` por dominio; si un dominio quedó
  **sin plazas** (unidades sin alojar) construye el edificio que lo aloja (`houses_for_domain`) en la
  natal. Cierra el bug de "entreno unidades y no tienen dónde ir".
- La IA robot cubre ahora **14 skills** y ambas se desbloquean **temprano** (nivel 2), porque búnker y
  alojamiento son la base para todo lo demás. Tests de servicio + e2e (catálogo publica ambos skills y
  su presencia en el `autonomy_scope` del nivel 2).
- La detección de tecnologías faltantes ya la cubre el skill `research` (investiga la próxima tech
  asequible); `bunker` agrega el prerequisito específico `bunker_engineering` como puerta.

## v9 (SDD 85) — el búnker se agranda solo + guarda materiales (reportado jugando)
El usuario notó que su autopiloto (nivel 7) "hace siempre lo mismo, en el búnker no excava cuando se
queda sin espacio y no guarda materiales". Dos arreglos:
- **`_auto_bunker` ahora EXCAVA cuando el búnker está lleno:** si `build_room` falla por falta de
  espacio, llama a `dig_deeper` (agranda +1 de lado; requiere `underground_construction` +
  `bunker_expansion_enabled`). Antes se quedaba sin lugar y no hacía nada.
- **Skill nuevo `stash` (🗄 Reserva en bóveda):** `_auto_stash` guarda el mineral más abundante por
  encima del umbral de excedente en la bóveda del búnker (a salvo del saqueo), topeado por la
  capacidad libre. Antes la IA nunca guardaba → si te atacaban, perdías todo. Desbloqueado en el
  **nivel 2** (junto a búnker; necesita la sala Bóveda activa). La IA robot cubre ahora **15 skills**.
- Tests: `test_auto_stash_saves_surplus_to_vault` + e2e (catálogo publica `stash` en el scope L2).

## Follow-ups
- `quality_eff` en más decisiones (umbral de comercio, selección de objetivo).
- Explore epsilon-greedy real en la postura (hoy es exploit puro del win-rate).
- Ampliar el set de acciones del AGENTE (SDD 83) para paridad con el determinista (búnker/stash/
  colonize/etc.), y evaluar niveles 8+ con capacidades nuevas si hace falta más profundidad.
