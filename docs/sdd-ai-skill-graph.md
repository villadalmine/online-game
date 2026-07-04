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

## Follow-ups (iterar)
- Implementar los behaviors de `diplomacy` (auto ofrecer/aceptar tributo) y `learn` como un efecto real
  (que `quality_eff` module decisiones: margen de ataque, cap de obreros, etc.).
- Que la calidad efectiva ALIMENTE al cerebro NPC (techo `artificial_life_npc_ceiling`) → tu IA
  entrenada sube el nivel de TODAS las NPC.
- Más skills: espionaje autónomo (satélites), expediciones a lunas, repoblación tras ataque.
