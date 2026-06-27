# SDD 47 — Minería: producción, trabajadores y almacenamiento (silos)

> **Estado:** **diseño** (no implementado) · **Fecha:** 2026-06-27
> **Relacionado:** SDD 46 (alojamiento/capacidad de unidades — los trabajadores son `personnel`),
> SDD 1 (grafo + asistente), SDD 13 (rigor científico: abundancia real por planeta), SDD 42
> (mercado/precios), `content/{buildings,units,minerals,planets}.yaml`,
> `app/services/{production,economy,effects}.py`.

## 1. Objetivo
Definir y documentar la **economía de minería** de punta a punta, hoy parcialmente implícita:
1. **Cuánto produce una mina por hora** y **cuál es el cálculo exacto** (hoy está en el código pero no
   documentado ni en el grafo).
2. **Apilar minas**: ¿más minas ⇒ más por hora? (sí, hoy lineal) — y cómo se relaciona con los
   **trabajadores**.
3. **Trabajadores ↔ minas**: hoy el trabajador **no hace nada** para producción (la descripción
   promete "+producción" pero no hay código). Diseñar que **los trabajadores operan las minas**: más
   trabajadores ⇒ más recolección, pero **si tenés muchas minas y pocos trabajadores, cada mina rinde
   menos** (la mano de obra se reparte).
4. **Almacenamiento**: cada mina/jugador tiene un **tope por mineral**; si se llena, lo producido **se
   desperdicia** salvo que tengas **silos**. Un **silo guarda un solo tipo de material**.
5. Todo **objeto con atributos** (data-driven YAML), legible por humanos **y por la IA**.

## 2. Estado actual (verificado 2026-06-27)
- **Fórmula (pura, `production.py:compute_mine_output`):**
  ```
  output_de_una_mina = horas_transcurridas · base_output_per_hour · abundance
  ```
  Luego en `economy.py:collect_mines`: `amount = output · production_mult`, acreditado **lazy por
  timestamp** (sin cron) al stock del jugador en ese planeta.
  - `base_output_per_hour = 60` (en `mine`, `buildings.yaml`).
  - `abundance = content.planet_abundance(planet, mineral)` (0..~2) — la **abundancia real** del
    mineral en ese planeta (SDD 13). En lunas/colonias usa `grants/100`.
  - `production_mult = effects.multiplier(player, "production")` = boons de dioses × tecnologías
    (`mining_efficiency` +25%, `deep_core_mining` +25%) × alianza × eventos (SDD 36).
- **Apilado de minas:** cada mina acumula **independiente**; el total es la **suma** ⇒ N minas del
  mismo mineral ≈ N× producción. **Lineal, sin rendimientos decrecientes ni mano de obra.**
- **Trabajadores:** existe la unidad `worker` (desc: "Aumenta produccion y construccion") pero
  **ningún servicio la usa** para producción → hoy es **decorativa**. **Hueco a cerrar.**
- **Almacenamiento:** **no hay tope** — los stocks crecen sin límite; nada se desperdicia; no hay silos.

## 3. Producción: fórmula documentada + apilado
La fórmula **se mantiene** (no se rompe); este SDD la **documenta** y le agrega dos factores nuevos
(**staffing** de trabajadores §4 y **overflow** por tope §5):
```
output_mina = horas · base_output_per_hour · abundance(planeta, mineral)
            · production_mult                       # boons × tech × alianza × eventos (ya existe)
            · staffing                              # NUEVO §4  ∈ [0,1]
recolectado = min(output_mina, espacio_libre_en_storage(mineral))   # NUEVO §5 (overflow)
```
- **Más minas ⇒ más producción** sigue siendo cierto, pero ahora **mediado por trabajadores**: sin
  mano de obra suficiente, sumar minas rinde cada vez menos (§4) — responde tu intuición
  *"si tenés muchas minas vas a recolectar menos porque necesitás más trabajadores"*.

## 4. Trabajadores ↔ minas (staffing) — el modelo nuevo
**Idea:** cada mina necesita **trabajadores para operar a full**. Los trabajadores son un **pool
compartido** del jugador (unidad `worker`, dominio `personnel` de SDD 46). Se reparten entre todas las
minas.

### 4.1 Atributos nuevos (data-driven)
- En `mine` (`buildings.yaml`): `worker_slots: <int>` — trabajadores para rendir al **100%** (arranque:
  `5`). 
- (Opcional) en `worker` (`units.yaml`): `mining_power: <float>` (default `1`) — cuánto "vale" un
  trabajador (permite obreros mejorados por raza/tech).

