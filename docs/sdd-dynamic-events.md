# SDD 36 — Eventos dinámicos del mundo ("happy hour": modificadores temporales)

> **Estado:** **implementado** (en producción) · **Fecha:** 2026-06-24
> **Relacionado:** [SDD 27 anuncios](sdd-announcements.md), [SDD 13 precisión física](sdd-scientific-accuracy.md),
> `app/services/effects.py` (`multiplier`), `app/services/boons.py` (`ActiveBoon` = multiplicador
> temporal **ya existente**), `app/services/state.py` (`advance`), `app/worker.py` (tick),
> `content/*.yaml`, `app/api/v1/world.py` (feed de eventos público).

## 0. Cómo usar este SDD
Los tipos de evento viven como **datos tipados** (`content/events.yaml`), no en código. Agregar/
rebalancear un evento = editar YAML. Bilingüe (ES default + `*_en`). El **estado** de un evento activo
vive en la **DB** (se lee dinámicamente, como pide el usuario), no hardcodeado en el front.

## 1. Objetivo
Hacer el juego **más ágil y vivo** con **eventos globales temporales** que se activan en **horas
aleatorias** y cambian las reglas un rato: *"happy hour"* donde **todo sale más barato**, la **energía
se carga más rápido**, **soldados gratis**, +producción, etc. Se muestran en un **panel de anuncios
dinámico** (se lee de la DB) con cuenta regresiva, y aplican a **todos** (o a un subconjunto) mientras
duran. Crea urgencia y momentos de pico de actividad sin romper el balance de largo plazo.

## 2. Idea clave: reusar el motor de multiplicadores que ya existe
El juego **ya** tiene multiplicadores temporales: `ActiveBoon` (boons de dioses) + `effects.multiplier`
combina boons × tech × alianza para `production|attack|defense|espionage|counter_espionage`. Un evento
global es, conceptualmente, **un boon que aplica a muchos jugadores a la vez** + algunos efectos nuevos
(costo, regen de energía, regalo de unidades). → Extender, no reinventar.

## 3. Tipos de efecto (data-driven, `content/events.yaml`)
| `effect` | qué hace | dónde engancha |
|---|---|---|
| `production` | ×prod de minas | ya soportado por `effects.multiplier` |
| `attack` / `defense` | ×combate | ya soportado |
| `energy_regen` | ⚡ se carga más rápido (×regen) | `physics.effective_energy_regen` lee un mult de evento |
| `build_cost` / `train_cost` | todo más **barato** (×<1 a costos) | `build`/`training` aplican el mult al resolver costo |
| `free_units` | **soldados gratis** (grant one-shot al entrar al evento) | acreditado lazy en `advance` (una vez por jugador/evento) |
| `research_speed` / `build_speed` | colas más rápidas (×<1 a tiempos) | al encolar / al calcular `completes_at` |

Campos de un evento (YAML): `key`, `name`/`name_en`, `description`/`*_en`, `icon`, `effect`,
`magnitude`, `duration_seconds`, `weight` (prob. relativa de salir), `scope` (`all` | `galaxy` |
`planet:<k>` | `race:<k>`), `cooldown_seconds` (no repetir muy seguido). Ej.:
```yaml
events:
  - key: happy_hour_cheap
    name: "Hora feliz: rebajas"
    name_en: "Happy hour: discounts"
    icon: "🏷"
    effect: build_cost
    magnitude: 0.5          # todo a mitad de precio
    duration_seconds: 1800
    weight: 3
    scope: all
  - key: power_surge
    name: "Sobrecarga energética"
    effect: energy_regen
    magnitude: 2.0          # energía al doble
    duration_seconds: 1200
    weight: 2
  - key: conscription
    name: "Leva: soldados gratis"
    effect: free_units
    magnitude: 5            # 5 soldiers al entrar
    grant_unit: soldier
    duration_seconds: 600
    weight: 1
```

## 4. Modelo + scheduling (DB, sin cron por usuario)
- **Modelo `WorldEvent`** `(id, key, effect, magnitude, scope, starts_at, ends_at, payload)`. Un evento
  **activo** = fila con `starts_at ≤ now < ends_at`.
- **Disparo en horas aleatorias:** el **tick** (`worker.run_tick`, ya corre periódico) decide si arranca
  un evento nuevo: con cierta probabilidad por tick (o "no hay ninguno activo y pasó el cooldown"),
  elige uno por `weight` y crea el `WorldEvent` con `ends_at = now + duration`. Determinista/testeable
  pasando `now` + un `random.Random(seed)`.
