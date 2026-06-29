# SDD 56 — Capacidad visible al entrenar: headroom de tropas (no encolar miles sin plazas)

> **Estado:** **IMPLEMENTADO** 2026-06-29 — backend de plazas ya existía (SDD 46); se sumó el headroom
> en el form de entrenar (web) + e2e. · **Diseño:** 2026-06-29
> **Relacionado:** [SDD 46 alojamiento de unidades](sdd-unit-housing-capacity.md) (ya implementado:
> `app/services/housing.py` `housing_report` = {dominio: {capacity, occupancy, free}}; panel web
> "📦 Economía / capacidad" `renderCapacity()`), [SDD 47 minería/silos](sdd-mining-workers-storage.md),
> `app/services/build.py`/`train` (encolado), `web/index.html` (`renderTrainCost`, train UI).

## 1. Problema (usuario, 2026-06-29)
"Tiene que haber un panel para saber cuánto espacio me queda para tropas/tanques/etc, para evitar
poner miles de unidades sin nada." Hoy:
- **Ya existe** el cálculo y el panel: `housing_report` expone `free` por dominio
  (personnel/infantry/ground/air/space/naval/ordnance/drone) y el panel "📦 Economía / capacidad"
  dibuja barras. Con `housing_enforced=ON` el server rechaza entrenar de más.
- **Pero falta el feedback en el MOMENTO de entrenar**: el jugador no ve, junto al botón "Entrenar",
  cuántas plazas libres le quedan para ESE dominio → encola cantidades imposibles y recién falla (o
  no entiende por qué). El panel está "lejos" del formulario de entrenamiento.

## 2. Diseño propuesto
### 2.1 Headroom en el formulario de entrenar
- Al elegir una unidad en la UI de entrenamiento, mostrar al lado: **"plazas libres: X / Y (dominio
  ✈ Aéreas)"** usando el `free` que ya viene en `/players/me` (`state.housing[dominio]`). Local, sin
  red extra (entra en el ciclo de 4s como `renderCapacity`).
- **Tope automático del input de cantidad**: `max = free` (no podés tipear más de lo que entra). Si
  `free == 0`, deshabilitar el botón con tooltip "sin plazas — construí un {edificio que aloja ese
  dominio}" (ej. hangar para aéreas/espaciales, cuartel para infantería, puerto para naval, fábrica
  para terrestres, lanzadera para misiles, fábrica de drones para drones).
- Considerar las unidades **en cola** (queued) en el cálculo de `free` (ya lo hace `housing_occupancy`
  con `queued=`), para no encolar dos tandas que juntas se pasan.

### 2.2 Pre-validación clara (defensa en profundidad)
- Mensaje de error del server (cuando igual se intenta pasar) ya existe por `housing_enforced`;
  unificarlo con el toast centralizado (`msg()`) y que diga exactamente "te faltan N plazas de
  {dominio}; construí {edificio}". (Ver memoria UI toasts + pre-calc.)
- El **asistente** (SDD 2) puede sugerir "construí un hangar (+8 aéreas)" cuando detecta que querés
  más unidades de las que entran.

### 2.3 (opcional) Capacidad por planeta/base
- Hoy el alojamiento es agregado del jugador (SDD 46 v1). A futuro (SDD 46 v2): plazas POR planeta →
  el panel mostraría headroom por base. Fuera de alcance de este SDD; solo dejarlo anotado.

## 3. Tests / validación
- e2e (`test_api_e2e.py`): con 0 plazas libres de un dominio, `train` de ese dominio devuelve 4xx con
  mensaje de plazas; tras construir el edificio que aloja, `train` pasa.
- Front: `renderTrainCost`/nuevo `renderTrainHeadroom` topea el input a `free` y deshabilita en 0.

## 4. Rollout / riesgos
- Mayormente front + textos; el backend ya calcula `free`. Aditivo. Va por el pipeline de Argo.
- Riesgo bajo: solo cambia UX y mensajes; no toca balance ni el modelo.

## 5. Implementación (2026-06-29)
- Backend: ya estaba (`housing_enforced=True`, error claro con plazas libres + edificios; `/players/me`
  expone `housing[dominio].free`).
- Front (`web/index.html`, `renderTrainCost`): muestra **🏠 plazas libres: X {dominio}** junto al costo,
  **topea el input de cantidad** a lo que entra (`max=floor(free/housing_size)`, clamp) y avisa en rojo
  **"sin plazas — construí …"** cuando no hay lugar. i18n `free_slots`/`no_slots` (es/en).
- e2e `test_training_capacity_headroom_e2e`: `/players/me` trae `housing.infantry.free` y entrenar más
  soldados que plazas (con material/energía de sobra) → 4xx con "plaza".
