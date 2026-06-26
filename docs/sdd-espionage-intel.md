# SDD 35 — Espionaje e inteligencia (espías, contraespías, intel persistida)

> **Estado:** **implementado** (en producción) · **Fecha:** 2026-06-24
> **Relacionado:** SDD 34 (combate/calculadora), SDD 1/2 (grafo + asistente), SDD 28 (uso IA),
> `app/services/{combat,effects,alliances}.py`, `app/models` (AttackMission/ExpeditionOrder como
> patrón), `content/{units,buildings,technologies}.yaml`.

## 1. Objetivo
Sistema de **espionaje**: mandás **espías** a un objetivo (player/NPC) y obtenés **información** (qué
unidades/defensa/recursos tiene). La info **se guarda por objetivo** (la ves al clickear ese
player/NPC) y **se desactualiza con el tiempo** → para estar al día hay que **seguir espiando**. Hay
una **relación matemática espías ↔ info** con **contraespionaje** (contraespías + edificio/tecnología)
que **ofusca** la info y hace que **mandar de más sea al pedo**. Alimenta la **calculadora de combate**
(SDD 34) y al **asistente IA** (grounded, sin alucinar).

## 2. Piezas nuevas (data-driven)
- **Unidad `spy`** (personnel, `content/units.yaml`): stat **`spy`** (poder de espionaje), bajo
  attack/defense; `requires` un edificio (p.ej. `intel_agency` o `research_lab`).
- **Edificio `counter_intel`** (category `defense`, `content/buildings.yaml`): `counter_power` flat
  (análogo a `turret.defense_power`) → sube la defensa de espionaje del dueño. (Los espías también
  pueden contar como contraespías al defender, vía su stat `spy`.)
- **Tecnologías** (`content/technologies.yaml`): efectos **`espionage`** y **`counter_espionage`**
  (multiplicadores permanentes), integrados a `effects.multiplier` (hoy soporta production/attack/
  defense → se agregan estos dos).
- **Misión `SpyMission`** (modelo, patrón de `AttackMission`): viaja al objetivo, **resuelve al
  llegar**, devuelve intel (y a veces se detecta / pierde espías).

## 3. Fórmula (paralela al combate, determinista)
```
spy_score     = power(espías, "spy") · espionage_mult
counter_score = ( power(contraespías_del_objetivo, "spy") + counter_intel·counter_power ) · counter_mult

depth = spy_score / (spy_score + counter_score)          # ∈ [0,1] = profundidad/precisión de la intel
detect_prob = counter_score / (spy_score + counter_score) # = 1 - depth (cuota del defensor)
```
- `espionage_mult`/`counter_mult` = `effects.multiplier(...)` (boons × tech × alianza), igual que
  attack/defense en combate.
- **`depth`** decide **cuánto y qué tan exacto** ves (§5). **`detect_prob`** decide si el defensor se
  entera ("⚠ te espiaron") y si **perdés espías** (más contraespionaje → más detección/bajas).

## 4. La relación matemática (por qué "mandar de más es al pedo")
Para alcanzar profundidad `d` necesitás `spy_score ≥ counter_score · d/(1-d)`:
| objetivo `depth` | espías necesarios (× el counter del rival) |
|---|---|
| 0.5 (rangos) | **1×** |
| 0.8 (aprox.) | 4× |
| 0.9 (casi exacto) | 9× |
| 0.95 (exacto) | 19× |
→ **rendimientos decrecientes:** pasar de 0.9 a 0.95 cuesta el doble de espías para casi nada →
**mandar más es al pedo** una vez que la profundidad ya es alta. Y si el rival sube su `counter_score`
(edificio/tech/contraespías), **multiplicás los espías necesarios** → "es al pedo, tienen más
contraespionaje". Además, contra un objetivo muy protegido, `detect_prob` alta = **te detecta y perdés
espías** por poca info. **Óptimo:** mandar lo justo para superar el umbral del rival, no más.

## 5. Qué ves según `depth` (ofuscación / no dar toda la info)
La intel se revela **graduada** — el contraespionaje del defensor baja tu `depth` y por ende sólo ves
**rangos**, no exactos:
| `depth` | qué se revela |
|---|---|
| < 0.25 | nada útil: sólo "presencia / score público"; el rival quizá te detecta |
| 0.25–0.5 | **rangos amplios** ("ejército ~50-150", "defensa media") |
| 0.5–0.8 | conteos **aproximados** + edificios principales + torretas (±) |
| 0.8–0.95 | conteos casi exactos + recursos estimados |
| > 0.95 | **exacto**: unidades, defensa, torretas, recursos, multiplicadores |

## 6. Intel persistida + desactualización ("seguir espiando")
- **Modelo `IntelReport`** `(observer_id, target_id, as_of, depth, payload)` — único por par; al re-espiar
  se actualiza (si la nueva `depth` ≥, reemplaza; si no, mantiene la mejor + refresca `as_of`).
