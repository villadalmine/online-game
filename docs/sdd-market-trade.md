# SDD 42 — Mercado, comercio y economía por-planeta

> **Estado:** propuesto (SOLO especificación — NO implementar todavía) · **Fecha:** 2026-06-25
> **Relacionado:** [SDD 37 colonización](sdd-colonization.md) (bases por planeta), [SDD 13 precisión
> científica](sdd-scientific-accuracy.md) (abundancia/ubicaciones reales), `app/services/alliances.py`
> (benefit `trade`), `app/services/economy.py` (stocks/minas), `content/planets.yaml` (abundancia),
> [SDD 41 insights](sdd-meta-insights.md) (precios derivados que sobreviven a cambios de contenido).

## 0. Cómo usar este SDD
Todo data-driven y derivado: los **precios NO se hardcodean**, se **calculan** del contenido +
abundancia del planeta + oferta/demanda → cuando cambien unidades/balance, los precios siguen siendo
válidos (igual filosofía que SDD 41). El **policy de comercio por alianza** se deja como estructura
de datos lista, aunque v1 no lo chequee.

## 1. Objetivo
Un **mercado** donde comprás/vendés cosas. Tres capas:
1. **Mercado local del planeta**: comprás a los **precios de ESE planeta** (lo barato donde abunda).
2. **Mercado intergaláctico de la galaxia** (un hub por galaxia): precios por **oferta y demanda**
   (estilo stock market), pagás en **divisa de energía**.
3. **Cuevas ilegales / black market** del hub: pagás con **lo que quieras (incluso materiales)**,
   pero tenés que **viajar con tu nave**; con energía no hace falta viajar.
Pagás en **energía** lo que comprás (= lo que te saldría producirlo vos). Necesitás **siempre una
nave** para traer lo comprado a tu planeta. La **economía pasa a ser por-planeta**: el material tiene
que estar EN ese planeta para usarlo; si no, lo **transportás** entre planetas.

## 2. La pieza estructural (el crux): inventario POR-PLANETA
- **Hoy:** `ResourceStock(player_id, mineral_key, amount)` = **un solo pool** por jugador. No hay
  noción de "dónde" está el material.
- **Necesario (el usuario lo pide explícito):** el material vive **por planeta/colonia**. Construir en
  una base usa el stock **de ese planeta**; si falta, hay que **mover** material de otro planeta.
- **Cambio:** `ResourceStock(player_id, mineral_key, planet_key, amount)` (o por `base_id`). Ripplea a
  **todo**: minería (acredita al planeta de la mina), build/train (gasta del planeta de la base),
  saqueo, catch-up, asistente. **Es la refactor más grande** → debería ser su **propia fase/SDD**
  (Fase 2 acá), con migración backward-compatible (default `planet_key = mundo natal`; el pool viejo
  se mapea al natal).
- **Transporte:** `TransportMission` (patrón de AttackMission/expedición): mové `{mineral: qty}` de un
  planeta a otro; **viaja** (tiempo por distancia) y requiere **nave** (shuttle). Llega → acredita al
  destino.

## 3. Fuente de precios (el "grafo/tabla de precios")
No es una tabla hardcodeada: es una **función** (determinista, sobrevive a cambios de contenido):
```
# precio "intrínseco" en energía de un ítem = lo que te costaría producirlo
base_energy_price(item)  = energy_cost(item) + Σ_mineral  qty · mineral_energy_value
mineral_energy_value     = constante por mineral (o derivada de su rareza media)
# precio en un PLANETA = intrínseco ajustado por escasez local (abundancia, SDD 13)
planet_price(item, p)    = base_energy_price(item) · scarcity(p, item)
scarcity(p, mineral)     = 1 / max(abundance(p, mineral), ε)   # caro donde escasea, barato donde abunda
```
- Comprar un mineral en la Tierra (rico en hierro) → hierro **barato**; en Marte → otros precios.
- "Pagás lo mismo que si lo produjeras vos" = `base_energy_price` es exactamente el costo de hacerlo.
- Se expone como **`GET /market/prices?planet=`** (tabla calculada) → la UI muestra "cuánto vale cada
  cosa" y la IA (SDD 41) puede razonar sobre precios.