- **Lectura lazy:** `state.advance` y `effects.multiplier` consultan los `WorldEvent` activos del scope
  del jugador y los **apilan** como un multiplicador más (igual que boons). `free_units` se acredita
  una sola vez por (jugador, evento) — marca en una tabla `EventGrant(player_id, event_id)`.
- **Notificación + feed:** al crear el evento, push a `world/events` (panel público) y notificación a
  jugadores activos. El panel de anuncios lee `GET /world/events` + `GET /events/active`.

## 5. API (diseño)
- `GET /api/v1/events/active` → eventos vigentes (con `ends_at` para la cuenta regresiva). Público.
- `GET /api/v1/events/catalog?lang=` → tipos posibles (para "qué puede pasar"). Público.
- (admin/test) `POST /api/v1/admin/events` `{key}` → fuerza un evento ya (para QA y demos).
- El panel web "📣 Eventos" muestra los activos con ⏱ y un texto claro ("⚡×2 por 18 min").

## 6. Integración con el resto
- **`effects.multiplier`**: sumar un factor `event_multiplier(scope, effect, now)` al producto (boons ×
  tech × alianza × **evento**). Economía/combate/espionaje lo heredan gratis.
- **Costos/tiempos**: `build`/`train`/`research` consultan el mult de evento para `build_cost`/
  `*_speed` al resolver (un solo punto por servicio).
- **Anuncios (SDD 27)**: los eventos vivos son una **categoría dinámica** del panel de anuncios
  (los de SDD 27 son estáticos/curados; estos salen de la DB).
- **IA/asistente**: puede mencionar el evento vigente ("aprovechá: construir está a mitad de precio
  por 12 min") — grounded en `events/active`, sin inventar.

## 7. Tests / validación
- **Scheduling determinista:** con `Random(seed)` + `now`, el tick crea el evento esperado y respeta
  cooldown/weight; no crea dos del mismo scope a la vez si así se define.
- **Apilado:** un evento `production×2` activo duplica la producción vía `effects.multiplier`; al
  expirar (`now > ends_at`) vuelve a ×1.
- **Costo/regalo:** `build_cost×0.5` cobra la mitad; `free_units` acredita una sola vez por jugador
  (no se puede re-cobrar tocando `advance` muchas veces).
- **e2e:** `POST /admin/events {happy_hour_cheap}` → `GET /events/active` lo muestra → construir cuesta
  la mitad → tras `ends_at` (fast-forward) ya no aplica.

## 7.bis Estado de implementación (2026-06-24) — v1
- **Contenido:** `content/events.yaml` (happy_hour_build, power_surge, mining_boom, war_fervor,
  fortify, conscription) + `registry.events`.
- **Modelos + migración:** `WorldEvent` (activo si starts≤now<ends) + `EventGrant` (one-shot por
  jugador).
- **Servicio `events.py`:** `active_events`, `event_multiplier` (production/attack/defense/
  energy_regen), `build_cost_multiplier`, `grant_due_free_units`, `maybe_start_event` (RNG sembrable,
  un evento global a la vez + cooldown), `start_event`.
- **Enganches:** `effects.multiplier` (prod/atk/def apilan el evento), `state.advance` (energía
  ×evento + free_units), `build.py` (build_cost), `worker.run_tick` (scheduling). Config
  `event_chance_per_tick`/`event_cooldown_seconds`.
- **API:** `GET /events/active`, `GET /events/catalog`, `POST /events/start/{key}` (admin).
- **Web:** panel **📣 Eventos** con cuenta regresiva (polleado). Journal registra
  `world_event_started`.
- **Tests:** multiplicador activo/expira, build_cost, free_units una vez, scheduling determinista +
  e2e. **254 verdes.**
- **Pendiente (follow-up):** scope por galaxia/planeta/raza; efectos de velocidad de colas; aviso
  push al iniciar; panel Grafana de eventos.

## 8. Riesgos / decisiones
- **Balance/abuso:** eventos cortos + cooldown; `free_units` cap por evento; multiplicadores acotados.
  Evitar que dos eventos se multipliquen sin techo (cap global opcional).
- **Equidad:** un jugador offline durante la "hora feliz" se la pierde — es parte del diseño (crea
  hábito), pero `free_units` se acredita al **próximo** `advance` dentro de la ventana, no exige estar
  mirando. Considerar `scope` para no castigar zonas horarias (eventos en varias franjas).
- **Determinismo:** el disparo usa RNG sembrable para test; en prod, seed por tiempo. Nunca decide el
  LLM.
- **Compatibilidad:** aditivo (modelo + YAML + un factor en `multiplier`); sin eventos activos el juego
  es idéntico a hoy.
