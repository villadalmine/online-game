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

## Follow-ups (v5)
- **Repoblación autónoma**: hoy `repopulate` reconstruye TODO el set (duplicaría edificios) → primero
  hacerlo idempotente (saltear los ya presentes), después un `_auto_repopulate` que dispare tras un ataque.
- Elegir postura/objetivo con la meta aprendida (SDD 41) y `bandit_posture`.
- `quality_eff` en más decisiones (reserva de ataque, umbral de comercio).
