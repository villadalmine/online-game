# SDD 29 — Inteligencia estratégica de NPCs (cerebro de 2 capas + conciencia del scoreboard)

> **Estado:** propuesto · **Fecha:** 2026-06-24
> **Relacionado:** `app/services/npc.py`, [SDD 12 métricas/score](sdd-player-metrics-public.md),
> [SDD 8 galaxias](sdd-galaxy-limits.md), [SDD 9 LLM en GPU](sdd-local-gpu-llm.md),
> [SDD 28 métricas LLM por usuario](sdd-llm-usage-metrics.md), `app/services/scoring.py`,
> `app/services/stats.py`, `app/worker.py`.

## 1. Objetivo
Que las NPC sean **más inteligentes y adaptativas**: que **cada tanto lean cómo vienen los demás**
(scoreboard + crecimiento) y **analicen sus propios recursos**, y a partir de eso **cambien de
postura** (p.ej. se vuelvan **agresivas** contra el líder, o defensivas si están débiles), en vez de
decidir sólo turno a turno. Efecto secundario deseado: **más uso de GPU/LLM** (la capa estratégica es
un prompt grande y periódico) → util visible en los dashboards (SDD 28).

## 2. Estado actual (verificado)
- `app/services/npc.py`: `LlmBrain` (o `RuleBasedBrain` de fallback). En cada **tick** (`worker.run_tick`,
  ~5 min), `run_npc_turn` → `_npc_state(player)` arma un snapshot (personalidad de la raza, energía,
  minerales, unidades, edificios + costos, **enemigos adyacentes** con `is_human`/units/`defense_estimate`,
  ataques entrantes, misiones, lunas, **memoria corta** `Player.npc_memory`) → `_llm_decide(state)`
  elige **UNA acción** acorde a la personalidad. Fallback a reglas si el LLM falla.
- **Limitaciones que ataca este SDD:**
  1. La NPC **no ve el scoreboard** ni el crecimiento de los demás (sólo bases vecinas) → no puede
     razonar "quién va ganando / a quién conviene atacar".
  2. **No hay postura estratégica persistente**: decide táctico turno a turno, sin un plan que evolucione.
  3. La "memoria" son sólo las últimas acciones, sin reflexión.

## 3. Diseño

### 3.1 Cerebro de 2 capas
- **Capa ESTRATÉGICA (periódica, lenta):** corre **cada `npc_strategy_every_ticks`** (no en cada tick).
  Una llamada LLM **más profunda** que recibe el **scoreboard de su galaxia** + su **trayectoria de
  recursos** + amenazas/oportunidades y devuelve una **postura** + **objetivo** + rationale corto.
  Se **persiste** en el `Player`.
- **Capa TÁCTICA (per-turn, rápida — la actual):** `_llm_decide` sigue eligiendo una acción por turno,
  pero ahora con la **postura inyectada** en el prompt → sus decisiones quedan sesgadas por la
  estrategia vigente (agresivo ⇒ prioriza atacar; defensivo ⇒ torretas/recall; expansión ⇒ minas/expediciones).

### 3.2 Conciencia del scoreboard
Nueva función `npc_scoreboard(session, player)` (reusa `scoring.player_score` y el ranking de
`stats.py`), **acotada a la galaxia de la NPC** (`galaxy_instance_id`, SDD 8):
```python
[
  {"name": "<nick>", "is_human": true, "score": 1234, "rank": 1,
   "delta": 180,            # crecimiento de score desde la última evaluación (trayectoria)
   "is_leader": true},
  ...
]
```
`delta` sale de comparar contra un snapshot previo (guardado en la estrategia) → la NPC "infiere cómo
vienen los demás" (quién acelera). Datos de `PlayerStats` (SDD 12) para el detalle (saqueado/minado/etc.).

### 3.3 Postura + objetivo (persistido)
Enum de postura (data-driven, ampliable):
- `aggressive` — atacar; preferir al **líder humano** o al de mayor `delta`.
- `defensive` — torretas, recall, no exponerse.
- `expand` — minas/edificios/expediciones (economía).
- `raid` — golpes de saqueo a vecinos débiles ricos.
- `opportunist` (default) — mezcla según contexto.

Se guarda en el `Player`: `npc_posture`, `npc_target_id` (a quién apunta), `npc_strategy`
(JSON: rationale + snapshot de scores para el `delta`), `npc_strategy_updated_at`.

### 3.4 Prompt estratégico (LLM)
- **Input** (JSON): personalidad de la raza, su propio `score`/recursos/unidades/defensa, el
  `scoreboard` (§3.2 con deltas), amenazas (ataques entrantes), y la postura previa.
- **Output** (JSON, parse-safe con `json_mode`):
  ```json
  {"posture":"aggressive","target":"<nick|null>","why":"el líder humano me saca 2x y crece rápido; lo hostigo"}
  ```
- Si falla / parse inválido / sin LLM → **mantiene la postura anterior** (o `opportunist`): nunca rompe.

### 3.5 Integración táctica
`_npc_state` suma `"posture"` y `"target_hint"`; el system prompt táctico agrega una línea
("Tu estrategia actual es {posture}; objetivo {target}"). El `RuleBasedBrain` también puede leer la
postura (si `aggressive` y hay enemigo batible → ataca; etc.) → la inteligencia estratégica **mejora
también el modo reglas**, no sólo el LLM.

### 3.6 Cadencia, costo y GPU
- `npc_strategy_every_ticks` (default p.ej. 6 = ~cada 30 min con tick de 5 min): la capa estratégica
  corre 1 vez cada N turnos por NPC → costo acotado.
