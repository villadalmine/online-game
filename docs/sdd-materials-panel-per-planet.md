# SDD 59 — Panel de materiales por planeta (el agregado confunde: "no tengo silicon" pero el panel dice que sí)

> **Estado:** **IMPLEMENTADO (v1)** 2026-06-29 — panel desglosa por planeta cuando hay colonias.
> · **Diseño:** 2026-06-29
> **Relacionado:** [SDD 42 mercado/multi-planeta](sdd-market-trade.md) (stock POR planeta),
> `app/services/state.py` (`stocks` agregado + `stocks_by_planet`), `web/index.html` (panel "Minerales"
> `#minerals` línea ~1131; afford por-planeta líneas ~598/647), fix previo 1.96.1 ("afford por planeta").

## 1. Problema (usuario, 2026-06-29)
"Me dice que no tengo silicon, pero el panel de materiales no se actualiza / dice que sí tengo." Causa
confirmada: el panel **"Minerales"** del front muestra `state.stocks`, que es el **AGREGADO de TODOS
los planetas**; en cambio construir/entrenar (SDD 42) valida contra el stock **del planeta de la base
seleccionada** (`state.stocks_by_planet[planet]`). Si tenés silicon en el natal pero construís en una
**colonia** sin silicon → el panel dice "tenés" y el build dice "no tenés" (no es que no se actualice:
muestra OTRO total). El backend ya expone ambos (`stocks` y `stocks_by_planet`); el bug es de UI.

## 2. Diseño propuesto
- **Panel de materiales sensible al planeta**: mostrar el stock del **planeta de la base seleccionada**
  (el mismo que usa la afford), no el agregado. Cuando hay varias colonias, mostrar **breakdown por
  planeta** (un bloque por planeta con stock), reusando `stocks_by_planet`.
- **Encabezado claro**: "📍 {planeta}" arriba del set de minerales así se entiende que es por colonia.
- Mantener el agregado solo como total opcional (o quitarlo para no confundir).
- El mensaje de error de build/train ya dice el faltante; alinear textos ("te falta silicon EN
  {planeta}").

## 3. Tests / validación
- e2e: un jugador con silicon SOLO en el natal y una colonia sin silicon → `/players/me` trae
  `stocks_by_planet` con 0 en la colonia; build en la colonia da 4xx por material (ya pasa). El test
  fija el contrato que la UI consume.
- Front: el panel muestra el stock del planeta de `#buildbase` (no el agregado).

## 4. Rollout / riesgos
- Solo front (el backend ya da `stocks_by_planet`). Aditivo. Va por el pipeline de Argo.
- Riesgo bajo: cambia presentación; cuidar el modo pictográfico y i18n.

## 5. Implementación (2026-06-29, v1)
- Confirmado: `market.buy` acredita el mineral al **planeta donde comprás** (con mercado activo ahí);
  construir/entrenar valida el planeta de la base → comprar en A y construir en B daba "falta".
- Front (`web/index.html`, panel "Minerales"): si el jugador tiene **>1 planeta** con stock, desglosa
  **por planeta** (⭐ natal / 🪐 colonia + `planetName`), reusando `state.stocks_by_planet` (lo mismo
  que usa la afford). Con un solo planeta, sigue el agregado. Respeta picto/i18n.
- e2e `test_stocks_exposed_per_planet_e2e`: `/players/me` expone `stocks_by_planet` por planeta.
- Pendiente v2: header 📍 también en el panel de acciones + alinear el texto de error ("falta X en
  {planeta}").
