# SDD 72 — Evento "Tormenta solar": 2 h sin fabricar, solo construir, energía infinita

> **Estado:** **IMPLEMENTADO** 2026-07-03 (1.139.0). Nuevo tipo de [evento del mundo (SDD 36)](sdd-dynamic-events.md).
> **Pedido:** usuario, 2026-07-02.
> **Relacionado:** [SDD 36 eventos dinámicos](sdd-dynamic-events.md) (motor, `content/events.yaml`,
> `app/services/events.py`), `app/services/training.py`, `app/services/build.py`.

## 1. Pedido (usuario, 2026-07-02)
"Agregá un evento que sea **tormenta solar**: por **dos horas** no podés crear más unidades porque tu
**electrónica se estropió** — no unidades, no drones, no misiles, nada; **solo podés construir bases**.
Pero en esas dos horas **tu energía es infinita**."

## 2. Diseño (temático + data-driven)
La tormenta solar es a la vez una **sobrecarga de energía** (→ energía infinita) y un **golpe a la
electrónica** (→ no se fabrica nada). Es un `WorldEvent` más (SDD 36), scope `all`, `duration_seconds:
7200` (2 h), `weight: 1` (raro; se rebalancea en YAML).
- **Efecto nuevo `solar_storm`** en `content/events.yaml`. `solar_storm_active(session)` en
  `events.py` = hay un evento activo con ese efecto.
- **No fabricar NADA:** `start_training` (el ÚNICO camino de fabricación — unidades, drones, misiles,
  satélites, todo pasa por ahí) corta con error si hay tormenta. Un solo gate cubre todo.
- **Energía infinita:** `start_build` pone `need_e = 0` mientras la tormenta está activa → construir
  no cuesta energía (aunque tengas 0). Los edificios siguen costando **minerales** (la electrónica no
  entra en la construcción; el material sí). Solo se puede **construir**.
- **Front:** el snapshot expone `solar_storm: bool`. El form de Entrenar muestra el aviso y no permite
  fabricar; el header/barra de energía muestran **☀️⚡ ∞**.

## 3. Por qué un gate en training + otro en build (y no un multiplicador)
Los eventos SDD 36 existentes son **multiplicadores** (producción/ataque/energía × magnitud). La
tormenta no es escalar: es un **switch de reglas** (bloquear fabricación + waivear energía de
construir). Por eso se resuelve con `solar_storm_active()` leído donde importa, no con `event_multiplier`.

## 4. Tests
- Servicio: `tests/test_events.py::test_solar_storm_blocks_all_manufacturing` (start_training falla).
- e2e: `test_solar_storm_blocks_training_allows_building_e2e` — fuerza el evento, `solar_storm=true` en
  el snapshot, entrenar da 400, y construir con **energía 0** devuelve 201 (energía infinita).

## 5. Notas / futuro
- Los NPC que intenten fabricar durante la tormenta caen a su fallback (try/except del brain) — no se
  rompe el tick.
- Posible v2: que la tormenta también dé un plus de producción minera (la "sobrecarga" alimenta minas)
  o un pequeño daño a satélites en órbita (temático). Fuera de alcance del pedido.
