# SDD 82 — Mejora de edificios en lote + claridad (qué mejora, alojamiento)

Reportado por el usuario jugando el panel **"mis bases"**: con muchos edificios iguales (p.ej. 30
torretas) mejorarlos era de a uno; además no se veía **qué** mejora cada nivel (¿defensa? ¿ataque?),
ni cómo conseguir **más plazas** para empleados/unidades. Tres arreglos, todos aditivos.

## 1) Mejora EN LOTE
- Servicio `build.upgrade_buildings_bulk(session, player, base_id, building_key, kind, count=None)`:
  toma los edificios activos de ese `building_key` en la base, ordena por **menor nivel primero**
  (para emparejarlos) y les da **+1 nivel a cada uno** reusando `upgrade_building` (que cobra el costo
  por nivel). Se **frena** cuando el material/energía no alcanza (BuildError → break) o al llegar a
  `count`. Devuelve `{upgraded, total, building_key, kind}` → el front muestra "mejoraste N de M".
- Endpoint `POST /api/v1/bases/{base_id}/buildings/upgrade-bulk?building_key=&kind=&count=`.
- Front: en la **cabecera del grupo** de edificios repetidos (`torreta ×30`) aparece un botón
  `⬆<icono>×N` por cada `kind` mejorable. Un click mejora todas las que alcancen tus recursos.
  `count` queda disponible en la API para "elegí cuántas" (el front hoy usa "todas las asequibles").

## 2) Qué mejora cada nivel (info)
- Los botones de mejora (individual y en lote) muestran el **efecto real** derivado del YAML
  `buildings.<key>.upgrade.<kind>` (no se desincroniza del contenido): `output_mult`→`+X% ⛏`,
  `defense_power`→`+X 🛡`, `hp`→`+X ❤`, `intercept_power`→`+X 🎯`, todo `/nivel`.
- Aclaración explícita: **las torretas solo defienden, no atacan** — mejorar defensa/antimisil NO sube
  ataque (era la duda del usuario). Helper `_upInfo(bkey, kind)` en el front.

## 3) Cómo tener más plazas (alojamiento)
- El bloque **🏠 Alojamiento** de "capacidad" ahora tiene un tooltip que explica el concepto (cada
  dominio tiene plazas; cada unidad ocupa una; con las plazas llenas no fabricás más de ese tipo) y,
  cuando vas **justo** (free ≤ 2), lista los edificios que dan plazas para ese dominio y cuántas,
  derivado del catálogo (`buildings.<key>.houses`). Helper `_housesFor(domain)`.

## Tests
- e2e `test_building_upgrade_bulk_e2e`: mejora 3 torretas de una (todas a L2) + caso de error (una mina
  no admite `kind=defense` → 400).

## Follow-ups
- UI "elegí cuántas mejorar" con pre-cálculo de costo (la API ya acepta `count`).
- Extender el lote a **todas las bases** de un planeta (hoy es por base, alineado al agrupado del panel).
