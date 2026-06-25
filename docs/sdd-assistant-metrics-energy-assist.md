# SDD 40 — Métricas del asistente por jugador + asistencia de energía por ranking

> **Estado:** propuesto · **Fecha:** 2026-06-25
> **Relacionado:** [SDD 28 uso de IA por usuario](sdd-llm-usage-metrics.md),
> [SDD 38 journal](sdd-event-journal-replay.md), [SDD 25 catch-up](sdd-newcomer-catchup.md),
> `app/services/advisor.py`, `app/services/llm.py`, `app/services/stats.py` (leaderboard).

## 1. Objetivo
Dos cosas que pidió el usuario:
1. **Trackear el uso del asistente IA por jugador**: quién lo usó, cuánto, y con **qué modelo**
   (GPU local / nube; gratis / pago) — para datos ricos cruzables que la IA pueda analizar.
2. **Hack de energía inteligente por ranking**: hoy el hack solo da material/energía para construir
   algo puntual. Nuevo: pedir energía y que el server **calcule según tu posición** — los **3 últimos**
   reciben más (nivelan rápido); el resto recibe **+100 fijo, hasta 3 veces/día** → evita snowball
   ("run pike") y que sea ventaja persistente.

## 2. Métricas del asistente por jugador
- **Ya existe (SDD 28):** cada llamada del asistente va con `user="player:<username>"` → litellm
  expone `litellm_*{end_user, model}` en Prometheus/Grafana, y el router etiqueta el modelo servido
  (gpu local vs openrouter free/paid). O sea **quién** y **con qué modelo/costo** ya es medible.
- **Nuevo (game-side, este SDD):** registrar un evento **`advisor_ask`** en el **journal** (SDD 38)
  por cada consulta `{player, mode (llm|fallback)}` → `game_journal_events_total{kind="advisor_ask"}`
  + fila en `game_events` cruzable con todo lo demás. Así el dataset propio del juego también tiene
  el uso del asistente (no solo litellm), legible por una IA de análisis.
- (futuro) Propagar el **modelo** efectivo desde `llm_chat` al evento (hoy litellm ya lo tiene).

## 3. Asistencia de energía por ranking (nuevo "hack")
- **Posición:** ranking por score entre **pares humanos de tu instancia de galaxia** (como catch-up,
  SDD 25). `N` jugadores; sos "de los 3 últimos" si tu rank está en el tercio inferior absoluto
  (los 3 de menor score) y `N ≥ 4`.
- **Grant:**
  - **3 últimos:** energía hasta **llenar el pool** (`energy_max`), escalado por lo bajo que estás
    → nivelás rápido. Hasta `assist_energy_per_day` veces/día.
  - **Resto:** **+100** (`assist_energy_normal`), hasta 3 veces/día, **capeado a `energy_max`**.
- **Anti-snowball:** la energía es **transitoria** (regenera, no es ventaja persistente); todo
  capeado a `energy_max` y limitado a 3/día (contador diario con reset perezoso, como los hacks).
  Los punteros NO obtienen ventaja (solo +100 ocasional); los últimos se nivelan.
- **Determinista:** lo calcula el server (no el LLM). El asistente puede ofrecer el botón cuando
  detecta intención ("necesito energía"), pero el monto lo decide el server.

## 4. Modelo / API
- **Player:** `assist_energy_used:int` + `assist_energy_reset_at:datetime` (reset diario perezoso).
  Migración aditiva (`server_default`).
- **`POST /api/v1/players/me/assist/energy`** → `{granted, energy, bottom3, left}`; 429 si agotaste el
  cupo del día. Botón **⚡ Nivelar** en la web (panel de energía / asistente).

## 5. Tests
- `advisor.ask` deja un evento `advisor_ask` en el journal.
- Asistencia: un jugador en el fondo recibe más (llena el pool); uno del medio recibe 100; el 4º
  pedido del día → 429; nunca supera `energy_max`.

## 6. Riesgos
- **Definir "3 últimos"** con pocos jugadores: si `N<4`, todos reciben el grant normal (100).
- **Abuso:** cupo diario + cap de energía + transitoriedad evitan ventaja. Ajustable por config.
