# SDD 34 — Estrategia de combate: fórmula, matriz y calculadora (para web + IA)

> **Estado:** **implementado** (en producción) · **Fecha:** 2026-06-24
> **Relacionado:** `app/services/combat.py` (`resolve_combat`), `app/services/effects.py`
> (`multiplier`), `content/units.yaml`, `content/buildings.yaml` (turret), SDD 1 (grafo/RAG),
> SDD 2 (asistente), SDD 28 (uso IA).

## 1. Objetivo
Documentar **exactamente** cómo se resuelve el combate (ataque/defensa, multiplicadores, pérdidas)
para: (a) poder hacer una **calculadora** ("¿cuánto necesito para ganar / para defender?"), y (b) que
la **IA de ayuda** lo sepa **sin alucinar** (cálculo determinista en el server; el LLM sólo narra).

## 2. Modelo (verificado en `resolve_combat`, función pura/determinista)
Cada unidad tiene `stats: {attack, defense, hp}`. Una *fuerza* es `{unidad: cantidad}`.

**Poder de una fuerza** para una stat: `power(F, s) = Σ_u cantidad_u · stats_u[s]`.

**Resolución de un ataque:**
```
attack_score  = power(atacante, "attack")  · atk_mult
defense_score = ( power(defensor, "defense") + flat_defense ) · def_mult
total         = attack_score + defense_score

GANA el atacante  ⇔  attack_score > defense_score      (empate exacto ⇒ gana el defensor)

# pérdidas: cada lado pierde proporcional a la CUOTA del rival en el total
attacker_loss_ratio = defense_score / total       # piezas perdidas ≈ round(cantidad · ratio)
defender_loss_ratio = attack_score / total
```
- **`flat_defense`** = `torretas · 40` (cada `turret` aporta `defense_power: 40`) **+** defensa mutua de
  alianza (`mutual_defense_flat`). Las **torretas son edificios, NO se destruyen** en el combate
  (las pérdidas sólo afectan unidades) → **defensa flat permanente**, muy costo-efectiva.
- **`atk_mult` / `def_mult`** = `effects.multiplier(...)` = **boons de dioses × tecnologías
  investigadas × beneficios de alianza** para `attack`/`defense`. Es tu poder *efectivo*.
- **`hp` NO se usa hoy** (las pérdidas son por cuota de poder, no por daño/hp). Queda para un futuro
  modelo de **daño por rondas** (backlog) — documentarlo para no confundir la calculadora.

## 3. Matriz de unidades (de `content/units.yaml` — data-driven, ajustable)
| unidad | attack | defense | hp | rol |
|---|---|---|---|---|
| worker | 0 | 1 | 5 | económico |
| scientist | 0 | 2 | 6 | ciencia |
| soldier | 8 | 5 | 12 | infantería barata |
| tank | 30 | 25 | 60 | ataque pesado |
| ship | 25 | 30 | 80 | defensa pesada |
| aircraft | 40 | 15 | 40 | máximo ataque, frágil |
| shuttle | 20 | 20 | 100 | mixto / expediciones |
| **turret** (edificio) | — | **40 flat** | — | defensa fija, no se pierde |

> Costos en `content/units.yaml`/`buildings.yaml` (roles por raza). El balance se cambia editando YAML.

## 4. Cálculos para atacar / defender (lo que va en la calculadora)
Sea `D = defense_score` del objetivo (incluye torretas y su `def_mult`).

- **¿Gano?** `attack_score > D`.
- **Poder de ataque mínimo para ganar:** `power(atacante,"attack") > D / atk_mult`.
- **Pérdidas según el margen** `k = attack_score / D` (cuánto "sobrepasás" la defensa):
  | k (ataque/defensa) | pierde atacante | pierde defensor |
  |---|---|---|
  | 1.0 (empata→pierde) | 50% | 50% |
  | 1.5 | 40% | 60% |
  | **2.0** | **33%** | 67% |
  | 3.0 | 25% | 75% |
  | 5.0 | 17% | 83% |
  → **regla práctica:** llevá **2-3× la defensa** del objetivo para ganar con pérdidas razonables
  (~25-33%). Apenas por encima = victoria pírrica (perdés casi la mitad).
- **Defensa necesaria (para sobrevivir un ataque esperado `A`):**
  `power(defensor,"defense") + torretas·40 ≥ A / def_mult`. Las **torretas** suben `D` sin riesgo de
  perderlas → primera línea de defensa barata; las unidades de defensa (ship) agregan poder pero se
  pueden perder.
- **Mezcla de unidades:** elegí por `attack`/`costo` para atacar (aircraft = más attack/u, pero frágil
  si contraatacan; tank = robusto) y por `defense`/`costo` para defender (ship/turret).

## 5. La calculadora (diseño)
- **Núcleo:** `resolve_combat` **ya es puro** → reutilizable. Sumar helpers puros:
  `min_attack_power_to_win(D, atk_mult, margin)`, `units_for_power(power, unit_key)`,
  `defense_needed(expected_attack, def_mult)`.