### 4.2 Fórmula de staffing (pura, determinista)
```
required_workers = Σ ( mine.worker_slots ) sobre todas las minas activas
available_work   = Σ ( quantity(worker) · mining_power )           # tu pool de obreros
staffing         = clamp( available_work / max(1, required_workers), 0, 1 )
```
- `staffing` multiplica el output de **todas** las minas por igual (modelo global simple v1).
- **Consecuencias (lo que pediste):**
  - **Más trabajadores ⇒ más recolección** (hasta `staffing = 1`, lleno de personal).
  - **Más minas con los mismos trabajadores ⇒ `required_workers` sube ⇒ `staffing` baja ⇒ cada mina
    rinde menos.** "Tenés muchas minas pero te faltan obreros." 
  - **Punto óptimo:** mantener `available_work ≥ required_workers`. Pasar de ahí (más obreros que
    plazas) **no** sube producción (techo en 1.0) → no sobre-contratar (paralelo a SDD 35: "mandar de
    más es al pedo").
- **Variante v2 (opcional):** sobre-staffing da un bonus suave (p.ej. `staffing` hasta 1.2 con
  `soft_cap`), o asignación por-mina en vez de global. v1 = global con techo 1.0 (claro y testeable).

### 4.3 Costo de tener trabajadores
- Los trabajadores **ocupan plazas** (`personnel`, SDD 46) → necesitás base central/labs para alojarlos
  ⇒ otro límite natural (no podés tener obreros infinitos). 
- (Opcional, decisión de balance) **upkeep**: cada worker consume X energía/h o algo de mineral/h. v1
  **sin upkeep** (más simple); se evalúa si hace falta frenar el crecimiento.

## 5. Almacenamiento y silos (tope por mineral)
**Idea:** no podés acumular minerales infinitos. Cada **mineral** tiene una **capacidad** de almacén;
lo que se produce por encima **se desperdicia** (overflow) hasta que amplíes con **silos** o gastes el
stock.

### 5.1 Atributos nuevos (data-driven)
- En `mine`/`headquarters` (`buildings.yaml`): `storage: <int>` — capacidad base que aporta ese
  edificio, repartida/￼asignada al mineral que corresponda (la HQ da un colchón base por mineral;
  cada mina aporta un pequeño buffer del mineral que extrae).
- **Edificio nuevo `silo`** (category `storage`): `storage_capacity: <int>` (arranque `10000`). **Guarda
  un solo tipo de material**: al construirlo se elige el mineral (igual que la mina elige
  `production_mineral`) → `Building.storage_mineral`. Un silo de Hierro no guarda Silicio.
- (Opcional) en `minerals.yaml`: `base_storage: <int>` — colchón inicial por mineral aun sin silos.

### 5.2 Fórmula de capacidad (pura)
```
storage_cap[mineral] = base_storage[mineral]
                     + Σ ( mine.storage      de minas que extraen ese mineral )
                     + Σ ( silo.storage_capacity de silos asignados a ese mineral )
espacio_libre[mineral] = max(0, storage_cap[mineral] − stock_actual[mineral])
```
- **Overflow:** en `collect_mines`, lo producido se acredita **hasta** `espacio_libre`; el resto se
  **pierde** y se registra (`journal: "overflow"`) para avisar ("tu Hierro está al tope: construí un
  silo o vendé"). Esto crea el bucle: producir → almacenar → **gastar/ampliar** (mercado SDD 42,
  construir, entrenar).
- **Silo por tipo (lo que pediste):** la capacidad es **por mineral**; un silo dedicado sube solo el
  tope de **su** mineral → tenés que decidir qué mineral priorizás almacenar.

### 5.3 Interacción con producción
- Si `espacio_libre[mineral] == 0`, la mina de ese mineral **produce al pedo** (overflow total) → la UI
  y la IA lo marcan como **cuello de botella** ("ampliá almacenamiento o consumí"). No se frena la
  simulación; solo se descarta el excedente (lazy, sin cron).

## 6. Todo como objeto con atributos (resumen data-driven)
| objeto | atributos relevantes (nuevos en **negrita**) |
|---|---|
| `mine` (building) | `base_output_per_hour`, `production_mineral`, **`worker_slots`**, **`storage`** |
| `silo` (building, NUEVO) | **`storage_capacity`**, **`storage_mineral`** (elegido al construir), `category: storage` |
| `headquarters` (building) | **`storage`** (colchón base por mineral) |
| `worker` (unit) | `domain: personnel` (SDD 46), **`mining_power`** |
| mineral (`minerals.yaml`) | **`base_storage`** (opcional), abundancia vía `planets.yaml` |
| planeta (`planets.yaml`) | `abundance` por mineral (ya existe, SDD 13) |

Todo editable en YAML → rebalancear = cambiar datos, no código (principio del proyecto).

## 7. Fórmula integrada (final)
```
staffing            = clamp( Σ worker·mining_power / Σ mine.worker_slots , 0, 1 )
output_mina         = horas · base_output_per_hour · abundance · production_mult · staffing
storage_cap[m]      = base_storage[m] + Σ mine.storage + Σ silo.storage_capacity(asignado a m)
recolectado[m]     += min( Σ output_mina(de m), storage_cap[m] − stock[m] )   # overflow descartado
```
Pura y determinista (sumas/clamp), barata (como hoy), **lazy por timestamp**.

## 8. Exposición data-driven + IA (clave)
- **`/catalog`**: minas con `worker_slots`/`storage`; silo con `storage_capacity`; worker con
  `mining_power`. (Cache Redis 300s, SDD 28.)
- **`/players/me`**: agrega `mining: { staffing, required_workers, available_workers }` y
  `storage: { <mineral>: { cap, stock, free, overflowing: bool } }` → el cliente y la IA ven el estado.
- **Grafo/asistente (SDD 1, `depgraph.py`):** aristas **worker→mina** (staffing) y **silo→mineral**
  (capacidad) + grounding `mining_economy`: "si `staffing<1` entrená obreros; si un mineral está
  `overflowing` construí un silo o vendé". El **NPC** (`npc.py`) usa esto: equilibra minas↔obreros y
  construye silos cuando rebalsa (no entrena minas que no puede operar ni produce a un almacén lleno).
- Helper `mining_report(player)` serializable para prompt y tests.

## 9. UI (web)
- Panel de **economía/bases**: por mineral, barra **stock/cap** (roja si rebalsa) + aviso "desperdiciando
  X/h". Indicador global de **staffing** ("obreros 18/25 — minas al 72%").
- Modal de **mina**: "rinde N/h × staffing × abundancia"; modal de **silo**: "Hierro +10.000".
- Pictográfico (SDD 43): ⛏ producción, 👷 staffing, 🛢 silo/almacén, chip "X/Y".

## 10. API
- `GET /catalog`, `GET /players/me` — extendidos (aditivo).
- `POST /bases/{id}/build` para `silo` acepta `storage_mineral` (qué guarda), como la mina elige mineral.
- (sin endpoints nuevos; el overflow y el staffing se calculan en el `advance`/`collect_mines`).

## 11. Tests / validación
- **Pureza:** `compute_mine_output` (ya existe) + `staffing_ratio(workers, mines)` +
  `storage_cap(buildings)` + `apply_overflow(produced, free)` testeables a mano.
- **Staffing:** 1 mina + obreros suficientes ⇒ 100%; 2 minas mismos obreros ⇒ <100% (cada una rinde
  menos); obreros de más ⇒ techo 1.0.
- **Storage/silos:** producción se corta al llegar al cap; construir silo del mineral sube el cap y
  desbloquea; silo de otro mineral **no** ayuda; overflow se registra en journal.
- **Compat/rollout:** sin los campos nuevos ⇒ `staffing=1` y `cap=∞` ⇒ comportamiento idéntico al
  actual (flags `mining_staffing_enabled`, `storage_caps_enabled`, default off al inicio).
- **e2e** (`tests/test_api_e2e.py`): producir con staffing<1 vs full; rebalsar un mineral y ver el aviso;
  construir silo y verificar que el cap sube y deja de desperdiciar.

## 12. Plan de implementación (cuando se decida)
1. **Contenido:** `worker_slots`/`storage` en `mine`+HQ, `mining_power` en `worker`, edificio `silo`
   (+`storage_mineral`), `base_storage` opcional en minerales. Validar carga.
2. **Cálculo puro** (`production.py`): `staffing_ratio`, `storage_cap`, `apply_overflow` + `mining_report`.
   Tests.
3. **Integración** en `collect_mines`: aplicar `staffing` y `overflow` (detrás de flags, default off).
4. **Exposición:** `/catalog` + bloques `mining`/`storage` en `/players/me`. Tests + e2e.
5. **IA:** aristas + grounding `mining_economy`; NPC equilibra obreros/silos.
6. **UI:** barras stock/cap + staffing + avisos de overflow; pictográfico.
7. **Rollout:** medir con flags off → prender staffing y storage en releases separadas (balance).

## 13. Riesgos / decisiones
- **No frustrar:** activar topes/staffing puede sentirse como un nerf. Mitigar: arrancar **generoso**
  (silos grandes, `worker_slots` bajos) y con flags off → medir → ajustar por YAML.
- **No romper partidas vivas:** al prender storage, **no** borrar stock por encima del cap; solo frena
  **nueva** producción (igual criterio que SDD 46 con unidades).
- **Balance del bucle:** producción → almacén → gastar es el corazón del juego; `worker_slots`,
  `storage_capacity` y abundancias se afinan juntos. La IA ayuda a no quedar trabado.
- **Granularidad:** v1 staffing **global** (un ratio para todas las minas) y storage **por jugador/
  planeta** según el stock actual (`planet_stocks` ya es por planeta) — coherente con el modelo de hoy;
  asignación por-mina es v2.
- **Relación con SDD 46:** los obreros consumen plazas `personnel`; los dos SDDs comparten el concepto
  "todo tiene un tope físico" (unidades→alojamiento, minerales→silos).
