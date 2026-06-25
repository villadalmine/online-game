# SDD 41 — Del journal a la inteligencia: capa de insights / meta (y futuro ML)

> **Estado:** propuesto · **Fecha:** 2026-06-25
> **Relacionado:** [SDD 38 journal](sdd-event-journal-replay.md) (la materia prima),
> [SDD 29 cerebro estratégico NPC](sdd-npc-strategic-intelligence.md),
> [SDD 2 asistente](sdd-ai-assistant.md), [SDD 28 uso IA](sdd-llm-usage-metrics.md),
> `app/services/{journal,combat,npc,advisor}.py`.

## 1. Objetivo
Convertir el **"guardo todo"** (journal `game_events`, SDD 38) en **inteligencia**: que la IA
(asistente + NPCs) **aprenda el meta** de las partidas reales y juegue/aconseje mejor — **sin entrenar
un modelo todavía**, pero **dejando todo preparado** para hacerlo eficientemente cuando haya muchas
partidas.

## 2. Tres niveles (elegimos el 2, listos para el 3)
1. **Grounding/RAG** (ya existe): meter datos reales en el prompt del LLM.
2. **Analítica determinista = "aprender patrones" por estadística (ESTE SDD).** Un proceso Python+SQL
   mina el journal y calcula el **meta** (win-rates, counters, openings); lo guarda como **insights**;
   el LLM (NPC + asistente) los **lee** → juega/aconseja con datos. NO es una red neuronal.
3. **Modelo ML entrenado** (futuro, con escala): predecir prob. de victoria / recomendar acción. Se
   habilita reusando lo mismo (ver §6).

## 3. Datos (fuente: journal, SDD 38)
- El journal ya tiene `attack_launched {force, defender_id}` y `battle_resolved {outcome,
  attacker_losses, defender_losses, loot}`. **Mejora (v1):** `battle_resolved` también guarda la
  **`force`** atacante → cada batalla es minable de una sola fila (composición → resultado).
- Otros eventos (build/train/spy/colonize) quedan disponibles para insights futuros (openings, etc.).

## 4. Capa de insights (v1)
- **Modelo `MetaInsight`** `(key PK-ish, payload JSON, sample_n, updated_at)` — **upsert** por `key`.
  Persistido (no se recalcula todo cada vez; barato de leer; queryable; base para dashboards y ML).
- **Servicio `insights.py`:**
  - `compute_meta(session)` (corre en el **tick**, gated por intervalo): agrega `battle_resolved` y
    calcula:
    - `attack_winrate`: % de ataques ganados + `n`.
    - `winrate_by_unit`: por **unidad dominante** de la flota, win-rate + `n` (qué composición gana).
  - `meta_summary_text(session)`: texto corto del meta para el prompt del LLM.
  - `get_insights(session)`: lectura (API/UI).
- **Consumo:** el **cerebro NPC** (SDD 29) y el **asistente** (SDD 2) reciben `meta_summary_text` en su
  contexto → las NPC juegan el meta y el asistente aconseja con datos ("las flotas con tank ganan 70%").
- **API:** `GET /api/v1/insights` (público/auth) — transparencia + panel web 📈 Meta + Grafana.

## 5. Determinismo / costo
- Todo determinista (SQL/agregación); el LLM solo narra/usa, no inventa. Recompute barato ahora;
  con escala se **ventana** (últimos N días) o se hace **incremental** por `seq` (cursor en MetaInsight).

## 6. Preparado para ML (nivel 3, futuro — sin hacerlo ahora)
- El **journal es el feature store**: append-only, ordenado, con `force`+`outcome` por batalla →
  exportable a `(features, label)` para entrenar (win-prob, recomendador). `MetaInsight` y el export
  YAML (SDD 38) son las vistas estables sobre las que se construye.
- **Camino futuro:** job `export_training_set()` (de `game_events`/`combat_logs`) → entrena offline
  (sklearn/torch) → publica un modelo que el cerebro NPC consulta como una estrategia más (pluggable,
  como hoy `RuleBasedBrain`/`LlmBrain`). Nada de esto bloquea v1; el esquema ya lo permite.
- **Privacidad:** insights son **agregados** (sin exponer estado exacto de un rival); el export de
  entrenamiento es interno/admin.

## 7. Tests
- `compute_meta` con batallas sembradas calcula win-rates correctos y upsertea `MetaInsight`.
- `battle_resolved` guarda `force`.
- `meta_summary_text` no rompe sin datos (meta vacío) y resume con datos.
- e2e: `GET /insights` devuelve las claves esperadas.

## 8. Riesgos
- **Muestras chicas:** mostrar `n`; el LLM debe matizar ("pocos datos"). Umbral mínimo configurable.
- **Sesgo/realimentación:** si las NPC juegan el meta, el meta se refuerza; mitigar con exploración
  (las NPC a veces se salen del meta) — follow-up.
- **Escala:** pasar a incremental por cursor cuando `game_events` crezca (diseñado en §5).
