# SDD 86 — Las IAs ven y aprovechan los eventos del mundo

## Contexto
Los eventos dinámicos (SDD 36 "happy hour": `build_cost`, `energy_regen`, `production`, `attack`
[fervor bélico], `defense`, `solar_storm`, `free_units`) aplican multiplicadores mientras están
activos. Pero ni la NPC ni el autopiloto del jugador los MIRABAN al decidir → no los aprovechaban
(atacar cuando el ataque está potenciado, construir cuando sale barato, etc.). El usuario lo pidió.

## Cambios
- **NPC (`_npc_state` + prompt):** el estado incluye `active_events` (`[{effect, magnitude, name}]`).
  El prompt le dice EXPLÍCITAMENTE cómo aprovechar cada efecto: `attack`→atacar ya, `build_cost`/
  `solar_storm`→construir, `production`/`energy_regen`→expandir economía, `free_units`→entrenar.
- **Autopiloto AGENTE (`_agent_state` + prompt, SDD 83):** ídem — `active_events` en el estado +
  guía para explotarlos.
- **Autopiloto DETERMINISTA (`_auto_attack`):** en un evento `attack` (fervor bélico) baja el margen
  exigido (×0.75) → ataca más agresivo mientras dura la ventana. (El resto de los efectos ya se
  aplican solos a la economía/combate vía `event_multiplier`; esto es la explotación ACTIVA del
  timing de ataque.)

## Tests
- `test_npc_state_includes_active_events` (NPC ve un evento `attack`).
- `test_agent_state_includes_active_events` (el agente ve un evento `build_cost`).

## Follow-ups
- Explotación activa por evento también en más skills deterministas (construir más en `build_cost`,
  colonizar/expandir en `production`), no solo el ataque.
