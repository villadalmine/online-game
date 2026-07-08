# SDD 84 — NPC AI: visión del grafo completo + más acciones + ruteo de modelo

## Contexto (por qué)
El usuario notó que la NPC "decayó" y "juega mal / solo cosas básicas, no usa todo el grafo del juego".
Análisis con métricas (Prometheus):
- El LLM RESPONDE bien (0 errores) pero ~41% de las decisiones caen a reglas; motivo dominante
  **`infeasible`** (elige acciones que no puede ejecutar), no parse/errores.
- **2 de 3 NPCs corrían en el modelo local débil `qwen2.5:7b`** (18-50% de jugadas aplicadas) vs la de
  nube `gemma-4-31b` (80-100%). La GPU buena (P4) está apagada por mantenimiento.
- **Por qué "ahora":** antes del fix del datetime (1.190.0) el cerebro LLM SIEMPRE crasheaba → las NPC
  jugaban con reglas (sólidas). Al arreglarlo, empezaron a seguir al LLM — y el modelo chico jugaba
  peor que las reglas.
- **Por qué "básico":** el estado que veía el LLM solo incluía opciones **pagables y desbloqueadas YA**;
  nunca veía lo avanzado → no podía apuntar a ello. Y el vocabulario de acciones eran **7**
  (build/train/attack/research/spy/recall/expedition) — sin colonizar, comerciar, satélites, drones,
  búnker, diplomacia.

## Cambios
### 1) Visión del grafo completo (`_npc_state`)
- `research_options` ahora son `{tech, unlocks:[...]}` → el LLM ve **qué desbloquea** cada tech.
- `locked_buildings` / `locked_units`: TODO lo que existe pero está bloqueado, con **qué falta**
  (`tech:<x>` o `building:<y>`). El LLM ya no está ciego a lo avanzado → planifica hacia ello.
- `colonizable` (planetas colonizables ya, con colony_ship) y `market_planets` (dónde vender).
- El prompt le pide "THINK BIG": investigar/construir el prerequisito que abre una capacidad que le
  falta, en vez de spamear lo básico.

### 2) Más acciones (`dispatch_action` + prompt)
- **`colonize`** (`{planet}`) → `colonization.found_colony` (expansión económica).
- **`trade`** (`{planet,mineral,quantity}`) → `market.sell` (vender excedente por energía).
- (build/train ya soportan TODO el catálogo una vez desbloqueado → con la visión nueva la NPC llega
  sola a lo avanzado. Combate/spy/expedition/recall/research ya existían.)

### 3) Ruteo de modelo
- Con la GPU buena apagada, `LLM_MODEL=gemma4-paid` (values-prod) + `npc_llm_model=""` → **todas las
  NPC heredan el modelo fuerte de nube** (las jugadas dejan de ser infeasible por modelo chico). El
  split gpu/cloud (SDD 19 §9) vuelve cuando se re-prenda la GPU con un modelo local capaz.

## Fix de infra relacionado (mismo release)
- **El tick estaba MUERTO** ~2.5h: un job quedó Pending (pineado al nodo eliminado en el mantenimiento)
  y con `concurrencyPolicy: Forbid` bloqueaba TODOS los ticks → las NPC no recibían turnos. Se borró el
  job zombie y se agregó **resiliencia** al CronJob (`activeDeadlineSeconds: 240` + `backoffLimit: 1` +
  `startingDeadlineSeconds: 120`) para que un tick trabado se AUTO-FALLE antes del próximo y el mundo
  nunca se frene por un job colgado. Ver [[cd-reuse-values-gotcha]].

## Tests
- `test_npc_state_shows_full_graph_vision` (bloqueados + qué falta + colonizable/market + unlocks).
- `test_llm_dispatch_colonize` (la NPC coloniza vía el LLM).

## Follow-ups (SDD 84 v2)
- Más acciones al vocabulario: satélites (recon), drones/misiles (arsenal intra-planeta), búnker
  (cavar/salas/evolucionar IA), diplomacia (tributo por LLM), mercado (comprar/transportar), mover
  tropas. Cada una reusando su servicio + hint de factibilidad + test.
- Que el `backend` de las métricas refleje el modelo real cuando la GPU está apagada (hoy dice "gpu"
  aunque use gemma).
