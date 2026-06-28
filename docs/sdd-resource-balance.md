# SDD 53 — Balance de costos: defensa no gateada por 1 mineral + asimetría por raza

> **Estado:** **diseño** (no implementado) · **Fecha:** 2026-06-28
> **Relacionado:** SDD (data-driven `content/*.yaml`), plan de game-design (roles de recurso por raza),
> SDD 49/50 (balance de combate), `content/{buildings,units,races}.yaml`, `registry.resolve_cost`,
> `tests/test_balance.py`.

## 1. Problema (analizado 2026-06-28)
Los costos se expresan en **roles** (`structural`/`energetic`/`advanced`) que cada raza resuelve a un
mineral. Hallazgos:
- **Casi TODO usa el rol `energetic`** (22/22 items), **incluida la defensa básica**:
  `turret` = 140 structural + **60 energetic**; `soldier` = 15 structural + **10 energetic**.
- Mapeo por raza (rol→mineral):
  - terran: structural=**iron**, energetic=**silicon**, advanced=**aluminum**
  - martian: structural=**iron**, energetic=**sulfur**, advanced=**magnesium**
  - venusian: structural=**basalt**, energetic=**sulfur**, advanced=**titanium**
- ⇒ Para terran, **sin silicio no podés hacer torreta NI soldados = te quedás sin defender**. Un solo
  mineral gatea toda la defensa. (Mismo riesgo para cualquier raza con su `energetic`.)

## 2. Metas (las dos que pidió el usuario)
1. **La defensa NO debe depender de un solo mineral**: siempre poder defenderte con tu mineral
   estructural, aunque te quedes sin el energético.
2. **Mantener/reforzar la asimetría por raza**: que cada raza "dependa" de un mineral distinto (es la
   gracia estratégica) — terran↔silicio, martian/venusian↔azufre, advanced distinto (aluminio/
   magnesio/titanio), structural iron vs basalt. Anclado a la abundancia real del planeta (rigor SDD 13).

## 3. Diseño
### 3.1 Defensa e infantería = solo rol `structural`
- `turret`: 140 struct + 60 energetic → **180 struct, 0 energetic** (defensa con tu mineral base).
- `soldier`: 15 struct + 10 energetic → **22 struct, 0 energetic** (infantería barata sin el energético).
- Garantía: con SOLO el mineral estructural (iron/basalt) podés levantar defensa + infantería → nunca
  te quedás indefenso por faltar un mineral.

### 3.2 Diversificar el rol por RAMA (que cada mineral pese en algo distinto)
Para que ningún mineral gatee todo y cada uno tenga propósito:
- **ground (tank)**: structural + advanced (sin energetic) → blindaje pesado de tierra.
- **air (aircraft)**: energetic + advanced → necesita el energético (silicio/azufre) + el avanzado.
- **naval (ship)**: structural + energetic.
- **space (shuttle/cargo)**: energetic + advanced (alto).
- **ciencia/energía (research_lab, power_plant)**: energetic alto (ahí SÍ es el cuello del energético,
  pero es opcional/de progreso, no la defensa).
- **economía (mine, silo, port)**: structural-dominante.
Así: te falta energético → igual defendés (struct) y hacés tanques (struct+advanced); te falta
advanced → hacés torretas/soldados/minas; etc. Ningún faltante te deja sin jugar.

### 3.3 Asimetría por raza (mantener + afinar)
- Mantener el mapeo distinto (la "personalidad" de cada raza por su `energetic`/`advanced`).
- Afinar bonuses de raza (`races.yaml`) acordes: terran (silicio→ciencia/economía), martian
  (azufre→militar), venusian (azufre+titanio→energía/defensa atmosférica) — coherente con el diseño.
- Anclar a abundancia del planeta: cada raza tiene su mineral barato en casa (no se rompe la realidad).

## 4. Tests / validación (`tests/test_balance.py`)
- **Invariante anti-lockout**: para cada raza, `turret` y `soldier` se pueden pagar con SOLO el mineral
  estructural (cost resuelto tiene 0 en el resto) → nunca indefenso por un mineral.
- Ningún item depende de los 3 roles a la vez en defensa básica.
- Cada raza tiene un `energetic`/`advanced` (perfil) distinto.
- e2e: con stock de un solo mineral (el estructural), construir torreta + soldado OK; sin energético,
  aircraft/research SÍ bloquean (esperado).

## 5. Rollout / riesgos
- 100% YAML (data-driven) + tests; aditivo, no toca código. Va por el pipeline de Argo.
- Riesgo: rebalancear puede abaratar/encarecer ramas → ajustar números con el reporte `make balance`
  (extender `scripts/balance.py` a un breakdown por mineral/raza).
- No rompe partidas en curso (los costos nuevos aplican a construcciones nuevas).
