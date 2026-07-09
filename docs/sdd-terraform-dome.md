# SDD 89 — Domo de terraformación (sink de raros + colonizar lo imposible)

Idea del usuario: dar uso a los materiales más raros. Decisiones confirmadas: **catalizadores
exóticos únicos por luna · más lunas en más planetas · modo de colonización `dome`**.

## Mecánica
- **Cada luna, un catalizador ÚNICO** (`content/minerals.yaml`, `catalyst: true`; `content/gods.yaml`
  `catalyst:` + en `grants`): `selenite` (Luna), `phobite` (Fobos), `deimite` (Deimos), `zoozvine`
  (Zoozve), y las lunas nuevas de las otras galaxias (`lyrium`, `nyxite`, `proximite`, `trappist_ore`,
  `novite`). Solo se consiguen por **expedición** → te obliga a visitar TODAS las lunas de tu galaxia.
- **Lunas nuevas** en los planetas que no tenían (Vega Prime, Nyx, Proxima b, TRAPPIST-1e, Nova Terra),
  así cada galaxia tiene su set.
- **Domo de terraformación** (`colonization.found_colony(mode="dome")`): con la tech `terraforming` +
  **1 de cada catalizador de tu galaxia** (`galaxy_catalysts`), fundás un HQ-Domo en un planeta LETAL
  (Mercurio, exoplanetas hostiles) — **ignora la habitabilidad** (ese es el punto) y consume el set.
  El domo es una base completa (`base_type="dome"`): desde ahí construís TODO (revive el contenido
  muerto de los mundos imposibles).

## Piezas
- `content/minerals.yaml` (9 catalizadores), `content/gods.yaml` (catalyst por luna + 5 lunas nuevas).
- `app/services/colonization.py`: `galaxy_catalysts()` + `mode="dome"` (tech + set + bypass
  habitabilidad + consumo). `app/api/v1/colonize.py`: expone `dome` por planeta (listo si tenés
  tech + set). `web/index.html`: botón 🏛 Domo en el modal de colonización.
- Flag `TERRAFORM_DOME_ENABLED` (prod ON), config `dome_catalyst_cost` (1 de cada uno).

## Tests
- `tests/test_terraform_dome.py`: el set de la galaxia, Mercurio letal sin domo, el domo funda en un
  mundo letal y CONSUME el set, y falla sin el set completo o sin la tech.

## Follow-ups
- Que la habitabilidad de verdad penalice el rinde (hoy es solo gating) → el domo tendría un rinde
  propio. Cross-galaxy: expediciones a otras galaxias (hyperspace) para un set universal.
- Que el autopiloto/NPC busquen el domo como objetivo de endgame.
