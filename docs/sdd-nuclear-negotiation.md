# SDD 80 — Negociación nuclear más rica (lado del atacante)

## Idea (del usuario)
Cuando le lanzo un nuclear a alguien y me tiene que pagar tributo: quiero **elegir a qué planeta mío
me lo mandan**; y si **no pueden pagar** (no tienen diplomacia todavía), **darle tiempo** posponiendo el
misil para que la desarrollen. El NPC tiene que saber hacerlo, y quiero **métricas** de que la IA piensa
y decide.

## A — Elegir el planeta destino del tributo
`accept_tribute(session, attacker, mission_id, target_planet=None)`: el atacante puede indicar a qué
planeta PROPIO (donde tenga una base) le acreditan los minerales del tributo; default = natal. Front:
`acceptTribute` pregunta el planeta si tenés más de uno.

## B — Dar tiempo (pausar el nuclear)
`grant_time(session, attacker, mission_id)`: el atacante posterga `arrives_at` del nuclear
`nuclear_grant_time_hours` (12h), acotado a `nuclear_time_grants_max` (3) veces por misil (contador en
`mission.details.time_grants`). Notifica al defensor ("desarrollá diplomacia y ofrecé tributo").
`POST /combat/strike/{id}/grant-time` + botón **⏳ dar tiempo** en la salva nuclear propia.

## C — El NPC ya sabe hacerlo (SDD 67 v5)
`npc_seek_diplomacy` (tick): el NPC bajo un nuclear que no tiene diplomacia CONSTRUYE government →
INVESTIGA diplomacy (legítimo, con costo/tiempo) y recién ahí ofrece tributo (`npc_offer_tributes`).

## D — Métricas (ver que la IA piensa/decide)
`game_diplomacy_actions_total{action, actor}`: `seek_diplomacy`/npc (el NPC desarrolla diplomacia),
`tribute_offered`/npc, `tribute_accepted`/human, `recall`/human, **`grant_time`/human**. En Grafana ves
la negociación completa: el NPC aprendiendo diplomacia bajo amenaza y los tributos/prórrogas.

## Tests
`tests/test_strike.py::test_grant_time_extends_nuclear_and_caps` (+12h por vez, tope a las N veces).
`accept_tribute` con planeta reusa el test nuclear existente.

## Follow-ups
- Que el atacante DEMANDE un tributo específico (hoy el defensor lo ofrece; el atacante acepta/da tiempo).
- Mostrar el contador de prórrogas y la métrica de diplomacia también in-app.