- **Sube el uso de GPU** (prompt grande y periódico) → util/tokens visibles (SDD 28), **atribuido a
  `npc:<nombre>`** (cada NPC mide su gasto, y en qué placa/backend).
- Fallback (SDD 9): LLM caído/lento → la NPC sigue con su postura previa + reglas.

### 3.7 Reflexión post-batalla (opcional, fase 2)
Tras una batalla relevante (gana/pierde), un mini-LLM "reflexiona" y ajusta `npc_strategy`/memoria
("perdí contra X, paso a defensivo"). Más uso de GPU + NPCs que **aprenden** del resultado.

## 4. Modelo de datos (aditivo, en `Player`)
- `npc_posture: str` (default `opportunist`)
- `npc_target_id: int | None`
- `npc_strategy: Text` (JSON: rationale + snapshot de scores p/ deltas; default `{}`)
- `npc_strategy_updated_at: datetime | None`
- (existe ya `npc_memory`)
Migración Alembic aditiva (`server_default` en SQLite, ver CLAUDE.md).

## 5. Config (`app/core/config.py`)
- `npc_strategy_enabled: bool = True`
- `npc_strategy_every_ticks: int = 6`
- `npc_strategy_max_tokens: int = 250`
- (reusa `npc_brain`, `llm_*`, fallback de SDD 9)

## 6. Métricas
- Por NPC vía `user="npc:<nombre>"` (SDD 28): tokens/requests/spend de la capa estratégica vs táctica,
  por backend (GPU/nube). → se ve qué NPC "piensa más" y cuánto cuesta.
- Opcional: contador `game_npc_strategy_runs_total{posture}` en `/metrics` (SDD 19).

## 7. Otros componentes que pueden usar GPU (futuro, fuera de alcance v1)
- **Reflexión post-batalla** (§3.7). **Eventos del mundo** narrativos. **Diplomacia/chatter** de
  alianza (hay taunts). **Lore dinámico** para spin-offs (SDD 26). Todos con fallback y medibles (SDD 28).

## 8. Tests (regla del proyecto)
- **Servicio:** `npc_scoreboard` acota a la galaxia (SDD 8) y calcula `delta`; `decide_strategy`
  (inyectando un fake LLM) setea `npc_posture`/`npc_target_id`; sin LLM o parse inválido → mantiene la
  postura previa (no rompe). La capa táctica respeta la postura (aggressive ⇒ tiende a atacar).
- **e2e:** tras correr el tick N veces, una NPC tiene `npc_posture` seteada; el endpoint público
  (`/public/*`, SDD 12) no expone datos privados. Caso de error: LLM caído ⇒ NPC sigue jugando (reglas).
- **Idempotencia/cadencia:** la estrategia se recalcula sólo cada `npc_strategy_every_ticks`.

## 9. Riesgos / decisiones
- **Costo/latencia:** la capa estratégica es periódica (no por turno) → costo acotado; cae al fallback
  bajo carga (SDD 9). Mensurable por NPC (SDD 28).
- **Balance/jugabilidad:** NPCs "cazar-al-líder" no deben ahogar a un humano puntero → respetar
  **newbie protection** (SDD 11) y límites de galaxia (SDD 8); la agresión coordinada ya existe, esto
  la hace adaptativa, no infinita.
- **Determinismo de tests:** la capa estratégica es inyectable (fake decide) como el `LlmBrain` actual.
- **Privacidad:** el scoreboard usa nick/score público (SDD 12), nunca email (SDD 20).

## 9.bis Estado de implementación (2026-06-24) — v1
- **Modelo**: `Player.npc_posture`/`npc_target_id`/`npc_strategy`/`npc_strategy_updated_at` + migración.
- **`npc.py`**: `npc_scoreboard` (galaxia-scoped, con `delta`), `_llm_strategy` (LLM estratégico
  inyectable), `decide_strategy` (cadencia por tiempo `npc_strategy_interval_seconds`; sin LLM o
  fallo → mantiene la postura previa; valida `POSTURES`). Enganchado en `run_npc_turn`.
- **Táctico**: `_npc_state` expone `posture` y marca `enemies[].is_target`; el prompt táctico la
  respeta; `RuleBasedBrain` prioriza `npc_target_id` al atacar (mejora también el modo reglas).
- **Métricas**: la capa estratégica va atribuida a `npc:<nombre>` (SDD 28) → tokens/spend por NPC.
- **Config**: `npc_strategy_enabled`, `npc_strategy_interval_seconds` (1800), `npc_strategy_max_tokens`.
- **Tests**: `tests/test_npc_strategy.py` (scoreboard scope+delta+leader; postura/objetivo seteados;
  postura inválida ignorada; sin LLM mantiene postura; cadencia no recalcula) + e2e (el tick corre la
  capa sin romper). **226 verdes.**
- **Pendiente**: fase 2 reflexión post-batalla; tunear cadencia/posturas con datos reales.

## 10. Implementación (orden sugerido)
1. Modelo + migración (campos `npc_*`). 
2. `npc_scoreboard` (galaxia-scoped, con `delta`). 
3. `decide_strategy` (LLM estratégico inyectable + fallback) + persistencia + cadencia en `run_npc_turn`.
4. Inyectar postura en `_npc_state` + prompt táctico + reglas. 
5. Métricas (`npc:<name>` ya fluye; opcional counter). 
6. Tests servicio + e2e. 
7. (Fase 2) reflexión post-batalla.
