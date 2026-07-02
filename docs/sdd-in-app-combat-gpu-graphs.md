# SDD 71 — Gráficos in-app: cómo van mis ataques/defensas + mi uso de IA (GPU)

> **Estado:** **IMPLEMENTADO** 2026-07-02 (1.138.0). Extiende [SDD 51 "Tu historia"](sdd-player-analytics.md):
> el modal 📈 (`openHistory`) suma dos bloques nuevos, todo per-jugador y determinista (sin LLM).
> **Pedido:** usuario, 2026-07-02: "métricas uso de gpu y métricas de cómo van mis ataques y defensas,
> armá algún gráfico en la parte de tu imperio → tu historia".
> **Relacionado:** [SDD 51 analítica](sdd-player-analytics.md), [SDD 65 observabilidad GPU](sdd-npc-autonomous-intelligence.md)
> (Grafana, agregado), [SDD 38 journal](sdd-event-journal.md), `app/services/analytics.py`,
> `web/index.html` (`openHistory`).

## 1. Qué agrega
- **⚔ Ataques y defensas (24 h)** — de `CombatLog` (per-jugador): ganados/perdidos como atacante y como
  defensor, **efectividad** (win-rate), 💰 botín ganado/perdido, y un sparkline de **batallas/hora**.
  `combat_summary(player_id, hours)` en analytics; se filtra `outcome in (attacker,defender,draw)`
  (las salvas de misiles `outcome=strike` no cuentan como batalla de flota).
- **🖥️ Tu uso de IA (asistente)** — de `GameEvent type=advisor_ask` con `payload.mode`: total +
  desglose por ruta **gpu/cloud/byok/hack** + sparkline por hora. `llm_usage(player_id, hours)`.
  Es la señal **per-jugador** de uso de GPU (no sufre el problema de 3 réplicas del `/metrics` del
  proceso — sale de la DB del journal). Se registra el `mode` en el `advisor_ask` (advisor.py).

## 2. Por qué acá y no solo en Grafana
Grafana (SDD 65) da el **agregado del server** (todos los jugadores + NPCs, sumando las 3 réplicas de
la API). "Tu historia" da lo **tuyo**, dentro del juego, sin salir a Grafana. Complementarios.

## 3. Data / endpoints
- `GET /players/me/history?hours=` ahora devuelve además `combat` y `llm` (además de `samples`/`events`).
- Sin migración: reusa `CombatLog` y `GameEvent`. El único cambio de datos es empezar a guardar `mode`
  en el payload de `advisor_ask` (aditivo).

## 4. Tests
- Servicio: `tests/test_analytics.py` (win/loss/loot de `combat_summary`; desglose por modo de `llm_usage`).
- e2e: `test_player_history_analytics_e2e` verifica que `combat` y `llm` vienen con su forma.
