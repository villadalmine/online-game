# SDD 66 — Estado de edificios: averiada/sana, reparar, demoler y mejoras (defensa/antimisil)

> **Estado:** **DISEÑO** 2026-07-02 (sin implementar) · **Pedido:** usuario, 2026-07-02.
> **Relacionado:** [SDD 49 misiles](sdd-missile-launcher.md) (hoy una salva **borra** el edificio),
> [SDD 57 bombardeo](sdd-hyperspace-base-buster.md) (ídem), [SDD 60 paneles](sdd-collapsible-planet-panels.md)
> (la vista agrupada "torreta ×5" ya muestra ✓activas/🏗en obra — acá se suma sanas/averiadas),
> `app/models/__init__.py` (`Building.status`), `app/services/{strike,combat,build}.py`.

## 1. Pedido (usuario, 2026-07-02)
Todas las bases tienen que tener por edificio las acciones **reparar / destruir / mejorar (update)**:
- **Averiada/sana**: los ataques dejan edificios **averiados** (no siempre borrados); la vista agrupada
  ("research_lab ×5") debe mostrar **cuántas están averiadas y cuántas sanas**.
- **Reparar**: volver una averiada a sana (cuesta materiales/tiempo).
- **Destruir**: demolición propia (libera la celda; recupera parte del material).
- **Update (mejoras)**: por edificio — **defensa** (resiste más daño) o **ataque antimisil** (mejor
  intercepción para repeler misiles).

## 2. Diseño propuesto
### 2.1 Condición (averiada/sana)
- `Building.condition: float` (0–100, default 100) + estado visual `averiada` si `< 50`.
- **Los ataques dañan antes de destruir**: una salva de misiles (SDD 49) o el bombardeo (SDD 57)
  reparten su daño bajando `condition`; el edificio se **borra solo si llega a 0** (hoy se borra
  entero de una — pasar a daño gradual hace la guerra menos binaria). Un edificio averiado **rinde a
  fracción** (producción/defensa × condition/100) — mismo patrón que el staffing de minas (SDD 47).
### 2.2 Acciones por edificio (API + UI)
- `POST /bases/{id}/buildings/{bid}/repair` — cuesta % del costo original según el daño; tarda
  `repair_seconds` (lazy). `.../demolish` — propia, instantánea, devuelve `salvage_fraction` (~30%)
  del costo al planeta. `.../upgrade {kind: defense|antimissile}` — sube `level` con efecto:
  `defense`: +HP/`defense_power` por nivel; `antimissile`: +`intercept_power` por nivel (torretas y
  edificios con defensa). Costos crecen por nivel (data-driven: `upgrade` en `buildings.yaml`).
- UI: en la vista agrupada del panel de bases ("torreta ×5 ✓4 🏗1"), sumar `💚N 🩹M` (sanas/averiadas);
  al expandir, cada edificio muestra su condición y los botones 🩹 reparar / 🗑 demoler / ⬆ mejorar.
### 2.3 Datos
- Migración: `Building.condition` (float, default 100, server_default) — `level` ya existe.
- `buildings.yaml`: `upgrade: {defense: {hp: +X, cost_mult: 1.5}, antimissile: {...}}` por edificio
  (data-driven; solo los que tengan la clave ofrecen esa mejora).

## 3. Tests
- Daño gradual: una salva baja `condition` y solo destruye al llegar a 0; averiada rinde a fracción.
- Reparar restaura y cobra proporcional; demoler devuelve el salvage; upgrade sube el efecto y el
  costo crece por nivel. e2e del flujo completo + errores (reparar sana, demoler HQ prohibido).

## 4. Rollout / riesgos
- Flag `building_condition_enabled` (OFF hasta balancear: cambia cuánto "dura" una base bajo misiles).
- Aditivo; por el pipeline. La UI agrupada (SDD 60) ya quedó preparada para mostrar el desglose.