- **API determinista** (cacheable, sin LLM):
  - `POST /combat/simulate` `{attacker_force, defender_force, atk_mult?, def_mult?, flat_defense?}` →
    `{outcome, attack_score, defense_score, attacker_losses, defender_losses}`.
  - `POST /combat/plan` `{target_base_id | defender_force+turrets, margin}` → fuerza sugerida + pérdidas
    estimadas + costo. (Para un objetivo real, el server arma `defender_force`+torretas+`def_mult` y
    tu `atk_mult` desde `effects.multiplier`.)
- **Clientes:** una **calculadora web** (sliders de unidades → outcome/pérdidas en vivo) y el CLI, ambos
  llamando al endpoint. Todo data-driven (lee `stats` del catálogo).

## 6. Cómo lo "sabe" la IA (sin alucinar)
Los LLM son malos con aritmética → **no** dejar que el modelo calcule. Dos vías (patrón SDD 1/2):
1. **Grounding/RAG:** publicar la **fórmula + la matriz de stats** como documento recuperable (estilo
   `graph_documents`) → el asistente **explica** la mecánica correctamente.
2. **Cálculo determinista como herramienta:** el backend del asistente **llama a `resolve_combat`/
   `/combat/plan`** y mete el **resultado** en el prompt (o lo devuelve estructurado) → el asistente
   responde "necesitás ~12 tanks para ganarle a esa base con ~25% de pérdidas" porque **lo calculó el
   server**, no el LLM. (Igual que el asistente hoy se apoya en el grafo de dependencias, SDD 1.)
→ La IA queda **exacta y auditable**: narra números que vienen de la misma función que resuelve el
combate real. Medible/atribuible por `player:<id>` (SDD 28).

## 7. Tests / validación
- **Pureza:** `resolve_combat` ya testeado; agregar tests de los helpers (mínimo para ganar, pérdidas
  por margen, defensa necesaria) contra casos a mano de la matriz.
- **e2e:** `/combat/simulate` reproduce el resultado de un ataque real (mismos inputs → mismo outcome);
  `/combat/plan` sugiere una fuerza que efectivamente gana al simularla.
- **IA:** el asistente, dado un objetivo, devuelve un plan cuyos números **coinciden** con
  `/combat/simulate` (no inventados).

## 7.bis Estado de implementación (2026-06-24) — v1
- **Servicio `app/services/combat_calc.py`:** helpers puros `loss_ratios`, `min_attack_power`,
  `units_for_power`, `defense_needed` (sobre la misma fórmula que `resolve_combat`) + `attack_mult`
  (raza × tech × boons × alianza) + `plan_attack` (estima la defensa **desde el IntelReport** del
  atacante, no del estado real — SDD 35; cota alta = conservadora).
- **API:** `POST /combat/simulate` (determinista, == `resolve_combat`) y `POST /combat/plan`
  (`{target_base_id, margin}` → defensa estimada, tu `atk_mult`, poder necesario y opciones por
  unidad con pérdidas; 400 si no espiaste el objetivo).
- **Web:** botón 📊 planear en el panel de intel (modal de planeta).
- **Tests:** helpers vs la matriz, `simulate`==combate real, plan requiere intel + gana al simular;
  e2e. **242 verdes.**
## 7.ter Estado de implementación (2026-06-26) — v2 (follow-ups cerrados)
- **Calculadora web 🧮:** panel `data-panel="calc"` ("Calculadora de combate") con inputs por unidad
  (atacante/defensor) + torretas; llama a `POST /combat/simulate` debounced y muestra en vivo
  ganás/perdés, ⚔ vs 🛡 y las pérdidas de cada lado como chips. **Picto-aware** (SDD 43). No gasta
  nada (cálculo puro).
- **Asistente IA aterrizado:** nuevo documento de grounding `mech_combat_planning` (depgraph) le dice
  al modelo que **NO calcule de memoria** y use `/combat/plan` (estima defensa desde tu intel) y
  `/combat/simulate`, con la regla práctica "2-3× la defensa". Sumado al `mech_combat` que ya tenía la
  fórmula → el asistente explica/recomienda con números reales, no inventados.
- **SDD 34 COMPLETO.**

## 8. Riesgos / decisiones
- **`hp` sin usar:** dejar claro en la calculadora que hoy decide el poder (attack/defense), no hp; si
  se agrega daño por rondas (backlog), la fórmula y la calculadora cambian → actualizar este SDD.
- **Redondeo:** las pérdidas usan `round` → en cantidades chicas hay efectos de borde; la calculadora
  debe mostrar estimados.
- **Multiplicadores dinámicos:** boons expiran, tech/alianza cambian → el plan es una foto; recalcular
  al momento de atacar (el server usa `effects.multiplier` vigente).
- **Información del rival:** para `/combat/plan` contra una base real, exponer sólo lo que el atacante
  ya "ve" (visión de alianza, estimación de defensa) — no filtrar el estado exacto del defensor.