## 4. Mercado local del planeta
- Requiere una **estructura de mercado en ese planeta** (`content/buildings.yaml`: `market`,
  category `economy`) — "la base necesaria para copiar el mercado en ese planeta".
- **`POST /market/buy` `{planet, item, qty}`**: cobra `planet_price · qty` en **energía**, acredita el
  ítem al **stock de ese planeta** (Fase 2). Necesitás market activo en ese planeta.
- **`POST /market/sell`**: inverso (vendés stock local por energía, a un precio algo menor = spread).

## 5. Mercado intergaláctico (un hub por galaxia, ubicación científica)
- **Hub por galaxia** (data-driven, real): Vía Láctea → **Cinturón de asteroides** (entre Marte y
  Júpiter); otras galaxias → su hub plausible. `content` define el hub y su posición (para viaje).
- **Precios por oferta/demanda** (stock market): estado dinámico `MarketPrice(hub, item, price,
  updated_at)` que **se mueve con cada trade** (comprar sube, vender baja; mean-reversion lenta hacia
  el precio intrínseco). Determinista, sin LLM.
- Pagás en **divisa de energía** al precio que pone el mercado. Necesitás nave para traer lo comprado.
- (Se alimenta del journal SDD 38 → métricas de mercado + base para que la IA "juegue" el mercado.)
- **El patrón se repite en CADA galaxia** (un hub por galaxia, precios independientes por oferta/demanda
  local). Estando en el hub de tu galaxia podés **consultar precios de otras galaxias** ("mandar
  mensajes" a los otros hubs): `GET /market/hub/{galaxy}/prices` → ves el precio de cada ítem en cada
  hub → arbitraje informado (comprar barato en una galaxia y traer, si tenés cómo viajar). La consulta
  de precios es **gratis/instantánea** (info); mover bienes entre galaxias sí cuesta viaje/nave.

## 6. Cuevas ilegales / black market
- En el hub hay un **mercado negro**: pagás con **lo que quieras, incluso materiales** (trueque), a
  veces mejor precio / ítems no listados. **Requiere viajar con tu nave** (llevás los materiales
  físicamente). Con **energía** no hace falta viajar (la divisa es "remota"); con **materiales** sí.
- Riesgo/sabor: precios volátiles, sin garantías; gancho narrativo. Reusa `TransportMission` para el
  viaje de ida (materiales) y vuelta (lo comprado).

## 7. Comercio entre jugadores + policy de alianza (estructura lista, v1 no chequea)
- Vender/comprar **a otro jugador** (orden directa o vía hub). v1 **permite siempre**; pero se deja la
  estructura **`trade_policy`** por tipo de alianza (en `content/alliances.yaml`): p.ej. `embargo` a no
  aliados, `tarifa` reducida entre aliados, `bloqueo` total. El chequeo va en un solo punto
  (`can_trade(seller, buyer)`), hoy devuelve `True`; mañana lee `trade_policy`. Reusa el benefit
  `trade` ya existente.

## 8. Naves, presencia, aparcamiento y robos (mecánica)
**Presencia (dónde estás vs dónde comprás):**
| situación | para VER precios | para COMPRAR y traer |
|---|---|---|
| tu propio planeta (tenés base) | nada | nada (lo comprado ya está en casa) |
| otro planeta donde **ya tenés base** | nada (lo ves remoto) | solo **capacidad de almacenaje** para guardar lo comprado |
| otro planeta **sin base** | **nave protocolar de ventas** (viaja, scoutea precios, vuelve) | **nave de cargo** (viaja, compra y vuelve con la mercadería) |

- **Naves de comercio (content/units.yaml):** `protocol_ship` (barata, sin carga: viaja a ver precios
  y vuelve → "ya tenés una idea") y `cargo_ship` (con bodega: compra y trae). Pagar con **energía** no
  exige viaje de bienes si comprás en tu planeta; traer bienes de afuera **siempre** exige cargo+viaje.
- **Aparcamiento:** el mercado de un planeta tiene **1 solo slot de nave**. Para estacionar más,
  comprás **aparcamiento en los hangares** (edificio/upgrade `hangar` → +N slots). El **hub central de
  la galaxia tiene aparcamiento INFINITO** (está en el espacio).
- **Robos en el hub central:** hay **piratería** — un convoy comercial puede ser **atacado y SAQUEADO**
  (no solo destruido): te roban la mercadería/unidades que llevás. Conviene llevar **escolta militar**
  (naves + militares). Reusa `resolve_combat` (SDD 34): el convoy tiene defensa = escolta; si pierde,
  el atacante saquea la carga. → comerciar en el hub tiene **riesgo** (gancho para PvP/economía).

## 9. Fases (porque es grande)
- **Fase 0 (datos):** `trade_policy` en alianzas (no-op), `market`/hub en content, `mineral_energy_value`.
- **Fase 1 (precios + mercado local con pool actual) — IMPLEMENTADA (2026-06-25):** edificio
  `market`; `mineral_price(planet, mineral)` = base/abundancia (premium = caro); `GET /market/prices`,
  `GET /market/planets`, `POST /market/buy|sell` (energía ↔ minerales, requiere market activo en ese
  planeta); panel web 💱 Mercado; journal `market_buy`/`market_sell`. Acredita al **pool por-jugador**
  (per-planeta = Fase 2).
- **Fase 2 (inventario por-planeta) — PARCIAL (2026-06-25):** `ResourceStock` con `planet_key` +
  migración (backfill al mundo natal) + `planet_stocks`/`player_stocks` (agregado). Minería acredita
  al planeta de la mina; build/train/research gastan del planeta de la base (si falta → "transportá");
  saqueo desde el planeta de la base atacada; mercado compra/vende en su planeta; UI muestra stock por
  planeta. **Pendiente de Fase 2:** `TransportMission` + naves `protocol_ship`/`cargo_ship` + reglas
  de presencia (§8). La estructura ya está; falta el transporte para mover bulk entre planetas.
- **Fase 3 (hub dinámico + black market + aparcamiento + robos):** `MarketPrice` por oferta/demanda;
  cuevas ilegales (pagás con materiales, viajás); **slot único** en mercados de planeta + upgrade
  `hangar` (más slots), aparcamiento **infinito** en el hub; **piratería/saqueo** de convoyes →
  escolta militar (reusa `resolve_combat`); precios inter-galaxia (consultar otros hubs).

## 10. Tests / validación (por fase)
- Precios: `planet_price` barato donde abunda, caro donde escasea; `base_energy_price` == costo real.
- Buy/sell: cobra/acredita energía y stock correctos; sin market en el planeta → error.
- Per-planeta: construir usa el stock del planeta; sin material local → pide transporte; transporte
  viaja y acredita al destino.
- Hub: comprar sube el precio, vender baja; revierte lento. Black market exige nave/viaje.
- Alianza: `can_trade` hoy True; con `trade_policy` de prueba, bloquea/permite según el tipo.

## 11. Cómo encaja / riesgos (evaluación)
- **Encaja muy bien** con lo que ya hay: abundancia (SDD 13) da los precios por planeta "gratis";
  misiones (combate/espionaje/colonización) dan el patrón de **transporte**; energía es ya la moneda;
  alianzas ya tienen `trade`; journal+insights (38/41) hacen el mercado **medible y aprendible** por la
  IA. La colonización (SDD 37) le da sentido al per-planeta (colonias producen distinto → comerciás).
- **Riesgo principal:** el **inventario por-planeta** (Fase 2) es una refactor profunda del corazón
  económico — hacerla sola, con migración backward-compatible y muchos tests, **con el usuario
  presente**. Las Fases 0/1/3 NO la requieren y dan casi todo el "feel" de mercado antes.
- **Balance:** spread comprar/vender + mean-reversion del hub para que no se arbitre infinito; el
  black market con riesgo para que no sea siempre óptimo.
- **Compatibilidad:** todo aditivo; sin market construido, el juego es idéntico a hoy.