- **Confianza = `depth · decay(now - as_of)`** (half-life configurable, p.ej. 6-12 h). Intel vieja →
  confianza baja → la UI muestra "intel de hace Xh (puede estar desactualizada)" y la calculadora
  **ensancha los rangos**. → incentivo a **re-espiar** para mantener la foto al día.
- **Click en player/NPC** → panel con la intel guardada (campos según `depth`, `as_of`, confianza) +
  botón "🕵 espiar de nuevo". Sin intel → sólo ves lo público (score/ranking, SDD 12).

## 7. Integraciones
- **Calculadora de combate (SDD 34):** el `defender_force`/defensa que usás para planear un ataque
  **sale de tu IntelReport** (con incertidumbre si la confianza es baja) → "espiá antes de atacar".
- **Asistente IA (SDD 1/2/28):** usa **tu** intel guardada (server-side, grounded) para aconsejar
  ("la última intel de X es de hace 8h y baja; espiá de nuevo antes de atacar") y para el plan de
  combate. Determinista, atribuible por `player:<id>` (SDD 28). El LLM **no inventa** datos del rival:
  sólo narra lo que hay en tu IntelReport.
- **Alianza `shared_vision`** (ya existe): da una **intel base** compartida de los enemigos entre
  aliados (depth baja gratis) — espiar la mejora.

## 8. API (diseño)
- `POST /spy` `{target_base_id|target_player, spies:{spy:N}}` → despacha `SpyMission` (viaje).
- `GET /intel` → lista de IntelReports del jugador (con confianza/as_of).
- `GET /intel/{target}` → detalle (campos según depth).
- (resolución en `process_missions`, junto a ataques/expediciones).

## 9. Tests / validación
- **Pureza:** `resolve_spy(spy_force, counter_force, mults, counter_power)` → `depth`/`detect` testeable
  a mano (umbrales de la tabla §4).
- **Graduación:** depth baja → payload con rangos; depth alta → exactos (campos correctos por tier).
- **Persistencia/decay:** IntelReport se guarda al espiar; la confianza baja con el tiempo; re-espiar
  refresca. e2e: `POST /spy` → `GET /intel/{target}` devuelve datos coherentes con la depth resuelta.
- **Detección:** counter alto → el defensor recibe notificación y el atacante pierde espías.
- **IA:** el asistente no expone datos del rival que no estén en tu IntelReport.

## 9.bis Estado de implementación (2026-06-24) — v1 (backend)
- **Contenido:** unidad `spy` (stat `spy:10`) + edificio `counter_intel` (`counter_power:60`).
- **Modelos + migración:** `SpyMission` (patrón de AttackMission) + `IntelReport` (único por
  observer+target).
- **Servicio `app/services/espionage.py`:** `resolve_spy` (puro: `depth=spy/(spy+counter)`),
  `_counter_power` (espías + counter_intel), `graded_payload` (revelado por tiers + `_blur` a rangos),
  `start_spy` (valida, gasta energía, saca espías del stock, despacha viaje), `process_spy_missions`
  (resuelve al llegar → guarda intel + detección/bajas + notifica; al volver reintegra sobrevivientes),
  `intel_confidence` (decay por half-life), `player_intel`. Enganchado en `state.advance`.
- **API:** `POST /api/v1/spy`, `GET /api/v1/intel`, `GET /api/v1/intel/{target}`.
- **Tests:** servicio (fórmula, payload graduado, ciclo completo, counter_intel baja depth + detecta) +
  e2e (lanzar → resolver → leer intel; error). **231 verdes.**
- **UI web (hecho):** en el modal de planeta cada colonia enemiga muestra la intel guardada (depth,
  confianza coloreada por antigüedad + aviso de desactualización, campos graduados) + botones
  **🕵 espiar** (`POST /spy`) y **⚔ atacar**; la intel se recarga (`GET /intel`) en cada refresh.
  Bilingüe ES/EN. Sin intel → solo info pública.
- **Intel → combate (HECHO):** `/combat/plan` (SDD 34) ya estima la defensa **desde tu intel**; y la
  **Calculadora de combate** tiene un botón **🧮 "a la calculadora"** en el bloque de intel que
  precarga el lado defensor desde lo revelado (unidades exactas si depth≥0.8, torretas si ≥0.6). El
  asistente IA tiene la intel en contexto + grounding `mech_combat_planning` para usar las herramientas.
- **Pendiente (follow-up):** técnicas `espionage`/`counter_espionage` (tech tree); visión de alianza
  como intel base.

## 10. Riesgos / decisiones
- **Balance:** `spy`/`counter_power`/half-life se afinan por YAML; arrancar conservador (que espiar
  valga, pero el contraespionaje sea defensa real).
- **Privacidad/anti-cheat:** el server **nunca** devuelve más de lo que la `depth` permite (la
  ofuscación se hace server-side; el cliente jamás recibe el estado exacto si la depth es baja).
- **Costo de cómputo:** resolución barata (sumas), como el combate.
- **Compatibilidad:** aditivo (nueva unidad/edificio/tech/modelo); no rompe partidas existentes
  (sin intel = sólo info pública, como hoy).
