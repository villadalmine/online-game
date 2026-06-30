# SDD 60 — Paneles por planeta colapsables (materiales, bases, capacidad)

> **Estado:** **IMPLEMENTADO** 2026-06-30 (front; web smoke verde) · **Diseño:** 2026-06-30
> **Relacionado:** [SDD 42 stock por planeta](sdd-per-planet-stocks.md),
> [SDD 59 panel de materiales por planeta](sdd-materials-panel-per-planet.md),
> [SDD 46 alojamiento](sdd-unit-housing-capacity.md), [SDD 47 minería/silos](sdd-mining-workers-storage.md),
> `web/index.html` (todo es front; los datos por planeta ya están en `/players/me`).

## 1. Problema (usuario, 2026-06-30)
Con varias colonias, los paneles se vuelven enormes:
- "El panel de **Economía/capacidad** no está separado por planeta que tenés conquistado."
- "**Tu imperio** no está separado por planeta."
- "En los paneles de **materiales, unidades o que tengan info de planetas**, que se puedan **colapsar
  dentro del panel** así ves solo el planeta que querés y no te queda un planeta enorme — como es ahora
  el de **Bases y edificios**."

O sea: (a) agrupar por planeta donde tenga sentido y (b) que cada grupo de planeta sea **colapsable**.

## 2. Estado de los datos (qué es por-planeta y qué no)
- **Materiales**: POR PLANETA ya (SDD 42/59, `stocks_by_planet`).
- **Bases y edificios**: POR BASE (cada base tiene `planet_key`) → agrupable por planeta.
- **Almacén/silos** (`storage`): POR PLANETA ya (SDD 47).
- **Minería** (`mining`) y **alojamiento** (`housing`): hoy son **agregados del imperio** (no por
  planeta) en el snapshot. → en esta v1 se muestran como sección "imperio" (no se inventa granularidad
  que el backend no da); v2 puede exponerlos por planeta.
- **Unidades** (`units`): son **globales del jugador** (modelo `UnitStock` por `player_id`, sin
  planeta) → NO se separan por planeta (sería falso). Se deja la nota y se hace el panel colapsable.

## 3. Diseño (todo front, `web/index.html`)
### 3.1 Colapsable reutilizable que sobrevive el refresh de 4 s
`renderState` regenera el `innerHTML` cada 4 s → un `<details>` nativo perdería su estado abierto/
cerrado. Solución: un Set `_collapsed` de claves de sección cerradas (default = abierto, nada se
oculta sin que el usuario lo pida); helper `_collapse(key, titleHtml, bodyHtml)` que emite
`<details open?>` según el Set y un `ontoggle` que actualiza el Set. Persistir en `localStorage` para
que el colapso aguante recargas.

### 3.2 Aplicación
- **Bases y edificios**: agrupar `state.bases` por `planet_key`; cada planeta = un `<details>` con
  summary "⭐/🪐 Planeta · N edificios" + el detalle de edificios adentro.
- **Materiales** (con >1 planeta): cada planeta = un `<details>` (summary con los totales/chips).
- **Capacidad**: el bloque de almacén por planeta, cada planeta colapsable; minería/alojamiento en una
  sección "imperio".

## 4. Tests / validación
- Web smoke (`tests/test_web_smoke.py`): no hay errores de JS al renderizar; los `<details>` existen y
  el panel de bases sigue mostrando los edificios. Colapsar/expandir no rompe el ciclo de 4 s.
- Sin cambios de API → no hay e2e nuevo de backend; el guard es el smoke de front.

## 5. Rollout / riesgos
- 100% front, aditivo. Riesgo: el estado de colapso parpadea si no se persiste bien → por eso el Set +
  `localStorage` y default abierto. Va por el pipeline de Argo.
