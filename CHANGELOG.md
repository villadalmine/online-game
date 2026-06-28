# Changelog

Registro de todo lo que vamos logrando. Formato basado en
[Keep a Changelog](https://keepachangelog.com/). Fechas en formato AAAA-MM-DD.

> Regla del proyecto: **toda feature entra con su test e2e** (`tests/test_api_e2e.py`).

## [Unreleased]

### 2026-06-28 — SDD 53 (diseño): balance de costos (defensa no gateada + asimetría por raza)
- `docs/sdd-resource-balance.md`: análisis (el rol `energetic` está en 22/22 items → para terran
  `energetic=silicon` gatea hasta la defensa: sin silicio no hay torreta ni soldados). Diseño:
  defensa/infantería = solo rol `structural` (siempre defendible), diversificar el rol por rama
  (ground=struct+advanced, air=energetic+advanced, …) y mantener la asimetría por raza
  (cada una con su mineral). Para iterar. No implementado aún.

### 2026-06-28 — Fix CD: pool de nodos (no pinear) + ttl corto (no llenar disco)
- El CD estaba pineado a UN nodo (`srv-rk1-nvme-01`); cuando ese entró en DiskPressure el workflow
  quedó `Pending` para siempre. Selector al **pool** `storage=rk1-longhorn` (rk1-nvme 01-04) → corre
  en un nodo sano. ttl: success 30m→10m, failure 2h→30m → los Workflows + sus PVCs (20Gi Longhorn)
  se limpian rápido y no llenan el disco. (Limpié los 4 fallidos acumulados ~80Gi.)
- **SDD 52** (`docs/sdd-cicd-storage-resilience.md`): por qué una PVC no evita el disco del nodo
  (imágenes en imagefs + réplicas Longhorn en `/var/lib/longhorn`) y qué iterar: StorageClass efímera
  de **1 réplica** para el workspace (3× menos disco), image-GC, artifact repo de Argo, alertas de
  DiskPressure. (Diseño, para iterar más tarde.)

## [1.104.4] - 2026-06-28

### 2026-06-28 — Fix CD: imagePullPolicy Always en los gates (no más imagen de test stale)
> Incidente: 1.104.3 no promovía — el gate `e2e-api` corría un test que YA estaba arreglado
> (`test_advisor_hack_grants_and_exhausts_daily_budget` con "mine") y fallaba, aunque local pasaba
> 387. Causa: re-deployar el MISMO tag → el nodo cacheaba la PRIMERA imagen de test (`IfNotPresent`
> por default) y reusaba la vieja. (No era arm ni flaky.)
- `imagePullPolicy: Always` en los pods `test-api` y `test-chrome` → siempre corren la imagen recién
  buildeada, aunque se re-use el tag. `podGC: OnWorkflowSuccess` (conserva pods fallidos para leer
  logs; sin esto no se podía diagnosticar — no hay artifact repo).

## [1.104.3] - 2026-06-28

### 2026-06-28 — Asistente: botón "🔓 crear gratis (hack)" — crea sin cobrarte aunque tengas material
> Bug reportado: tocabas el botón del asistente y te CONSUMÍA materiales (era el botón "Construir"
> normal). El de hack solo aparecía cuando ya NO tenías material → confuso.
- El hack ahora **CREA GRATIS** el objetivo (cubre el costo completo y construye → neto 0 en tu stock),
  **tengas o no materiales**, y arma toda la cadena (lab → tech → target). Gasta 1 hack diario y lo
  dice claro ("creé gratis X… te quedan N").
- La respuesta del asesor trae `hack_targets` → el front muestra un botón **"🔓 crear gratis: X"**
  separado del "Construir" (que sí cobra). Disponible mientras te queden hacks, aunque tengas material.
- Si das la orden ("construime X"), lo crea gratis solo. Mina/silo siguen pidiendo elegir mineral.
- Tests: `test_hack_creates_free_even_with_materials`, advisor suite verde.

## [1.104.2] - 2026-06-28

### 2026-06-28 — Hardening: JWT_SECRET y password de Postgres → Secret + secretKeyRef
- Antes `JWT_SECRET` y `DATABASE_URL` (que lleva la password de Postgres inline) se renderizaban como
  `value:` en TEXTO PLANO en el Deployment (visibles con `kubectl get deploy -o yaml`). Ahora van en el
  Secret `galaxy-secrets` y se consumen por **`secretKeyRef`** (como ya hacían OTP/API keys/metrics).
- El flujo cierra por el pipeline: los VALORES siguen viniendo del release (values-local, que Helm
  guarda en su Secret de release) y el `promote` los reusa con `--reset-then-reuse-values` → **Argo
  nunca maneja secretos crudos**; el chart los materializa en el Secret. SDD 33 / bloqueador de
  publicación (secretos fuertes fuera del manifiesto).

## [1.104.1] - 2026-06-28

### 2026-06-28 — Fix CD: el overlay de prod va en examples/ (values-*.yaml está gitignored)
- `values-prod.yaml` quedaba ignorado por `.gitignore` (`deploy/helm/values-*.yaml`) → el promote
  fallaba con "no such file" (prod intacto, falla antes del upgrade). Movido a
  `deploy/helm/examples/values-prod.yaml` (commiteable, sin secretos) y corregido el `-f` del promote.

## [1.104.0] - 2026-06-28

### 2026-06-28 — API HA + más capacidad de queries (pipeline-native) + asistente que construye la cadena
- **API HA**: overlay versionado `deploy/helm/values-prod.yaml` (replicas=3 + PodDisruptionBudget +
  topologySpread entre nodos) aplicado por el **CD** con `helm upgrade --reset-then-reuse-values -f`
  (los secretos siguen viniendo de la release previa; toda la config no-secreta vive en git y va por
  Argo, nada manual). El `player_lock` ya era distribuido por Redis (REDIS_ENABLED=true) → multi-réplica
  es seguro sin tocar código.
- **Más queries**: `postgres.maxConnections` configurable (100→**200**) + `sharedBuffers` + pool por
  réplica acotado (`dbPoolSize=8`/`dbMaxOverflow=12` → ~8 réplicas entran bajo el techo). OJO: subir
  max_connections reinicia Postgres (blip en el deploy; los datos persisten).
- **Asistente (SDD 2): el hack arma TODA la cadena en un click** — materializa y deja LISTOS al
  instante los edificios previos que falten **y las tecnologías requeridas** (p.ej. lanzadera → lab +
  Cohetería + lanzadera), no solo el material del target. Además dispara solo al darle la orden
  ("construime X"/"¿podés construirme X?"). Tests `test_hack_builds_full_chain_lab_tech_and_target`,
  `test_ask_command_uses_hack_to_build`.
- **Dashboard Grafana `npc-ai`**: 2 paneles nuevos — "Perfil/postura de los NPC en el tiempo"
  (`game_npc_posture`) y "Ataques NPC: humano vs NPC" (`game_npc_attack_targets_total`).
- **CD**: `podGC: OnWorkflowCompletion` + ttl de fallo más corto (incidente 2026-06-28: pods apilados
  en el ns compartido saturaron el controller de Argo y trabaron los deploys).

## [1.103.0] - 2026-06-28

### 2026-06-28 — SDD 51: analítica por jugador + gráficos in-app "📈 Tu historia"
- **Implementado (Fase 1-2):** modelo `PlayerSample` (muestreo throttleado del estado en
  `state.advance`, lazy, sin cron; migración `4e2f998dc2ef`), servicio `analytics.py`
  (`sample_player`/`history`/`event_counts`), endpoint `GET /players/me/history?hours=` (serie de
  energía/stock/unidades/score + conteo de acciones del journal), y **modal web "📈 Tu historia"**
  (botón en card Imperio) con **sparklines SVG** (sin librerías) + barras de acciones. i18n es/en.
  Flag `analytics_enabled` (default ON), `analytics_sample_seconds=300`. e2e
  `test_player_history_analytics_e2e`. Pendiente Fase 3: retención/downsample + admin + Grafana SQL.

### 2026-06-28 — Asistente: usa el hack al DARLE LA ORDEN + versión visible en la UI
- **Auto-hack por comando (SDD 2):** si le decís "construime X" (imperativo) sobre un objetivo único,
  te queda hack diario y solo te falta material/energía → el asistente **usa el hack y lo construye
  solo** (antes solo decía "te falta material" y dejaba un botón). Preguntas ("¿qué construyo?") NO
  gastan hack. Tests `test_ask_command_uses_hack_to_build` / `test_ask_question_does_not_spend_hack`.
- Texto del botón de hack actualizado ("🔓 hackear y construir X").
- **Versión visible:** `/health` ahora devuelve `version`; la UI muestra un pill `v<versión>` en el
  header → sabés exactamente qué está live sin adivinar.

### 2026-06-28 — Combate: límite de ataques por ventana (humanos y NPCs)
- Nuevo límite de gameplay: **3 ataques cada 4 h** por jugador (`attacks_per_window`/
  `attack_window_seconds`, 0 = sin límite). Aplica a humanos Y NPCs → la IA no "se zarpa" y el rival
  tiene tiempo de reagruparse. e2e `test_attack_rate_limit_per_window_e2e`.

## [1.102.0] - 2026-06-28

### 2026-06-28 — SDD 29 v2: la IA juega por PERFILES (y adapta sin LLM) + ataca NPCs + métricas
> Feedback: la NPC "no ataca / no tiene táctica / no se ve qué hace / siempre ataca humanos".
- **Perfiles que guían el cerebro POR REGLAS** (`PROFILES` en `npc.py`): economy/expand/research/
  rush/raid/turtle/aggressive/defensive/opportunist, cada uno con `margin` de ataque + flags
  (army_first, defense_first, expedite, colonize, arsenal). Antes la postura solo afectaba al LLM.
- **Selector DETERMINISTA** `pick_posture_rules`: elige el perfil según amenazas/economía/ejército/
  rivales → la IA **adapta su estrategia sin LLM** (antes, sin LLM, la postura nunca cambiaba → no
  adaptaba ni atacaba). Ahora **ataca de verdad** (margin por perfil; rush 1.05).
- **Expediciones + colonización** (perfil expand): construye transbordador, manda expediciones y
  funda colonias. **Arsenal** (perfil raid): usa misiles/drones para ablandar (SDD 49/50).
- **NPCs independientes** por default (`npc_shared_alliance=False`) → **también se atacan entre sí**
  (antes compartían alianza y solo pegaban a humanos). El target ahora es el rival más fuerte batible
  (humano o NPC; empate → humano).
- **Métricas (Grafana)**: `game_npc_posture{posture}` (gauge, recalculado en el tick) y
  `game_npc_attack_targets_total{target=human|npc}`. (Recordá: cada acción ya emite
  `game_journal_events_total{kind}` — ataques/misiles/drones/builds ya eran métrica.)
- **Visibilidad**: la postura se expone en `/players` (scoreboard) y se ve como **chip por NPC en el
  mapa** (💰 económico / ⚡ rush / 🛡 tortuga / 🚀 raider / 🔬 research / 🌍 expand…), i18n es/en.
- Tests: picker (turtle bajo ataque, economy temprano, rush con ejército+objetivo) + NPCs
  independientes se ven como enemigas.

### 2026-06-28 — SDD 2: el "hack" del asistente ahora CONSTRUYE el objetivo (un click, gratis)
- Antes `grant_hack` solo materializaba los minerales/energía que faltaban → el jugador igual tenía
  que construir a mano (y si faltaba un edificio requerido, fallaba). Ahora, tras materializar,
  **ejecuta la acción** (construye/entrena/investiga el target) en la base natal → en un click queda
  hecho. Mina/silo (piden elegir mineral) quedan materializados para que elijas. Test
  `test_hack_also_builds_the_target`.

### 2026-06-28 — SDD 51 (diseño): analítica por jugador + gráficos in-app
- Nuevo `docs/sdd-player-analytics-charts.md`: medir TODO por jugador (desde el journal SDD 38 +
  muestreo de estado `PlayerSample`) y mostrarlo como **gráficos en un popup** ("📈 Tu historia":
  energía/recursos/unidades/ataques en el tiempo). Series por-usuario en DB (no en Prometheus, por
  cardinalidad); Grafana por SQL datasource para operación. Diseñado, pendiente de implementar.

### 2026-06-28 — Fix UX: silo sin selector de mineral + techs de misiles/drones no listadas
> Dos bugs reportados al usar 49/50 en la web.
- **Silo**: pedía `target_mineral` pero el panel Acciones ocultaba el selector de mineral (solo se
  mostraba para `mine`). Ahora se muestra y se envía también para `storage` (silo) — helper
  `_needsMineral` en `renderCost`/`build`.
- **Techs de misiles/drones invisibles**: el panel Investigación ordenaba por una lista fija de
  categorías que NO incluía `strike`/`drones` → `rocketry`/`dronework`/etc. nunca aparecían (y al
  construir `launcher`/`drone_factory` decía "falta la tecnología" sin forma de investigarla). Agregadas
  al orden + etiquetas en `TECH_CAT` (🚀 Misiles / 🛸 Drones), es/en.

## [1.101.0] - 2026-06-28

### 2026-06-28 — SDD 49/50: balance fino de intercepción + mini-simulador
> Reescalado de la intercepción de misiles para que respete la intención de diseño y herramienta
> determinista para afinar números por YAML sin adivinar.
- **Intercepción reescalada** (antes 1 torreta frenaba ~3 nucleares — roto): `turret.intercept_power`
  30→**10**; `intercept_cost` sónico 1→**2**, transatlántico 3→**6**, nuclear 8→**30**. Ahora 1 torreta
  frena 5 sónicos / ~1.6 transatlánticos / 0.33 nucleares → **hacen falta 3 torretas para 1 nuclear**
  ("casi imposible salvo mucha defensa"); el enjambre de sónicos satura; el transatlántico queda en el
  medio. Trade-offs verificados: sónico = mejor daño/mineral (spam), nuclear = mejor daño/plaza y
  daño/⚡ pero premium/endgame.
- **`scripts/balance.py`** (`make balance`): mini-simulador determinista que imprime tablas de
  costo-eficiencia, intercepción y supervivencia de drones derivadas del YAML + funciones puras.
- **`tests/test_balance.py`**: invariantes de diseño (progresión de tiers, trade-offs, escala de
  intercepción/supervivencia) → un rebalanceo que rompa la intención falla el test. Tests de
  intercepción y e2e actualizados a los nuevos números.

### 2026-06-28 — Docs + CLI al día con SDD 49/50
- `docs/game-design.md`: nueva sección de **guerra intra-planeta** (misiles + drones) en Combate.
- **CLI** (`clients/cli`): comandos `strike <launcher> <target> <force>`, `drones <factory> <target>
  <force>` y `drones-recall <id>` → la feature queda alcanzable también desde el CLI (API-first).
  README actualizado con ejemplos.

## [1.100.0] - 2026-06-28

### 2026-06-28 — SDD 49/50 v1.5: PRENDIDOS + paneles web + NPC los usa
> Cierre de SDD 49 (misiles) y 50 (drones): de "implementado detrás de flag" a **activos**, con
> panel web pictográfico y el NPC jugándolos. Mismo patrón que cerró 47/46 v1.5.
- **Flags ON por default** (`strike_enabled`, `drones_enabled`), apagables por env. Frenos naturales:
  protección de novato (SDD 11), no se ataca a aliados, intra-planeta, tope de alojamiento
  (`ordnance`/`drone`), y el drenaje de energía (drones no son enjambre eterno gratis).
- **Panel web "🚀 Arsenal intra-planeta"** (`renderArsenal`, card colapsable; se oculta si ambos
  flags están off vía `catalog.features`): subpanel **Misiles** (inputs por tipo que tenés, objetivo,
  torretas rival → pre-cálculo `impactan/interceptados/⚔daño` con `/combat/strike/simulate`, botón
  🚀 Lanzar) y subpanel **Drones** (inputs, calculadora de duración 🔋⏳/🛡⏳/👁 con `/drones/simulate`,
  lanzar + escuadrones orbitando con ETA e intel y botón ⏹ retirar). Pictográfico (SDD 43), i18n es/en.
- **`/catalog`** ahora expone `features` (flags) + `costs` extra (`turret_intercept_power`/
  `turret_antiair_power`/`drone_tick_seconds`/`energy_regen_per_hour`) para las calculadoras del cliente.
- **NPC (`npc.py`):** investiga `rocketry`/`dronework` (si el flag está on), construye `launcher`/
  `drone_factory`, fabrica misiles/drones y **ablanda** una base enemiga del mismo planeta con una
  salva o un escuadrón de drones antes de la flota. Test `test_rule_brain_softens_with_a_missile_strike`.

## [1.99.0] - 2026-06-28

### 2026-06-28 — SDD 49 (misiles) + SDD 50 (drones): guerra intra-planeta, data-driven
> Dos vías de combate **paralelas a la flota**, ambas **intra-planeta** (no salen del planeta),
> **data-driven** y en el **grafo** (la IA arma la relación sola). Mecánicas deterministas +
> calculadoras puras + tests/e2e. **Flags OFF por default** (apagables/encendibles por env), como
> arrancaron SDD 47/46: el contenido carga (catálogo, grafo, árbol, asesor) pero la acción se
> habilita al prender el flag, tras revisar balance.

**SDD 49 — Lanzadera de misiles (`launcher`):**
- **Árbol tech (gate):** `rocketry → ballistics → nuclear_fission` (categoría `strike`).
- **Edificio `launcher`** (`requires_tech: rocketry`, `range: intra_planet`, aloja `ordnance`).
- **Misiles** (dominio `ordnance`, se alojan en la lanzadera): `sonic_missile` (power 60,
  intercept_cost 1 → enjambre satura), `cruise_missile` (160/3), `nuclear_missile` (600+ÁREA/8).
- **Intercepción determinista:** `turret` gana `intercept_power`; la capacidad antimisil = Σ de las
  torretas activas × defensa, se gasta sobre los misiles entrantes (los baratos primero); los que
  sobran IMPACTAN y **destruyen edificios** de la base (defensas primero; el nuclear, de área,
  también los no defensivos + deja **fallout** −producción). No saquea: **ablanda** una base.
- **API:** `POST /combat/strike`, `POST /combat/strike/simulate` (calculadora). `simulate_strike()`
  puro. Estado en `/players/me` (`strikes` en vuelo). Errores claros: sin tech, sin lanzadera,
  objetivo de otro planeta, sin stock.

**SDD 50 — Drones intra-planeta (`drone_factory`):**
- **Árbol tech (gate):** `dronework → drone_endurance` / `attack_drones` (categoría `drones`).
- **Edificio `drone_factory`** (`requires_tech: dronework`, aloja `drone`).
- **Drones** (dominio `drone`): espía `recon_drone`/`mk2`/`mk3` (hp/consumo/intel crecientes) +
  ataque `strike_drone`. Trade-off del pedido: **más durable ⇒ más consumo**.
- **Matemática lazy por timestamp:** un escuadrón ORBITA; cada tick las torretas (`antiair_power`)
  derriban drones (hp del escuadrón) y los vivos **drenan TU energía**; los espía dan **intel en
  vivo** (mejor que el snapshot de SDD 35); los de ataque castigan la base por tick. Muere sin
  energía o sin drones. `advance_drones()` se calcula al leer (como minería/energía), sin cron.
- **API:** `POST /drones/launch`, `POST /drones/{id}/recall`, `POST /drones/simulate`.
  `simulate_drones()` puro. Estado en `/players/me` (`drones` + `intel_live`).

**Transversal:**
- `content/{technologies,buildings,units}.yaml` extendidos; `registry` carga grupos `ordnance` y
  `drone`; `/catalog` y `/catalog/tree` los exponen (el modal 🌳 ya los muestra).
- **Grafo (SDD 1):** aristas `requires_tech`, `turret→intercepts→misil`, `turret→shoots_down→dron`;
  grounding `mech_missiles` y `mech_drones` (con números) → el asesor y el NPC pueden razonar sobre
  ellos. Mejora de recuperación: `retrieve` filtra **stopwords** de la query (textos largos ya no
  ganan por palabras de relleno).
- Modelos `StrikeMission` y `DroneSquadron` (migración `865940154e14`); la flota clásica
  (`/combat/attack`) rechaza misiles/drones (tienen su vía propia).
- **Tests:** `test_strike.py`, `test_drones.py` (puros) + e2e `test_missile_strike_e2e`,
  `test_strike_blocked_without_tech_e2e`, `test_drone_squadron_e2e`, `test_drones_die_without_energy_e2e`.
- **Pendiente (v1.5, como en 47/46):** prender flags tras balance, paneles web pictográficos
  (lanzar/calcular salva y duración de drones) y que el **NPC** use misiles/drones para ablandar.

## [1.98.0] - 2026-06-27

### 2026-06-27 — SDD 47/46 v1.5: minería y alojamiento PRENDIDOS (balance suave) + NPC los usa
> Cierre de SDD 47 (minería) y SDD 46 (alojamiento): pasan de "medido detrás de flags" a **activos**,
> con balance que **no rompe a los nuevos**, y el **NPC** juega con las nuevas reglas.
- **Flags ON por default** (apagables por env): `mining_staffing_enabled`, `storage_caps_enabled`,
  `housing_enforced`. Antes default OFF.
- **Balance suave (clave para no frustrar):**
  - `mining_staffing_floor=0.34` → una mina sin obreros igual rinde ~34% (no se zerea a quien recién
    empieza); los obreros la llevan de ahí a 1.0. Aplicado en `economy.mining_staffing` (lo usan
    `collect_mines` y `/players/me`).
  - `base_housing_per_domain=10` → cada dominio arranca con 10 plazas de **gracia** aunque no tengas el
    edificio → podés entrenar desde el inicio; ampliás construyendo. Nunca destruye unidades.
- **NPC (`npc.py`):** ahora **entrena obreros** para mantener las minas con staffing, **construye silos**
  cuando un mineral rebalsa, y **respeta el alojamiento** (no intenta entrenar sin plazas → no rompe su
  turno con `TrainingError`). Test `test_rule_brain_trains_worker_to_staff_mines`.
- Tests ajustados a la nueva realidad (formula pura con staffing off; e2e con piso/gracia 0 para probar
  la mecánica estricta). Suite verde.

### 2026-06-27 — Test: smoke de Chrome robusto (sin flake por sleep fijo)
- `test_all_panels_render_without_js_errors` flakeaba en CI ("el juego no se mostró"): esperaba `#game`
  con un `wait_for_timeout(1500)` fijo y, bajo carga, el boot tardaba más → falso negativo (frenó el
  promote de 1.97.0 pese a que el código estaba bien — verificado pasando local). Nuevo helper
  `_wait_shown` que **espera el selector** con timeout (10s) en vez de dormir un tiempo fijo.

## [1.97.0] - 2026-06-27

### 2026-06-27 — 🌳 Árbol/tabla calculado: `GET /catalog/tree` + modal web + "Explicar con IA"
- **Endpoint calculado (determinista):** `GET /catalog/tree?race=&planet=` (`depgraph.build_tree`)
  devuelve el **skill tree** (tecnologías con `requires`/`requires_tech`, efecto, costo YA resuelto a
  minerales de la raza) + **tablas de unidades** (dominio, edificio, tech, costo, stats,
  prerequisites) + edificios. Cacheado (Redis, TTL catálogo). Es la **misma verdad** que ya consume la
  IA por el grafo (`graph_documents`/`retrieve`) — ahora también estructurada para clientes.
- **Web:** botón **🌳 Árbol y tabla** (card "Tu imperio") abre una **ventana/modal** (como el detalle
  de planeta) con el árbol + tabla, con íconos (pictográfico). Botón **🧠 Explicar con IA** dentro del
  modal → usa el asesor (GPU/cloud/BYOK, SDD 9) para explicar qué conviene primero. i18n ES/EN.
- e2e: `test_catalog_tree_computed`. Cambiar balance sigue siendo **editar YAML** (sin código).

### 2026-06-27 — Diseño: SDD 49 (lanzadera de misiles) + SDD 50 (drones intra-planeta)
- **SDD 49 — Lanzadera de misiles** (`docs/sdd-missile-launcher.md`): edificio `launcher` + misiles
  **sónico → transatlántico → nuclear**, cada uno detrás de su tech (`rocketry → ballistics →
  nuclear_fission`); golpe **intra-planeta** con **intercepción determinista** por torretas (enjambre
  satura; el nuclear casi no se frena). Data-driven + grafo + UI pictográfica. Diseño, no implementado.
- **SDD 50 — Drones intra-planeta** (`docs/sdd-drones-intraplanet.md`): `drone_factory` + drones
  **espía** (3 tipos: durabilidad↑ ⇒ consumo↑) que **orbitan dando intel en tiempo real** mientras
  tengan energía (mueren al agotarla) y caen ante torretas (matemática de supervivencia §4), + drones
  de **ataque masivo**. Solo dentro del planeta (se construyen en cualquiera, no se envían fuera).
  Energía/duración calculable en el panel (pictográfico). Lazy por timestamp. Diseño, no implementado.

### 2026-06-27 — 📌 Pendientes / roadmap (estado de cierre, para retomar)
> Snapshot de lo que queda. La app está **viva** (1.96.1 con los bugfixes).
**Infra / CI:**
- **CD verde:** resuelto (RBAC completo + Opción B en clusterissuers + nodo descordonado). Validar que
  1.96.1 cierre el `promote-prod` en verde (en curso al cierre).
- **Kaniko en SD interno:** mitigado (scratch a PVC Longhorn-NVMe vía TMPDIR + PVC 20Gi auto-borrada).
  Queda *inherente* la extracción del rootfs en el overlay del nodo → fix profundo (follow-up): mover
  el data-dir de containerd a NVMe, **o** pasar a BuildKit con caché en PVC.
- **nodeSelector clavado a `srv-rk1-nvme-01`:** si ese nodo se cordonea/llena, el CD se traba. Relajar a
  un `nodeAffinity` sobre el pool `srv-rk1-nvme-01..04` (los 4 de 30GB; las Pi/super6c de 8GB no entran
  por el límite de 8Gi). Pendiente.
- **Argo UI sin logs de pasos terminados:** falta configurar un *artifact repository* (hay MinIO
  `loki-minio` en `monitoring`) + `archiveLogs: true`. Es infra compartida del ns `argo` → con criterio.
**SDD 47/46 (implementados v1, flags default OFF):**
- Prender `mining_staffing_enabled` / `storage_caps_enabled` / `housing_enforced` **tras balancear**
  (hoy off para no romper partidas).
- **NPC**: que use minería (equilibrar obreros/silos) y respete alojamiento en su build order.
- UI: el panel "📦 Economía / capacidad" ya está; falta pulido (tooltip/disable de botón por plaza).
- v2 alojamiento **por base/planeta** (hoy es agregado por jugador).
**SDD 48:** `Idempotency-Key` server-side (opcional, para botones de pago).
**Solo diseño (sin implementar):** SDD 5 (Telegram — bloqueado: falta token), 30 (runbook resiliencia),
31 (Postgres HA CNPG), 33 (hardening: no-root/NetworkPolicy/RBAC runtime), 28 §8 (virtual keys con
budget), 7/9 (load test real), **49 (lanzadera de misiles), 50 (drones intra-planeta)**.
**Bloqueadores para publicar:** secretos fuertes, email real, backup offsite cifrado + PITR, target de
hosting, bot Telegram (SDD 5).
**Decidido (no tocar):** la PV vieja de Postgres `pvc-b23ba706…` (Released/Retain, pre-Longhorn) **se
deja** (respaldo; borrar el objeto Retain ni libera disco).

## [1.96.1] - 2026-06-27

### 2026-06-27 — Fix: loadActiveEvents pegaba a un path 404 (lo atajó el gate de Chrome)
- El fetch de eventos activos usaba `GET /api/v1/events` (no existe → 404) en vez de
  `GET /api/v1/events/active`. Generaba 2 errores de consola → el gate `e2e-chrome`
  (`test_all_panels_render_without_js_errors`) **falló y frenó el promote** (el 1.96.0 buggeado NO
  llegó a prod). Además rompía el propio Fix del descuento de evento (gBuildMult nunca cargaba).
  Corregido el path.
- **CI (scratch de Kaniko a PVC, no al SD/eMMC del nodo):** el workflow ya usaba una PVC Longhorn-NVMe
  efímera (auto-borrada al terminar); ahora Kaniko manda su `TMPDIR` a esa PVC y se agrandó a 20Gi →
  el grueso del scratch va a NVMe-Longhorn, no al disco interno del nodo. El `ephemeral-storage` del
  nodo (solo el rootfs/overlay de la extracción) se acotó a 2–6Gi. Nota: la extracción del rootfs de
  Kaniko es inherentemente en el overlay del nodo; eliminarla del todo requeriría mover el data-dir de
  containerd a NVMe o usar BuildKit con caché en PVC (follow-up).

## [1.96.0] - 2026-06-27

### 2026-06-27 — Fix UX: el pre-cálculo de acciones ahora coincide con lo que cobra el server
> Reportes del usuario: "compro silicio, imperio dice que tengo más pero en acciones figura menos y no
> me deja", "el research parece global", "los eventos muestran rebaja de construcción pero no sé si se
> aplica". Todo era lo mismo: **la UI mostraba algo distinto a lo que el server hace**.
- **Stock por planeta (SDD 42):** el afford de construir/entrenar usaba el **agregado** (suma de todos
  los planetas) para el planeta natal, mientras el server valida **por planeta**. Ahora la UI usa
  siempre el stock **del planeta de la base** (incluido el natal) → lo que ves es lo que se cobra. El
  material que comprás en el hub llega a tu planeta natal; para usarlo en una colonia hay que
  transportarlo (el mensaje ya dice "tenés X ahí").
- **Research:** se paga con el material del planeta **natal** ("se investiga en casa") — ya era por
  planeta, pero la UI **no mostraba el costo**; ahora cada tech muestra costo + ⚡ + si alcanza (con el
  stock natal). 
- **Eventos (rebaja de construcción):** el server ya aplicaba el descuento (`build_cost_multiplier`),
  pero la UI mostraba el precio **sin** rebaja. Ahora el costo de construir refleja el evento activo y
  muestra "🏗−X% evento" (se trae de `GET /events`).

## [1.95.0] - 2026-06-27

### 2026-06-27 — UI de SDD 47/46: panel "📦 Economía / capacidad"
- Nueva card en el dashboard que pinta lo que la API ya exponía: **staffing de minería** (👷 obreros
  disponibles/requeridos + "minas al X%"), **almacenamiento** (🛢 barra stock/cap por planeta/mineral,
  **roja si rebalsa**) y **alojamiento** (🏠 plazas ocupadas/capacidad por dominio). Local, sin red
  (entra en el ciclo de 4s). i18n ES/EN. Con los flags off muestra al menos las plazas de alojamiento;
  staffing/almacén aparecen al prender `mining_staffing_enabled`/`storage_caps_enabled`.

### 2026-06-27 — Fix infra: CD helm-promote "failed" era RBAC (no el timeout arm)
- **Causa real** del `promote-prod` que marcaba *failed* desde 1.92.0 (mi hipótesis previa del
  "arranque arm lento" estaba equivocada): el SA del CD `og-deployer` no tenía permiso para los CRDs
  que el chart administra además del Deployment, y `helm upgrade --wait` los **GETea** en el 3-way
  merge → `... is forbidden`. El Deployment igual se aplicaba (por eso el pod quedaba en la versión
  nueva pero la release figuraba *failed*). Las releases viejas "deployed" se hacían a mano.
- **Fix RBAC** (`deploy/build/cicd-rbac.yaml`, aplicado al cluster + verificado con `auth can-i`):
  Role `og-deployer` (ns online-game) + `autoscaling/hpa`, `policy/pdb`,
  `monitoring.coreos.com/{prometheusrules,servicemonitors}`. Nuevo Role `og-deployer-gateway`
  (ns gateway): `cert-manager/certificates` + `gateway.networking/{gateways,httproutes}` (CRUD) +
  `rbac/{roles,rolebindings}` **solo lectura** (sin escalada). ClusterIssuers **RO** cluster-wide.
- **Evicción de pods de test:** los gates `e2e-api`/`e2e-chrome` tenían `ephemeral-storage` request 0
  → BestEffort → primeros en caer si el nodo de build entra en **DiskPressure** (agravado por builds
  Kaniko concurrentes de otro proyecto en el mismo nodo). Ahora declaran request 1Gi / limit 2Gi.
- **Pendiente (ops, decisión del usuario):** el nodo de build `srv-rk1-nvme-01` quedó con
  `DiskPressure=True`; limpiar caché de imágenes / workflows viejos para que el CD cierre verde. La
  app 1.94.0 **ya está viva** (corre en otro nodo, sana); el promote verde es cosmético.

### 2026-06-27 — 📌 Estado de SDDs + qué sigue (snapshot)
> 48 SDDs (`docs/sdd-*.md`). Casi todos implementados con código+tests; quedan pocos en diseño.
- **Implementados (código + tests + e2e):** SDD 1–4, 6–29, 32, 34–48 (núcleo del juego, deploy/CI,
  observabilidad, mercado, espionaje, NPCs, asistente, paneles, minería/alojamiento/concurrencia).
- **Solo diseño (sin implementar todavía):**
  - **SDD 5** bot de Telegram — ⛔ bloqueado: necesita `TELEGRAM_BOT_TOKEN` real.
  - **SDD 30** runbook de resiliencia / apagar GPU.
  - **SDD 31** Postgres HA con CNPG.
  - **SDD 33** hardening (pods no-root, NetworkPolicy, RBAC del runtime).
  - **SDD 28 §8** virtual keys de LiteLLM con budget por jugador (diseñado; recién con monetización).
  - **SDD 7/9** load test / benchmark real de saturación (parcial).
- **Qué sigue (sugerido, por valor):**
  1. **UI de 47/46**: barras stock/cap + staffing + plazas por dominio (hoy la API/IA ya lo exponen).
  2. **NPC** que use minería (equilibrar obreros/silos) y alojamiento (no entrenar sin plazas).
  3. **Prender flags** `mining_staffing_enabled`/`storage_caps_enabled`/`housing_enforced` tras balancear.
  4. **SDD 33 hardening** (camino a publicar) + bloqueadores de publicación (secretos fuertes, email
     real, backup offsite cifrado + PITR, target de hosting, **SDD 5 Telegram**).

## [1.94.0] - 2026-06-27

### 2026-06-27 — SDD 47 v1: minería con trabajadores (staffing) + almacenamiento (silos)
> Detrás de flags `mining_staffing_enabled` / `storage_caps_enabled`, **default OFF** → comportamiento
> idéntico al actual hasta balancear. Cierra el hueco "el trabajador no hacía nada".
- **Staffing (trabajadores ↔ minas):** cada mina pide `worker_slots` (5) obreros para rendir al 100%;
  `staffing = clamp(Σ worker·mining_power / Σ worker_slots, 0, 1)` multiplica la producción de TODAS las
  minas. Más minas con los mismos obreros ⇒ cada una rinde menos; sobre-contratar no pasa de 1.0.
- **Almacenamiento (silos):** cada mineral tiene un tope por planeta = base + HQ (`storage`) + cada mina
  (`storage`) + silos. Edificio nuevo **`silo`** (category `storage`): guarda **un solo mineral**
  (elegido al construir, como la mina). Al llenarse, lo producido de más **se desperdicia** (overflow);
  nunca borra stock existente, solo frena producción nueva.
- **Data-driven:** `worker_slots`/`storage` en mina+HQ, `silo` (+`storage_capacity`), `mining_power` en
  worker, todo en YAML → expuesto en `/catalog`. Funciones puras `staffing_ratio`/`apply_overflow`/
  `storage_caps_by_planet` (`production.py`/`economy.py`) con tests (`tests/test_mining.py`).
- **Exposición:** `/players/me` agrega `mining {staffing, available_workers, required_workers}` y
  `storage {planeta: {mineral: {cap, stock, free, overflowing}}}`.
- **IA:** aristas worker→mina (`operates`) y silo→mineral (`stores`) + grounding `mech_mining` en el
  grafo (`depgraph.py`) → el asistente/NPC saben equilibrar obreros y construir silos.
- **e2e:** `test_mining_staffing_and_storage_e2e`. **Pendiente:** UI (barras stock/cap + staffing), NPC
  que equilibra, balance antes de prender los flags. Diseño: `docs/sdd-mining-workers-storage.md`.

### 2026-06-27 — SDD 46 v1: alojamiento/capacidad de unidades (grafo unidad ↔ edificio)
> Enforce detrás de flag `housing_enforced`, **default OFF** → solo mide/expone hasta prenderlo.
- **Concepto:** cada unidad pertenece a un **dominio** (`domain`) y ocupa `housing_size` plazas; cada
  edificio provee plazas (`houses: {dominio: N}`). Capacidad = Σ plazas de edificios activos; sin plazas
  libres no podés entrenar esa unidad. La matriz (personnel→HQ/lab, infantry→cuartel, ground→fábrica,
  air/space→hangar, naval→**puerto**) es la fuente de verdad compartida humanos ↔ IA.
- **Edificio nuevo `port`** (naval) para alojar barcos. Atributos `domain`/`housing_size`/`houses` en
  YAML → `/catalog`.
- **Servicio puro** `app/services/housing.py` (capacity/occupancy/`can_train`/`housing_matrix`) con
  tests (`tests/test_housing.py`); enforce en `start_training` con mensaje accionable i18n; bloque
  `housing {dominio: {capacity, occupancy, free}}` en `/players/me` (las unidades en cola reservan plaza).
- **IA:** aristas unidad→edificio (`housed_in`/`houses`) + grounding `mech_housing` en el grafo.
- **e2e:** `test_unit_housing_capacity_enforced_e2e`. **Pendiente:** UI (barras de plazas), NPC respeta
  capacidad, v2 por base/planeta. Diseño: `docs/sdd-unit-housing-capacity.md`.

### 2026-06-27 — SDD 48: indicador "⏳ procesando…" in-flight (cierra el front)
- Mientras hay mutaciones en cola/vuelo (FIFO de `api()`, v1.93.0), la web muestra un indicador
  **⏳** abajo a la derecha (con contador si hay >1) → feedback honesto al spamear, sin deshabilitar
  todo. Completa el §4.1 del diseño. Idempotency-Key (§4.2) queda opcional para botones de pago.

## [1.93.0] - 2026-06-27

### 2026-06-27 — SDD 48 v1: no saturar la API al spamear comprar/construir
- **Bug:** clickear muchas veces "comprar/construir/entrenar" muy rápido daba **409 "ya tenés una
  acción en curso"** o, en dev/SQLite (sin Redis), **500 internal error** (dos requests del mismo
  jugador corriendo en paralelo → "database is locked").
- **Frontend (cola FIFO del cliente):** `api()` ahora **serializa las llamadas mutantes** (no-GET) en
  una cola → nunca hay dos en vuelo, así no se generan 409 al spamear. Cada acción se valida **al
  enviarse** (no diferida): si una falla (p.ej. sin material) rechaza con su toast y la cola sigue con
  las demás. Los GET (lecturas/refresh) quedan en paralelo.
- **Backend (lock in-process de respaldo):** sin Redis, `player_lock` ahora **serializa in-process**
  por jugador (antes era no-op) → el 2º request ve el lock tomado (409, no 500). Con Redis sigue siendo
  el lock distribuido. Tests: `test_player_lock_without_redis_serializes_in_process`.
- **CI:** subido el `--wait`/timeout del `helm upgrade` en el pipeline (8m→15m, rollout 300s→600s)
  porque el arranque en arm (pull de imagen + migraciones) excedía el timeout y marcaba el deploy
  "failed" aunque el rollout completaba. Diseño completo en `docs/sdd-action-concurrency-queue.md`.

### 2026-06-27 — 📌 Pendientes / roadmap (para retomar)
> Estado al cierre 2026-06-27. Lo de arriba (panel de batallas, SDD 48, SDD 35 cerrado, SDD 28
> verificado) ya está. Lo que sigue, por prioridad:
- **A implementar (diseño listo):** **SDD 47** minería (staffing de trabajadores + silos/almacén —
  el `worker` hoy no hace nada), **SDD 46** alojamiento de unidades (topes por edificio), **SDD 48
  resto** (idempotency-key opcional; deshabilitar botón con spinner por acción), **SDD 28 §8** virtual
  keys LiteLLM con budget por jugador (a futuro/monetización).
- **Diseño-only sin implementar:** SDD 30 (runbook resiliencia), SDD 31 (Postgres HA CNPG), SDD 33
  (hardening: no-root/NetworkPolicy/RBAC), SDD 7/9 (load test real).
- **Infra/CI:** revisar por qué el arranque en arm tarda (pull + migraciones) y deja el `helm`
  "failed" pese a rollout OK — validar que el timeout 15m alcance; release helm quedó en estado
  failed rev 134 (el próximo upgrade exitoso lo limpia).
- **Bloqueadores para publicar:** secretos fuertes, email real, backup offsite cifrado + PITR, target
  de hosting, **bot Telegram (SDD 5)**.
- **Decisión del usuario (no autónoma):** borrar (o no) el PV viejo de Postgres `pvc-b23ba706-…`
  (Released, pre-Longhorn, destructivo).

## [1.92.0] - 2026-06-27

### 2026-06-27 — Panel de batallas: quién atacó a quién y quién ganó (general + admin)
- **Panel general (todos los jugadores):** en *Reportes de combate* se agregó **🌐 Batallas de todos**
  — el historial global de combates, **agrupado por atacante**, con **ruta origen→destino** (planeta
  del atacante → base atacada) y el **ganador**. Antes solo veías *tus* batallas.
- **Panel de admin:** nueva card **⚔ Batallas — quién ganó** con el mismo feed global (atacante vs
  defensor, ruta, ganador, botín).
- **Privacidad (SDD 35):** el feed **NO expone unidades ni bajas** — la composición/fuerza de un
  ejército sigue siendo intel que se consigue **espiando**, no mirando el feed. El espionaje tampoco
  aparece (usa otra tabla). Tus *propios* reportes (`/combat/reports`) sí mantienen el detalle.
- API: `GET /combat/battles` (público) y `GET /admin/battles` (admin), ambos vía
  `app/services/battles.py:battles_feed` (deriva de `CombatLog`, sin storage nuevo). e2e:
  `test_battles_feed_global_and_admin_no_unit_info` (incluye que NO haya datos de unidades).

### 2026-06-27 — Diseño: SDD 46 (alojamiento de unidades) + SDD 47 (minería/trabajadores/silos)
- **SDD 46 — Alojamiento y capacidad de unidades** (`docs/sdd-unit-housing-capacity.md`): grafo
  data-driven unidad→dominio→edificio (worker→base, soldado→cuartel, avión→hangar, barco→puerto…),
  tope de plazas por dominio (`houses` en edificios, `domain`/`housing_size` en unidades), enforcement
  en entrenamiento, exposición en `/catalog`+`/players/me` y en el grafo de la IA. Diseño, no implementado.
- **SDD 47 — Minería: producción, trabajadores y almacenamiento** (`docs/sdd-mining-workers-storage.md`):
  documenta la fórmula de producción (`horas·base_output·abundancia·mult`), diseña **staffing** de
  trabajadores (más minas con pocos obreros ⇒ cada una rinde menos), y **almacenamiento con silos** (tope
  por mineral; overflow se desperdicia; silo guarda un solo mineral). Todo objeto data-driven + en el
  grafo de la IA. Diseño, no implementado.
- Los builds Kaniko extraen las capas al **disco efímero del nodo** (no la PVC ni la DB); en el
  pipeline de CD corren **dos en paralelo** (imagen del juego + imagen de test) sobre el mismo nodo
  pineado, y eso llenaba el disco → el build se **evictaba a mitad** ("node was low on resource:
  ephemeral-storage", pasó con 1.90.0). Ahora cada container Kaniko declara
  `ephemeral-storage` (request 4Gi / limit 8Gi) en `deploy/build/online-game-cicd.yaml` y
  `online-game-kaniko.yaml`: el scheduler reserva el piso y un build desbocado se **autoexpulsa**
  (falla limpio) en vez de presionar al nodo y evictar vecinos. Sin cambio de comportamiento del
  juego (solo infra de build).

### 2026-06-26 — Fix: el panel de mercado/hub se refresca al instante tras comprar
- Bug: al comprar mineral/energía (mercado, hub, mercado negro, transporte) el **stock mostrado en el
  panel no se actualizaba** hasta el ciclo de 20s (había que refrescar la página). Las funciones de
  comercio llamaban `refresh()` (estado) pero no `refreshPanels()` (mercado/hub se cargan ahí). Ahora
  hacen `await refresh(); refreshPanels()` → el panel refleja el stock nuevo enseguida.

## [1.90.0] - 2026-06-26

### 2026-06-26 — Intel → Calculadora de combate (SDD 35 + 34)
- En el bloque de **intel** de una colonia enemiga (modal de planeta) hay un botón **🧮 "a la
  calculadora"** que abre la Calculadora de combate **precargando el lado defensor** desde lo que tu
  espionaje reveló: unidades exactas si la profundidad ≥0.8, torretas si ≥0.6 (lo no revelado queda
  en 0). Así calculás un ataque realista contra un objetivo concreto sin tipear a mano.

## [1.89.0] - 2026-06-26

### 2026-06-26 — NPC que aprende de cada batalla (SDD 29 §3.7 reflexión post-batalla)
- Tras cada combate, los NPC involucrados **reflexionan** (determinista, **sin gastar GPU**): anotan
  el resultado y **ajustan su postura** — perdió defendiendo→`defensive`, falló atacando→`expand`,
  ganó atacando→`raid`, ganó defendiendo→mantiene. Guarda `last_battle` y registra `npc_reflection`
  en el journal. Así la IA **aprende del resultado** sin costo de LLM por batalla.

### 2026-06-26 — Catch-up del recién llegado escalado por días de temporada (SDD 25)
- El nivelado al P40 de los pares ahora escala **explícito por antigüedad de la temporada**: entrar
  el día 0 da ~0 (nadie está nivelado aún), entrar tarde nivela al P40 completo (full a los
  `catchup_full_after_days`=7d). `=0` vuelve al comportamiento previo (top-up directo).

### 2026-06-26 — Métrica propia de uso de LLM por tipo (SDD 28 §3.5)
- `game_llm_calls_total{kind,status}` (kind=advisor|npc) en `llm_chat` → ver en las métricas del
  juego cuánto usa el LLM el asistente vs los NPC, sin alta cardinalidad. La atribución por jugador
  (`end_user` = `player:`/`npc:`) ya viajaba a LiteLLM. (DCGM-exporter + dashboards = follow-up infra.)

## [1.88.0] - 2026-06-26

### 2026-06-26 — Calculadora de combate web + asistente aterrizado (SDD 34 completo)
- **Calculadora de combate 🧮** (panel nuevo): poné unidades del atacante y del defensor (+ torretas)
  y te dice **en vivo si ganás y cuánto pierde cada lado** — usa `POST /combat/simulate`, el **mismo
  cálculo determinista** que el combate real, sin gastar nada. Picto-aware (íconos de unidad).
- **Asistente IA sin alucinar:** nuevo grounding `mech_combat_planning` → el modelo usa
  `/combat/plan` (estima la defensa desde tu intel) y `/combat/simulate` en vez de inventar números,
  con la regla práctica "llevá 2-3× la defensa". Junto al `mech_combat` que ya tenía la fórmula.
- Cierra los follow-ups del SDD 34 (la base —`/combat/simulate`, `/combat/plan`, botón planear— ya
  estaba); el ROADMAP estaba desactualizado marcándolo como "diseño".

## [1.87.0] - 2026-06-26

### 2026-06-26 — Fix: la planta de energía ahora SÍ sube el tope (y la regen) de energía
- **Bug:** el edificio "Planta de energía" prometía "aumenta el tope/regen" pero **no hacía nada**:
  `energy_max` era una constante fija (240) y la regen solo dependía del planeta. Por más plantas que
  construyeras, tu energía nunca pasaba de 240.
- **Ahora:** cada **planta de energía ACTIVA** sube el **tope** (+`energy_max_per_power_plant`=120) y
  la **regen** (+`energy_regen_per_power_plant`=5/h, escalada por la física del planeta). El tope
  efectivo = 240 + plantas×120. El conteo de plantas activas se cachea en el jugador
  (`active_power_plants`, migración aditiva) y se recomputa en cada acción/lectura (lazy-state).
- Aplicado en TODOS los cobros/topes de energía (construir, entrenar, investigar, atacar, expedición,
  espiar, mercado, hub, colonizar, catch-up, asistente) y en el `energy_max` que ve la UI.
- Tests: `test_physics.py` (puros + end-to-end construir→activar→sube el tope).

## [1.86.0] - 2026-06-26

### 2026-06-26 — Jugar sin leer (SDD 43 COMPLETO): TTS de servidor (espeak-ng)
- **`GET /api/v1/tts?text=&lang=`**: sintetiza el texto con **espeak-ng** y devuelve un WAV. Es el
  **fallback** del modo pictográfico para navegadores **sin voces** (típico Chromium/Linux), donde el
  `speechSynthesis` del navegador no suena. El front usa el navegador si tiene voces y, si no, pide
  este audio y lo reproduce. Texto acotado (600), pasado por stdin a un proceso sin shell.
- **Imagen:** `espeak-ng` agregado al Dockerfile (~5MB). e2e `test_tts_server_fallback` (400 sin
  texto; audio/wav con cabecera RIFF; 503 si el binario no está).
- Con esto **SDD 43 queda completo**: todos los paneles jugables hablan el modo y la lectura en voz
  alta funciona en cualquier navegador.

## [1.85.0] - 2026-06-26

### 2026-06-26 — Jugar sin leer (SDD 43): último lote — cobertura completa de paneles
- **Notificaciones:** cada aviso con un **ícono de tipo** (⚔ ataque, 🛡 defensa, 🔬 research, 🏪 mercado,
  🛰 expedición, 🤝 alianza, 🏗 construcción, 📣 novedad) en vez del texto del tipo; el cuerpo sigue
  siendo texto y se lee con TTS al tocar el ícono.
- **Ranking y Temporada:** los 3 primeros con **medalla** (🥇🥈🥉) en lugar del número.
- **Guía = leyenda del modo:** en pictomode arranca con el **diccionario ícono↔cosa** (minerales con
  su letra, edificios, unidades, planetas, y los símbolos de estado ⚡⏱✓❌🔒) — tocás y escuchás.
- **Atacar, eventos y meta** ya hablaban el modo (selección de fuerza con ícono+⚔, eventos como
  íconos, meta con unidades como íconos); quedan confirmados en la cobertura.
- Con esto **SDD 43 cubre todos los paneles jugables**. Único pendiente: fallback TTS de servidor.

## [1.84.0] - 2026-06-26

### 2026-06-26 — Jugar sin leer (SDD 43): investigación, colas, bases y galaxias pictográficos
- **Investigación:** cada tecnología como **ícono** (×magnitud); botón investigar 🔬; **🔒 + ícono
  del prerequisito** cuando falta la tech previa; listo = ✓.
- **Colas:** cada ítem (entrenar/expedición/investigación/transporte/espía/flota) con su **ícono** +
  ⏱; recall como 🔙; transporte con chips de mineral + ícono de planeta origen→destino.
- **Bases:** edificios como íconos (mineral de la mina como chip), stock del planeta como chips,
  planeta como ícono; selector de base con ícono de planeta.
- **Galaxias:** planetas del mapa como ícono.
- **Invariante intacto:** con el modo apagado, todo igual que antes (cubierto por el chrome smoke que
  re-renderiza TODOS los paneles en pictomode sin errores de JS).

## [1.83.0] - 2026-06-26

### 2026-06-26 — Jugar sin leer (SDD 43): mercado, hub, transporte y alianzas pictográficos
- **Mercado y Hub:** botones **comprar/vender/trocar** como íconos (🛒/💰/🔄) en pictomode; precios
  con 🛒/💰; selectores de planeta, mineral, unidad de escolta con su **ícono**; estimaciones del
  mercado negro y disponibilidad de transporte con chips de mineral + ícono de planeta.
- **Transportes en tránsito:** origen/destino se muestran con el **ícono del planeta/luna** (antes
  solo el nombre en texto).
- **Alianzas:** crear/unirse/salir/transferir como botones-ícono; minerales del trueque con ícono.
- **Datos:** `icon:` agregado a **planetas** (`content/planets.yaml`) y **lunas** (`content/gods.yaml`),
  expuesto sin localizar por `/catalog` (aditivo, sin migraciones). e2e en `test_catalog_pictographic_icons`.
- **Invariante intacto:** con el modo apagado, todos estos paneles se ven exactamente como antes.
- Toggle global/por-panel ahora refresca también los paneles secundarios (mercado/hub) al instante.
- **Pendiente** (SDD 43): resto de paneles (atacar/combate/investigación/bases/colas/galaxias/etc.).

### 2026-06-26 — Admin: el embed de Grafana queda como link (no iframe)
- El iframe cross-domain de Grafana no funciona en Firefox (X-Frame-Options + aislamiento de cookies
  de terceros). Se revirtió en infra-ai el `allow_embedding`/`cookie_samesite=none` (rompía el login
  de Grafana). La consola de admin usa el **link "📊 Ver en Grafana"** (configurable por
  `GRAFANA_NPC_DASHBOARD_URL`). El iframe se reconsiderará cuando Grafana viva bajo el mismo dominio.

## [1.82.0] - 2026-06-26

### 2026-06-26 — Fix: requisitos de unidades por planeta (entrenar en colonias)
- **El research es global** (por jugador): si lo investigaste en tu planeta origen, ya vale para
  TODAS tus colonias. Lo que bloquea entrenar en una colonia es el **edificio requerido en ESA base**
  (ej. Fábrica/Cuartel), no el research.
- **Front:** el menú de **Entrenar** ahora refleja la **base seleccionada** — el 🔒 (edificio/tech
  faltante) y la afford (mineral del planeta) se calculan para la **colonia** elegida, no para la base
  origen. Antes mostraba "buildable" si tenías el edificio en cualquier base y recién al hacer click
  el server lo rechazaba. Cambiar de base ahora también refresca el costo de entrenamiento, y muestra
  `📍 <planeta>` cuando entrenás fuera del mundo natal.
- **Backend:** las **restricciones físicas** (atmósfera/agua) se evaluaban en el planeta de **origen**;
  ahora se evalúan en el planeta de la **base** donde entrenás (un barco pide agua de la colonia, no
  de tu casa). Test `test_physical_restriction_checks_colony_planet_not_home`.

## [1.81.0] - 2026-06-26

### 2026-06-26 — Admin: ver el dashboard de Grafana DENTRO de la consola (SDD 19 §9.3)
- **`GET /admin/dashboards`** (admin-gated, data-driven): devuelve la URL del dashboard **NPC AI**
  solo si se configuró `GRAFANA_NPC_DASHBOARD_URL` (helm `grafana.npcDashboardUrl`). La **consola de
  admin** muestra entonces un link **"📊 Ver en Grafana"** + un **iframe colapsable** con el
  dashboard, junto a la card "🤖 NPC — cómo juega la IA".
- **Sin configurar = no se muestra nada** (invariante: cero cambios de UI). El iframe **no expone
  Grafana anónimo**: carga si Grafana tiene `allow_embedding=true` y el admin ya tiene sesión de
  Grafana en el navegador. URL recomendada con `?kiosk` (embed limpio).
- e2e `test_admin_dashboards_e2e` (403 no-admin · `{}` sin configurar · `{npc_ai:url}` con config).
- **Infra pendiente (opcional):** habilitar `allow_embedding=true` en Grafana (kube-prometheus-stack)
  para que el iframe cargue; el link "Ver en Grafana" funciona igual sin eso.

## [1.80.0] - 2026-06-26

### 2026-06-26 — Docs: IA del juego documentada en la página tech + qué queda pendiente
- **Página `/tech`**: nuevas cards de la inteligencia agregada — NPC estratega (lee grafo + métricas
  + scoreboard y decide como un jugador, solo jugadas pagables), **aprende de sus errores**
  (memoriza fallos), y **GPU local vs nube medido** (panel admin 🧠 % + Grafana). Modelo local
  actualizado a **qwen2.5:7b**.
- **PENDIENTE (próximo):** terminar **"jugar sin leer" (SDD 43, modo pictográfico)** — falta llevar
  los íconos/grilla al resto de paneles (mercado/hub/transporte/alianzas) y pulir; la base (F1 + F2
  parcial + TTS) ya está. Follow-ups de IA: orquestar el tick por **Argo** (SDD 19 §9.5, un NPC a la
  vez), y publicar `game_npc_*` por **Pushgateway** ya hecho (la card admin es DB-backed igual).

## [1.79.0] - 2026-06-26

### 2026-06-26 — NPC sin ahogo de energía + no atacar sin energía (más jugadas por LLM)
- **#1 Energía NPC:** los NPC regeneran energía ×`npc_energy_regen_mult` (default 4) → dejan de
  quedar 'ahogados' (~6 de energía con todo costando ≥10) y pueden jugar de verdad por LLM en vez de
  caer a fallback por energía. No afecta a los jugadores humanos.
- **#2 Atacar factible:** el estado del NPC trae `can_attack` (¿alcanza la energía de ataque?) y el
  prompt solo permite `attack` si es true → mata el fallback "Energía insuficiente para atacar".
- Las métricas (panel admin 🧠 % + dashboard) deberían mostrar subir el `llm_rate` y bajar
  `fallback_reason=energy`.

## [1.78.0] - 2026-06-26

### 2026-06-26 — IA: pasarle al modelo SOLO las jugadas pagables (menos fallback)
- Refuerzo de la afinación: `_npc_state` ahora **filtra** `build_options`/`train_options` a **solo lo
  pagable ahora** (el modelo no puede ni elegir lo impagable). Las métricas en vivo mostraron que el
  modelo de **nube ya jugaba por LLM** pero el **chico de GPU** ignoraba el flag `affordable` y caía
  por energía → este filtro lo corrige también.

## [1.77.0] - 2026-06-26

### 2026-06-26 — Afinar la IA (jugar lo que puede pagar) + métrica "¿aprendió?" en el admin
- **IA afinada:** el estado que ve el NPC marca cada opción con **`affordable`** (puede pagar
  minerales+energía y tiene el edificio requerido) y el prompt le exige elegir **solo affordable** y
  no repetir jugadas fallidas → menos `fallback` por "sin energía", más jugadas aplicadas.
- **¿Aprendió? (sin Grafana):** cada decisión se registra en el journal (`npc_decision`); el panel
  admin "🤖 NPC" ahora muestra por NPC **🧠 % de jugadas aplicadas** (`llm_rate`), el conteo
  `llm/total` y los **motivos de fallback** (energy/infeasible/parse). Sube el % y baja "energy" =
  la IA está aprendiendo. `/admin/npc-stats.decisions`.
- Grafana: panel `game_npc_fallback_reason_total{reason}` ("¿Aprende?"). SDD 19 §9.1.quater.

## [1.76.0] - 2026-06-26

## [1.75.0] - 2026-06-26

## [1.74.0] - 2026-06-26

### 2026-06-26 — Métricas NPC claras (Grafana comentado) + la NPC aprende de sus fallos
- **Dashboard "NPC AI" reescrito con lenguaje claro + comentarios**: panel de texto-glosario arriba,
  títulos en castellano y `description` (tooltip "i") en cada panel. Aclara la confusión: **la métrica
  "usó GPU y la jugada salió bien" es `game_npc_decisions_total{backend="gpu",outcome="llm"}`**; el
  `fallback` significa que **sí se usó el modelo** pero su jugada no se pudo aplicar (no que no usó GPU).
  Panel "¿juega bien?" = `llm/(llm+fallback)` por backend.
- **Aprendizaje:** cuando una jugada del LLM falla, la NPC la **memoriza con el motivo**; el próximo
  prompt lo trae en `recent_actions` → el modelo evita repetir la jugada inviable (ej. construir sin
  energía). SDD 19 §9.1.bis (glosario) + §9.1.ter (aprendizaje).

### 2026-06-26 — NPC: loguear por qué cae a reglas (antes era silencioso)
- `LlmBrain.act` ahora **loguea un warning** con el motivo cuando una decisión LLM falla y cae a
  reglas (tipo de excepción + mensaje, NPC y backend). Antes el fallback era silencioso → no se sabía
  por qué la IA no jugaba por LLM. Lo destapó la Pushgateway: se vio que los NPC estaban 100% en
  `fallback`; este log permite diagnosticar la causa (JSON inválido del modelo, acción inviable, etc.).

### 2026-06-26 — Docs: cómo decide el NPC (rules vs llm, modelo, GPU vs nube)
- SDD 29 §2.bis: explicación clara del cerebro del NPC — `rules` (determinista, sin GPU) vs `llm`
  (razona sobre estado/scoreboard/meta; cae a reglas si falla), qué modelo usa cada NPC
  (`npc_llm_model` GPU local vs `npc_cloud_model` nube por `npc_cloud_username`) y cuándo se usa la
  GPU. Para tener documentado cómo funciona.

### 2026-06-26 — Métricas del tick/NPC visibles en Grafana (Pushgateway)
- El **tick** (CronJob `galaxy-tick`) es un pod efímero no-scrapeable → sus métricas (`game_npc_*`,
  `game_tick_*`) no llegaban a Prometheus. Ahora `worker.tick()` **empuja** sus métricas a una
  **Pushgateway** (`PUSHGATEWAY_URL`, p.ej. `http://pushgateway.monitoring:9091`), de donde
  kube-prometheus-stack las scrapea → el dashboard **NPC AI** (incl. GPU vs nube) se llena solo.
- Infra (repo `infra-ai`): nuevo rol **`install-pushgateway`** (Pushgateway en ns `monitoring` +
  ServiceMonitor con `honorLabels`, label del release). Cableado en `bootstrap.yml`
  (`--tags pushgateway`). SDD 19 §7.quater marcado **RESUELTO**.

## [1.73.0] - 2026-06-26

## [1.72.0] - 2026-06-26

### 2026-06-26 — NPC AI observable: panel en admin + dashboard Grafana (SDD 19 §9)
- **En el panel de ADMIN** (sin Grafana): nueva card "🤖 NPC — cómo juega la IA" con un snapshot por
  NPC — score, postura, **mezcla de acciones** (del journal), **récord de combate** y **últimas
  jugadas**. Endpoint `GET /admin/npc-stats` (admin-gated, e2e).
- **Dashboard Grafana** `Online Galaxy War — NPC AI` (`deploy/helm/dashboards/npc-ai.json`):
  decisiones LLM vs reglas, **% por LLM** (confiabilidad de la IA), mezcla de jugadas, latencia
  p50/p95 y llamadas ok/error. Se importa solo con el chart (configmap opt-in).
- SDD 19 ampliado (§9): qué métricas de NPC hay, las 3 vistas (Prometheus/Grafana/admin), cuándo se
  usa la GPU, y el follow-up de orquestar los turnos de NPC con Argo (de a uno, mejor GPU/calidad).
- **Comparar GPU local vs nube por NPC:** seteando `npc_cloud_username`, ese NPC juega con un modelo
  de **nube** (`npc_cloud_model`) y el resto con la **GPU local** → se compara quién juega mejor
  (score/win-rate en `/admin/npc-stats`, con `backend`/`model`) y quién decide mejor (panel "GPU vs
  Nube" en el dashboard; `game_npc_decisions_total{backend}`). Helper `npc_llm_choice`.

## [1.71.0] - 2026-06-26

## [1.70.0] - 2026-06-26

### 2026-06-26 — Métricas de NPC: entender cómo juega la IA y si mejora
- Nuevos contadores Prometheus: **`game_npc_actions_total{action,brain}`** (qué hace cada turno:
  build/train/attack/research/colonize/idle…) y **`game_npc_decisions_total{outcome}`** con
  `outcome=llm` (el LLM razonó la jugada) vs `fallback` (falló y cayó a reglas). **Más `llm` y menos
  `fallback` = la IA está pensando, no adivinando.** Se combinan con las métricas LLM existentes
  (latencia, uso por NPC vía `end_user`) para ver en Grafana si la IA mejora con el tiempo.
- Queries útiles: `sum by(action)(rate(game_npc_actions_total[15m]))` (mezcla de jugadas);
  `sum by(outcome)(rate(game_npc_decisions_total[1h]))` (ratio LLM vs reglas).

### 2026-06-26 — NPC con LLM sin colgar el juego (decidir fuera de la transacción)
- Los NPC con cerebro `llm` leen su estado + el **grafo de dependencias** + las **métricas** y el
  LLM decide su táctica (igual que un jugador). El problema no era usar la GPU sino que la llamada al
  LLM se hacía **con la transacción de la DB abierta** → durante los ~20-30 s de la GPU la conexión
  quedaba "idle in transaction" reteniendo snapshot/locks y, con varios NPCs, el tick **colgaba el
  juego ~2 min**.
- **Fix:** `LlmBrain.act` ahora hace **commit antes** de llamar al LLM (lee estado → cierra
  transacción → decide sin transacción → aplica en una transacción corta). El tick puede tardar por
  la GPU pero **ya no bloquea** a los jugadores. Reactivado `npc=llm`.

## [1.69.0] - 2026-06-26

## [1.68.0] - 2026-06-26

### 2026-06-26 — Más estabilidad: SSE sin backlog (30 sonidos) + tick sin colgar el juego
- **30 sonidos de notificación de golpe al cargar:** el SSE re-emitía **todo el backlog** de
  notificaciones al conectar (catch-up desde 0) → 30 beeps **y** 30 refresh/loadFeed de una.
  Ahora el SSE arranca desde la última (`catch_up=False`) y solo empuja lo **nuevo** (el historial
  ya lo trae el GET); el cliente además **coalesce** los refresh del SSE (uno cada 600ms).
- **El juego se colgaba ~2 min cada tanto:** el tick de NPCs con **LLM** (GPU) mantenía **locks de
  fila** mientras esperaba la GPU (los lock-waits no respetan `pool_timeout`), y los requests del
  jugador esperaban hasta que el tick soltaba. Mitigado pasando el tick a **`npc=rules`** (NPCs
  siguen jugando, sin LLM en el camino caliente). *Follow-up:* reestructurar `run_npc_turn` para
  decidir con el LLM **fuera** de la transacción y aplicar la acción en una transacción corta, para
  poder reactivar el LLM sin bloquear.

### 2026-06-26 — Performance/estabilidad: paneles que se quedaban cargando + escala a más jugadores
- **Causa raíz del "se queda cargando / paneles vacíos / base no encontrada":** el cliente disparaba
  **~12-15 requests en paralelo cada 4 s** (todos los loaders de panel en cada `refresh`, + en cada
  evento SSE). Con varios jugadores eso **saturaba el pool de conexiones** (5+10) → requests
  esperaban hasta 30 s → los últimos paneles (hub/mercado/colonización) quedaban vacíos y `baseId()`
  caía a un id inválido → "base no encontrada".
- **Fix de carga (cliente):** el ciclo rápido de 4 s ahora solo trae el **estado** (3 fetch) y hace
  renders locales. Los paneles secundarios se recargan **cada 20 s y solo si están abiertos**
  (los colapsados no piden datos), o al **expandirlos**. **Se pausa todo con la pestaña en segundo
  plano** (`document.hidden`) → tabs idle = 0 carga. De ~3 req/s/cliente a ~1.
- **Fix de escala (server):** pool de DB 10+20 (antes 5+10) y `pool_timeout` 10 s (antes 30) → bajo
  saturación los requests **fallan rápido** y el cliente reintenta, en vez de **colgar** el panel.
- **UX:** construir/entrenar avisan "esperá que cargue" si el estado aún no llegó (no más "base no
  encontrada" engañoso). Completado el pictográfico (panel meta + selects de mineral).

## [1.67.0] - 2026-06-26

### 2026-06-26 — Fix erratismo de mercado/hub + cache del HTML + gate de tests (SDD 45)
- **Hub/mercado erráticos (500 intermitente, p.ej. vender hierro):** `_hub_row` hacía select→insert
  sin manejar la carrera; en Postgres dos requests concurrentes (la carga del hub crea filas de
  precio para todos los minerales) chocaban con el unique constraint → `IntegrityError` 500. Ahora se
  crea en un **savepoint** y, si pierde la carrera, **relee** la fila — sin 500. Tolerante también a
  duplicados preexistentes (`.first()` en vez de `scalar_one_or_none`).
- **"Se me fue la base orbital / quedó pegado a una versión vieja":** el HTML se sirve con
  `Cache-Control: no-store` (antes `no-cache`) → el browser **no** guarda el index y siempre ves la
  versión nueva tras un deploy, sin hard-refresh.
- **Gate de tests (SDD 45):** marker `chrome`; `tests/test_web_smoke.py` abre **todos los paneles**
  (normal + dibujos, usuario sembrado sin límites) y falla ante cualquier error JS; e2e API
  `test_all_keys_no_server_error` barre **todos los minerales/edificios/unidades** y falla si alguno
  da 500. `make test`/`test-ui`/`e2e-local`; `make dt-up/dt-down` (instancia `galaxy-dt`);
  `make deploy` con gate (build→test→promote) y `make deploy-force` de emergencia.

## [1.66.0] - 2026-06-26

### 2026-06-26 — CD de un paso: build + deploy in-cluster (SDD 44)
- Nuevo Argo Workflow `deploy/build/online-game-cicd.yaml` que **buildea (Kaniko) y despliega (helm)
  en una sola corrida**, con el tag como **parámetro** (no se edita YAML). `make deploy V=X.Y.Z` lo
  dispara. El deploy usa `helm upgrade --reuse-values --set image.tag=…`: reutiliza los values del
  release vivo (incluida la key de OpenRouter) → **el Workflow no maneja secretos**.
- RBAC mínima namespaced (`deploy/build/cicd-rbac.yaml`): SA `og-deployer` + Roles/Bindings.
- El `helm upgrade` **manual** queda documentado como **fallback** (cambios de chart/values) en
  SDD 17; el build-only (`online-game-kaniko.yaml`) se conserva. Doc: `docs/sdd-cicd-in-cluster.md`.

## [1.65.0] - 2026-06-26

### 2026-06-26 — Fix: ya no te desloguea cuando la API parpadea (deploy/red) + e2e de frontend
- **Bug:** un fallo **transitorio** de `/players/me` (un deploy rolando el pod, un corte de red de un
  segundo) te mandaba al **login** y veías **todo vacío** (incluida la opción de **base orbital**, que
  vive en el modal de planeta). `boot()` deslogueaba ante CUALQUIER error.
- **Fix:** ahora solo desloguea ante un **401 real** (token inválido); ante un error transitorio
  **mantiene la sesión y reintenta** solo cada 3 s. `api()` expone el status HTTP.
- **Tests de frontend (nuevos, Playwright + Chromium):** `tests/test_web_smoke.py` levanta un server
  real y verifica con un browser que (a) el **modo dibujos** renderiza sin errores de JS, (b) un
  **503** no desloguea, (c) un **401** sí. Se saltean solos si no hay Chromium.

### 2026-06-26 — Modo pictográfico F2 (cont.): atacar/combate/eventos sin leer (SDD 43)
- El **modo dibujos** ahora también cubre **Atacar** (unidades como íconos + ⚔ y ✓/❌ de energía),
  **Reportes de combate** (unidades perdidas y botín como íconos/chips) y **Eventos** (ícono grande +
  ⏱, con el nombre leído por voz al tocar).

## [1.64.0] - 2026-06-26

### 2026-06-26 — Modo pictográfico F2: navegar sin leer (SDD 43)
- En **modo dibujos**, los menús desplegables de **Acciones** (construir/entrenar/expedición) se
  reemplazan por una **grilla de botones-ícono**: cada opción es su dibujo con una marca
  **✓ alcanza / ❌ no alcanza / 🔒 bloqueado** — se elige tocando, sin leer.
- **Toggle por panel:** cada panel tiene un botón **🔤/🖼** en su título para forzar/excluir el modo
  dibujos solo ahí (override sobre el global).
- **Mercado** y **Hub** muestran los minerales como chip ícono+letra en modo dibujos.
- Sin cambios de API (reusa `/catalog`); apagado por default, con el modo off todo queda como hoy.

## [1.63.0] - 2026-06-26

### 2026-06-26 — Modo pictográfico F1 + leer en voz alta (SDD 43)
- Nuevo botón **🔤/🖼** en el header: el **modo dibujos** muestra el **chip ícono + letra + número**
  (`🔩 Fe 30`) en costos de construir/entrenar/expedición, en los faltantes (`🔩 ❌ −12`, `⚡❌ −N`),
  en los requisitos bloqueados (🔒 con íconos) y en los stocks/unidades del imperio. Pensado para
  quien **no lee**: relaciona número, ícono y la **letra del material**.
- **Leer en voz alta (TTS):** con el modo activo, **tocar un ícono dice qué es** (Web Speech API,
  voz por idioma es/en) — para lo difícil de representar con un dibujo.
- **Aditivo, no rompe nada:** apagado por default; con el modo off **todo queda como hoy**. Los
  íconos son **atributos del catálogo** (`icon:`/`symbol:` en `content/*.yaml`) que la API expone por
  `/catalog` sin localizar — la UI solo los lee. e2e `test_catalog_pictographic_icons`. **321 verdes.**

### 2026-06-26 — Docs: SDD 43 modo pictográfico (jugar sin leer)
- Nuevo `docs/sdd-pictographic-ui.md` (**diseño, NO implementado**): un botón **🖼 Dibujos** que
  reemplaza el texto por el **chip ícono + letra + número** (`🔩 Fe 30`, faltante `🔩 Fe ❌ −12`) en
  **todos los paneles** (cobertura panel por panel de los 25 `data-panel`), pensado para quien **no
  lee nada** pero relaciona números, íconos y la letra del material. Campos `icon:`/`symbol:`
  aditivos en `content/*.yaml`; activable **global o por panel**.
- **Invariante:** es aditivo y **apagado por default** — con el modo desactivado **todo queda como
  hoy** (no rompe la UI actual); el texto se preserva como tooltip/aria-label (accesibilidad + TTS
  en F3 + aprender a leer).

### 2026-06-26 — Docs: SDD de colonización sincronizado
- `docs/sdd-colonization.md` registra el estado **v1.6**: pre-cálculo de costo en `/colonize/options`
  (`energy_surface`/`energy_orbital`/`shuttle_cost`) visible en el modal, y errores de energía con
  detalle compartidos con build/training/research.

## [1.62.0] - 2026-06-26

### 2026-06-26 — Colonizar: costo visible antes de hacer click + error con detalle
- El menú del planeta ahora muestra **antes de tocar Colonizar** el **costo** de fundar ahí:
  energía de superficie y orbital (escala con cuántas colonias ya tenés) + **transbordadores**
  necesarios, comparado con lo que tenés (en rojo si no alcanza). `GET /colonize/options` expone
  `energy_surface`/`energy_orbital`/`shuttle_cost`.
- El error "Energía insuficiente para colonizar" ahora también dice **cuánto falta y en cuánto se
  recarga** (mismo helper que build/training/research).

## [1.61.0] - 2026-06-26

### 2026-06-26 — Errores de energía con detalle (cuánto falta y cuándo se recarga)
- Al intentar **construir** (incluida la base orbital), **entrenar** o **investigar** sin energía,
  el mensaje ahora dice exactamente **cuánta energía necesitás, cuánta tenés, cuánto falta** y
  **en cuánto tiempo se recarga** (la energía es global del jugador, no por planeta), igual que ya
  hacía el error de minerales. Antes solo decía "Energía insuficiente" sin contexto.
- Nuevo helper `energy_shortfall_msg()` reutilizado por build/training/research.

## [1.60.0] - 2026-06-25

### 2026-06-25 — Hub y mercado negro: naves + escolta + riesgo pirata determinístico
- Comprar en el **hub** o trocar en el **mercado negro** ahora exige **naves de carga** (1 por cada
  capacidad de cargo) y expone el cargamento a **piratas** con un **riesgo DETERMINÍSTICO** según la
  cantidad (`pirate_strength`): sin escolta perdés hasta el `pirate_loss_cap` (50%); una **escolta**
  militar opcional baja el riesgo (su defensa vs el poder pirata, misma fórmula que los convoyes).
- La UI muestra, **antes de operar**, las naves necesarias y el **🏴‍☠️ riesgo %** (cae a 0 con
  suficiente escolta); el resultado informa lo robado. `GET /market/hub` expone
  `pirate_strength`/`pirate_loss_cap`/`cargo_capacity` para el preview. `hub_trade`/`black_market`
  aceptan `escort`.
- Tests: `test_hub_buy_pirate_risk_and_escort` (riesgo 50% sin escolta → 0 con escolta).

## [1.59.0] - 2026-06-25

### 2026-06-25 — Panel de Colas: research, transportes y espías con su ETA
- El panel **Colas y flotas** ahora muestra, además de construcción/entrenamiento/ataques:
  **🔬 investigación** (con barra/ETA), **🚚 transportes** de minerales (carga, origen→destino, cuándo
  llega) y **🕵 espías** (ida y vuelta). Antes esos viajes no aparecían y no se veía cuánto tardaban.
- `/players/me` ahora expone `transports` y `spy_missions` en curso (con `arrives_at`/`returns_at`).
- Test e2e: el convoy aparece en `me.transports` con su `arrives_at`.

## [1.58.0] - 2026-06-25

### 2026-06-25 — Árbol de tecnología: edificios/unidades/research con prerequisitos (SDD 1)
- **No todo se puede al inicio**: progresión científica (data-driven en YAML, enforce en servicio,
  🔒 en la UI).
  - **Edificios**: `factory` pide **Laboratorio**; `hangar` pide fábrica; `turret` pide lab + tech
    **armas**; `counter_intel` pide lab + **contraespionaje**. Los básicos (mina, planta, mercado,
    cuartel, lab) siguen libres.
  - **Unidades**: `tank/aircraft` piden fábrica + **armas**; `shuttle` pide fábrica + **antigravedad**;
    `spy` pide lab + **espionaje**. **Mercenario (soldado) y trabajador: sin cuartel, baratos e
    inmediatos** (ataque rápido). **Barco**: fábrica, sin tech (camino dinámico de ataque, lento).
  - **Investigación encadenada**: deep_core←minería, escudos←armas, contraespionaje←espionaje,
    robótica_orbital←antigravedad, domos←blindaje_térmico.
  - **Mundos hostiles**: la **base orbital** (orbital_robotics) habilita construir ahí (ya estaba).
- Enforce en `build.py`/`training.py`/`research.py` (rechazo claro si falta edificio o tech). La UI
  de Acciones muestra **🔒 requiere 🏗edificio / 🔬investigación** en el costo. El **cerebro NPC** se
  hizo tech-aware (laboratorio → investiga armas → fábrica → torreta; no intenta lo que no puede).
- Tests: `test_tech_tree_gates_buildings_and_research_e2e` + ajustados depgraph/training/science/npc.

## [1.57.0] - 2026-06-25

### 2026-06-25 — Transporte: muestra el stock disponible en el origen
- El form de transporte no decía cuánto tenías del mineral en el **planeta de origen**. Ahora muestra
  **"disponible en origen: N @planeta"** en vivo (al cambiar origen/mineral/cantidad) y avisa **cuánto
  falta** si pedís más de lo que hay. Solo frontend.

### 2026-06-25 — Sync de estados de los SDD con la realidad
- Auditoría CHANGELOG ↔ SDD ↔ código: el CHANGELOG estaba fiel, pero el campo **Estado** de casi
  todos los SDD seguía en "propuesto" pese a estar en producción. Reescritos los 42: **36
  implementados**, **2 parciales** (26 spin-offs / 38 replay), **1 bloqueado** (5 Telegram), **3
  pendientes de infra** (30/31/32).

## [1.56.0] - 2026-06-25

### 2026-06-25 — Novedades se alimentan del CHANGELOG (SDD 27)
- Los anuncios de categoría **`release`** ahora se **generan automáticamente** desde el `CHANGELOG.md`
  (`app/services/changelog.py`: parsea cada `## [X.Y.Z] - fecha` + su título `### … — Título` y el
  primer bullet como resumen). Así el panel **📰 Novedades** se mantiene solo; el `announcements.yaml`
  queda solo para **incoming/spinoff/season**. El link va al CHANGELOG en GitHub.
- Test: `GET /announcements?category=release` devuelve los `release-X.Y.Z` del changelog.

## [1.55.0] - 2026-06-25

### 2026-06-25 — Construir en colonias/bases orbitales (selector de base)
- El form de Acciones siempre construía en la base **principal** (no se podía elegir colonia/órbita).
  Ahora hay un **selector de base** (aparece si tenés más de una) con su 🌙/🛰/🪐 y planeta. Así
  construís en la **base orbital** del otro planeta (lo que aparecía pero no se podía usar).
- `renderCost` ahora calcula contra el **stock del planeta de esa base** (SDD 42: el material debe
  estar ahí) y aplica el **×1.5** de las bases orbitales (SDD 37) → la disponibilidad ya no engaña.
  Si falta material en ese planeta, hay que **transportarlo** (panel Mercado → 🚚). Solo frontend.

## [1.54.0] - 2026-06-25

### 2026-06-25 — Fix: layout de la consola de admin
- Las filas del ABM usaban la clase `.ab` (grid de 3 columnas, pensada para minerales) y con 6
  elementos (id, usuario, email, estado, 3 botones) **se pisaban**. Nueva clase `.acrow` (flex con
  wrap, botones agrupados a la derecha) → se ve ordenado y responsive.

## [1.53.0] - 2026-06-25

### 2026-06-25 — HTML sin cache + métricas LLM separadas usuarios vs NPC
- **Fix raíz del "sigo viendo lo viejo"**: el HTML (`/`, `/game`, `/tech`) se sirve con
  `Cache-Control: no-cache` → tras cada deploy ves la versión nueva **sin hard-refresh** (antes el
  navegador cacheaba el HTML por heurística de ETag). Por eso el link viejo de Novedades persistía
  aunque el fix ya estaba deployado.
- **Dashboard LLM**: nuevos paneles **usuarios vs NPC** (split por `end_user` =
  `online-game:player:*` vs `online-game:npc:*`): tokens/s y consultas 24h por tipo. Aclara que los
  NPC consultan al LLM cada tick y los usuarios solo al usar el asistente (por eso domina NPC).
- Test e2e: `test_html_served_with_no_cache`.

## [1.52.0] - 2026-06-25

### 2026-06-25 — Consola de admin (ABM de cuentas) + fix de links de Novedades
- **Consola de admin (SDD 14)**: al loguearte como admin ves una **vista dedicada** (el admin no
  juega, solo administra). ABM completo de cuentas: buscar, **editar** usuario/email/estado
  (`POST /admin/players/{id}/edit`), **resetear** clave (🔑) y **borrar** cuenta + imperio
  (`DELETE /admin/players/{id}`, cascade). Guardas: no te borrás a vos ni a otro admin; valida
  unicidad de nick/email. (Resuelve el lío de cuentas duplicadas/typo sin tocar la base a mano.)
- **Fix**: los links de **Novedades** apuntaban a `docs/*.md` (no servidos por el juego → 404). Ahora
  un helper manda los `docs/...` a **GitHub** y deja `/...`/externos como están.
- Tests: `test_admin_account_abm_e2e` (editar nick→login con el nuevo, borrar, guardas, no-admin→403).
- **Espionaje — feedback**: al despachar espías el toast muestra **cuánto tarda** (⏱) y avisa que el
  intel llega a 🔔; y al resolverse **se avisa al que espió** ("intel lista, profundidad X%, perdiste
  N espías") — antes solo se notificaba al detectado. Test: aviso `intel_ready` al observador.

## [1.51.0] - 2026-06-25

### 2026-06-25 — Login por email o usuario + vitrina de universos spin-off (SDD 26)
- **Login por email O usuario**: `POST /auth/login` acepta el username **o** el email + contraseña.
  Resuelve quedarse afuera tras renombrar el nick (el login era solo por username). Placeholder y
  ayuda actualizados ("usuario o email").
- **Universos spin-off — vitrina (SDD 26, showcase)**: `content/universes.yaml` (data-as-code,
  bilingüe, **genérico/homenaje** — nombres alterados). Primer pack: **"Guerra de las Colonias"**
  (homenaje a Battlestar Galactica): materiales (tilio), mundos y naves (coloniales vs autómatas) +
  en qué **difiere del estándar**. Endpoint público `GET /universes` y `GET /universes/{key}`
  (localizado). Panel **🌌 Universos** en el cliente. *No jugable aún* — es la maqueta para la página.
- **Panel admin — reset de clave**: buscador de usuario/email + botón 🔑 que llama
  `/admin/players/{id}/reset-password` y muestra la temporal.
- Tests: `test_login_by_username_or_email`, `test_universes_showcase_public`.

## [1.50.0] - 2026-06-25

### 2026-06-25 — Fixes de cuenta/admin + UX de espionaje
- **Fix (importante): el navegador autocompletaba "nueva contraseña" en Perfil** → al cambiar solo el
  nick te cambiaba la clave sin querer. Ahora los campos llevan `autocomplete` correcto y el
  placeholder aclara "vacío = no cambiar". (El backend/front ya solo cambiaban la clave si mandabas
  una; el culpable era el autofill.)
- **Admin por `ADMIN_EMAIL`**: `/players/me` ahora reporta `is_admin` por flag en DB **o** por
  coincidencia con `ADMIN_EMAIL` (igual que `get_current_admin`) → setear el env alcanza para que una
  cuenta existente vea el panel 🛡 Admin, sin tocar la base.
- **Reset de contraseña por admin**: `POST /admin/players/{id}/reset-password` genera una temporal,
  la guarda hasheada y la devuelve una vez (el admin no puede *ver* claves, solo resetear). Panel
  admin: buscador de usuario/email + botón 🔑 reset. (Recuperación del propio dueño: OTP por email.)
- **Espionaje**: al espiar, el prompt ahora **carga tu máximo de espías** y avisa si no tenés (antes
  arrancaba en 5 a ciegas).
- Tests: `test_admin_reset_password_e2e`, `test_me_is_admin_by_email_without_db_flag`.

## [1.49.0] - 2026-06-25

### 2026-06-25 — Alta con aprobación de admin + panel (SDD 14)
- Nuevo `Player.status` (`active` default | `pending` | `suspended` | `rejected`) + `approved_at/by`
  (migración aditiva, `server_default='active'` → no rompe cuentas/tests). Flag
  **`SIGNUP_REQUIRES_APPROVAL`** (default OFF): cuando está ON, las altas nuevas (OTP y user+pass)
  nacen **`pending`** y **no pueden jugar** (`/onboard` → 403 "espera aprobación"); el admin siempre
  nace `active`. Al quedar pending, se **notifica a los admins** (in-app).
- Endpoints **solo admin** (sobre `get_current_admin`): `GET /admin/players?status=pending` (con
  email), `POST /admin/players/{id}/approve|reject|suspend` (setean estado + `approved_at/by` +
  notifican al jugador).
- `/players/me` ahora expone `is_admin` y `account_status`.
- UI: panel **🛡 Admin** (solo visible para admins) con la lista de pendientes y aprobar/rechazar;
  aviso **"Cuenta en revisión"** para el jugador pendiente (en vez del onboarding).
- Tests: `test_admin_approval_flow_e2e` (pending→403, admin aprueba→onboarding 201, no-admin→403).

## [1.48.0] - 2026-06-25

### 2026-06-25 — Anuncios / "Lo que viene" (SDD 27)
- Contenido **data-as-code** en `content/announcements.yaml` (tipado, bilingüe): categorías
  `release|incoming|spinoff|season|maintenance` y estados `live|coming|planned`. Los spin-offs
  (ej. Star Wars) listan **qué traen y en qué difieren del estándar** (`differences`).
- Nuevo endpoint público **`GET /api/v1/announcements`** (sin auth): localiza con `?lang=`, filtra
  por `?category=`/`?status=`, ordena live→planned y por fecha. `localize` ahora swapea también
  `title`/`summary`/`standard_baseline`/`differences`.
- UI: panel **📰 Novedades** en el cliente (categoría + estado + resumen + diferencias del spin-off).
- Test e2e: `test_announcements_public_localized_and_filtered` (público, EN, filtros).

## [1.47.0] - 2026-06-25

### 2026-06-25 — Asistente: selector de modelo (GPU / nube / tu modelo BYOK) (SDD 9)
- En el panel del asistente, un **selector** con 3 modos (tooltip al pasar el mouse):
  - **🖥️ GPU local** (default): gratis, sin tope diario, rápido (modelo local).
  - **☁️ Nube (free→pago)**: usa el alias pago barato (`assistant_cloud_model`=gemma4-paid), con el
    **budget diario** por jugador para no abusar.
  - **🔑 Tu modelo (BYOK)**: ventana para pegar **tu API key de OpenRouter + el modelo**; se usa esa
    key **solo en esa request** (no se persiste en el server) y **no consume el cupo** del server
    (lo pagás vos). La key/modelo se guardan en tu navegador (localStorage).
- `POST /advisor/ask` acepta `model_mode` (`gpu|cloud|byok`) + `byok_key`/`byok_model`/`byok_base_url`.
  `llm_chat` admite override de `api_key`/`base_url`. El budget diario aplica a gpu/cloud; byok exento.
- Tests: `test_ask_cloud_mode_uses_paid_alias`, `test_ask_byok_uses_player_key_and_skips_budget`,
  `test_ask_byok_requires_key_and_model` (servicio) y `test_advisor_model_selector_e2e` (HTTP:
  cloud→200, byok sin key→400, modo inválido→422).

## [1.46.0] - 2026-06-25

### 2026-06-25 — Métricas LLM separadas por app (dashboard ya no mezcla juegos)
- El campo `user` que se manda a LiteLLM (→ `end_user`) ahora va **prefijado con la app**
  (`online-game:player:bob`, `online-game:npc:zorg`) — antes era `player:bob`. Como varios juegos
  comparten el mismo LiteLLM/GPU, esto permite separar el consumo por app. Centralizado en
  `llm.py:_tag_user` (cubre asistente + NPC). Sigue atribuyendo por jugador (SDD 28).
- **Dashboard `llm-usage.json`**: los paneles de tokens/spend ahora filtran `end_user=~"online-game:.*"`
  → muestran **solo el juego**, no el shooter ni otros. Los paneles de **GPU/HAMI y requests del
  proxy** se marcaron como **compartidos** (la GPU es física; no se pueden separar por app). El panel
  "GPU vs nube" pasó a tokens de salida (que sí llevan `end_user`) para poder scopearlo.
- Tests: `tests/test_llm.py` (tagging) + ajuste de los asserts de `user` en `test_npc.py`.

## [1.45.0] - 2026-06-25

### 2026-06-25 — Página Tech: cómo usa la IA el juego + enlace desde la landing
- Nueva sección **"Cómo usa la IA el juego"** en `/tech`: GPU local primero (Ollama × 2), asistente con
  **subgrafo indexado** (RAG, razonamiento determinista + IA solo redacta), **cadena con red** (si la
  GPU no llega → modelo pago barato gemma-4, porque el free se bloquea por día → tips deterministas) y
  **NPC + budget por jugador/día**. Actualizada la fila IA/LLM del stack (gemma-4 pago, no free).
- La **landing** (`/game`) ahora enlaza a **🛠 Tech** (header + footer, ES/EN) y la card del asistente
  aclara que corre en **GPU propia**.
- Tests e2e ampliados: la landing enlaza `/tech`; `/tech` muestra la sección de IA (subgrafo + gemma-4).

## [1.44.0] - 2026-06-25

### 2026-06-25 — Asistente en GPU local: subgrafo indexado + budget por usuario (SDD 9)
- **Índice del grafo** (`depgraph._graph_index`, cacheado por raza×planeta): pre-tokeniza el corpus
  una vez; `retrieve` ya no re-tokeniza todo en cada consulta.
- **Opción B (el fix del "delira")**: el asistente manda solo el **SUBGRAFO relevante** a la pregunta
  (top-k = `advisor_graph_k`=14) + los blockers, en vez del **grafo completo** (~7k tokens). Medido:
  con el grafo completo la GPU local (qwen2.5:1.5b, ctx 4096 por defecto) **trunca y delira** o cae a
  la nube free (con **tope diario 429**); con el subgrafo (~1–2k tokens) la **GPU responde en 1–3s**,
  sin truncar y sin depender de la nube.
- **Modelo/timeout por caso de uso**: el **asistente** es interactivo (timeout corto
  `assistant_llm_timeout_seconds`=20s); los **NPCs** toleran esperar (atacar/comerciar/chat de
  alianza) → `npc_llm_timeout_seconds`=60s, priorizan la **GPU local** (ahorra créditos). `llm_chat`
  acepta `model`/`timeout` por llamada; `*_llm_model` permite apuntar a otro alias sin tocar código.
- **Presupuesto del asesor por jugador/día** (`advisor_llm_calls_per_day`=40, patrón del repo
  shooter): pasado el cupo **no se llama al LLM** (cero tokens/créditos) → tips deterministas. Se
  cuenta desde el journal (`advisor_ask`), reset lazy a medianoche UTC.
- Tests: `test_ask_sends_bounded_subgraph_not_full_graph`, `test_ask_daily_budget_stops_calling_llm`.

## [1.43.0] - 2026-06-25

### 2026-06-25 — Fix: el auto-refresh borraba lo que elegías en Mercado/Hub
- El panel del Hub (y el de Mercado/Transporte) se re-renderiza solo cada 4s; eso **reseteaba a los
  valores por defecto** lo que estabas eligiendo (minerales del trueque del mercado negro, cantidades,
  origen/destino/escolta del transporte) antes de que llegaras a tocar el botón. Ahora se **preservan**
  tus selecciones/cantidades entre refrescos. (Bug introducido en 1.41.0; solo frontend.)

## [1.42.0] - 2026-06-25

### 2026-06-25 — Avisos centralizados: toasts apilables y descartables
- Todos los resultados de acciones (construir, entrenar, vender, transportar, atacar, investigar,
  alianzas, etc.) ahora aparecen como **toasts** arriba a la derecha, **siempre visibles** sin
  importar en qué panel estés ni cuánto hayas scrolleado. Antes el aviso salía en un `#msg` cerca del
  panel de imperio y si estabas en un panel de más abajo no te enterabas de "qué pasó".
- Los **éxitos** se autodescartan (~4.5s); los **errores quedan** hasta que los cerrás (clic o ×), así
  no se te escapa el motivo. Máximo 5 a la vez. `alert()` del onboarding también pasó a toast.
- Los **pre-cálculos inline** (costo/viabilidad al crear unidades, plan de combate, estimación del
  mercado negro) se mantienen donde están: lo que se puede anticipar se muestra antes de accionar; lo
  que solo se sabe al ejecutar el botón cae en el toast. (Cambio solo de frontend; sin API nueva.)

## [1.41.0] - 2026-06-25

### 2026-06-25 — Mercado negro: la UI ahora te dice por qué no podés trocar
- El panel 🕶 Mercado negro muestra **antes de tocar el botón**: tus **naves de carga** (y avisa si te
  falta una, que se entrena en la Fábrica), tu **stock en el planeta natal** del mineral que pagás, y
  una **estimación de lo que recibís** (al cambio del hub × premium). Si no te alcanza el stock o son
  minerales iguales, lo marca en rojo. Resuelve el "no sé por qué me falla el trueque".
- `GET /api/v1/market/hub` ahora devuelve `black_market_rate` para que la UI estime sin hardcodear.
- Test e2e: el hub expone `black_market_rate`.

## [1.40.0] - 2026-06-25

### 2026-06-25 — Hangar: estacionar/despachar más naves (SDD 42 Fase 3)
- Nuevo edificio **`hangar`** (categoría economía): cada hangar activo **sube el cupo** de naves de
  carga que podés despachar por ventana de 2h (`market_transport_ships_per_window` base +
  `market_transport_ships_per_hangar` × hangares). Cierra el loop "las naves que no salen quedan en
  el hangar": construí hangares para mover convoyes más grandes.
- El mensaje del límite ahora dice el cupo efectivo y sugiere construir hangares.
- Tests: `test_hangar_raises_ship_window_cap` (servicio) y `test_hangar_raises_transport_cap_e2e`
  (HTTP: sin hangar 6 naves → 400; con hangar → 201 con 6 naves; hangar en el catálogo).

## [1.39.0] - 2026-06-25

### 2026-06-25 — Piratería y escolta de convoyes (SDD 42 Fase 3 §8)
- Los **convoyes** de transporte ahora pueden ser **emboscados por piratas** en vuelo: cada tick del
  mundo, con probabilidad `pirate_raid_chance`, un convoy es atacado. El poder pirata escala con el
  tamaño de la carga (`pirate_strength`).
- **Escolta**: `POST /api/v1/market/transport` acepta `escort` (unidades militares que viajan con el
  convoy). Defienden con su `defense` usando la misma lógica de pérdidas que `resolve_combat`: si la
  escolta repele, la carga queda intacta (puede sufrir bajas); si pierde, los piratas roban hasta
  `pirate_loss_cap` (50%) de la carga. La escolta superviviente vuelve al llegar.
- Las naves de carga **no** escoltan (hay que mandar unidades militares); valida tenencia.
- Journal: `convoy_raided` / `convoy_defended`. Worker corre `raid_convoys` antes de entregar.
- Migración: `transport_missions.escort` (Text, default `{}`).
- UI: selector de escolta opcional en el form de transporte (🛡).
- Tests: `test_pirates_steal_from_unescorted_convoy`, `test_escort_defends_convoy`,
  `test_escort_must_be_military_and_owned` (servicio) y `test_transport_with_escort_e2e` (HTTP:
  escoltar con nave de carga → 400, escolta militar → 201 + eco).

## [1.38.0] - 2026-06-25

### 2026-06-25 — Mercado negro: trueque material-por-material (SDD 42 Fase 3)
- Nuevo `POST /api/v1/market/blackmarket`: **trueque** de un mineral por otro **sin pagar energía**.
  Pagás con un mineral y recibís otro valuados a los **precios dinámicos del hub** de tu galaxia,
  pero con un **premium ilegal** (`black_market_rate` = 0.7) → siempre te dan menos que el cambio
  justo. Es el riesgo del contrabando: **no** tiene los límites anti-abuso del mercado natal.
- Requiere una **nave de carga** (viajás con la mercancía); la carga sale y entra de tu planeta
  natal. Queda registrado en el journal (`black_market`).
- UI: mini-form **🕶 Mercado negro** dentro del panel del Hub (elegís pagar/recibir + cantidad).
- Tests: `test_black_market_barter`, `test_black_market_needs_ship_and_material` (servicio) y
  `test_black_market_barter_e2e` (HTTP: sin nave → 400, trueque ok).

## [1.37.0] - 2026-06-25

### 2026-06-25 — Mercado equilibrado: límites anti-abuso (ventana de 2h)
- En el mercado del **mundo natal**: por **ventana móvil de 2h** (rolling = se resetea sola), no
  podés **vender más del 30%** ni **comprar más del 20%** (+ piso) de tus tenencias de cada mineral
  → sin dumping ni reventa, parejo. Las **colonias** quedan exentas del % (se rigen por transporte).
- **Transporte**: máximo **4 naves de carga despachadas por ventana de 2h** (las demás "esperan en el
  hangar"). Todo config-driven (porcentajes/ventana/piso). Se calcula desde el journal (SDD 38).
  Tests + 289 verdes.

## [1.36.0] - 2026-06-25

### 2026-06-25 — SDD 42 Fase 3: hub galáctico con precios dinámicos + inter-galaxia
- **`MarketPrice` por (galaxia, mineral)** con precio por **oferta/demanda** (estilo stock market):
  comprar sube, vender baja, y en el tick **revierte** lento al precio intrínseco (base/abundancia-
  media → premium caros), dentro de una banda. `POST /api/v1/market/hub/{buy|sell}` (requiere
  **nave de carga**, pagás/cobrás energía). `GET /api/v1/market/hub` muestra los precios de **tu
  galaxia y de TODAS** (consulta inter-galaxia, tu idea). Panel web **🛰 Hub galáctico**. Pendiente:
  black market + robos/escolta + aparcamiento.

### 2026-06-25 — Investigación por categorías
- Cada tecnología ahora tiene **`category`** (economy/military/espionage/colonization) y el panel
  🔬 Investigación las **agrupa por categoría**. Data-driven (editar el YAML). Bilingüe.

## [1.35.0] - 2026-06-25

### 2026-06-25 — SDD 42 Fase 2 completa: transporte de minerales entre planetas
- Unidad **`cargo_ship`** (capacidad `cargo`) + **`TransportMission`**: enviás minerales de un planeta
  tuyo a otro — sale del origen, **viaja** (tiempo por distancia, consume naves), al **llegar acredita
  al planeta destino** y devuelve las naves. Se resuelve en `state.advance` y el tick. Valida que
  tengas el material en el origen y naves suficientes. `POST/GET /api/v1/market/transport`; form 🚚
  en el panel 💱 Mercado. Con esto cierra el lazo de la economía por-planeta (minás/comprás local,
  y movés bulk donde lo necesitás). Tests + 285 verdes.

## [1.34.0] - 2026-06-25

### 2026-06-25 — SDD 42 Fase 2: economía POR-PLANETA (el material vive donde está)
- **Refactor estructural** (backward-compatible): `ResourceStock` ahora es **por planeta**
  (`planet_key`), con migración que **lleva el stock existente al mundo natal** → las partidas
  actuales no cambian. `player_stocks` pasa a **agregado** (suma por planeta, sigue sirviendo a
  UI/scoring/asistente); `planet_stocks` para un planeta puntual.
- **Consumo por-planeta:** las **minas acreditan al planeta de su base**; **construir/entrenar/
  investigar gastan del planeta de la base** (si falta material ahí → "transportá a ese planeta");
  el **saqueo** sale del planeta de la base atacada y el botín se descarga en el mundo natal del
  atacante; el **mercado** compra/vende en el stock del planeta del mercado.
- **UI:** el panel de bases muestra el **stock por planeta** (⛏) de cada base.
- Pendiente de Fase 2: `TransportMission` + naves de comercio (mover bulk entre planetas). 283 verdes.

### 2026-06-25 — SDD 42 diseño ampliado: naves de comercio, aparcamiento y robos
- En tu planeta no necesitás nave; en otro con base solo almacenaje; en otro sin base viajás con
  **nave protocolar** (ver precios) o **de cargo** (comprar y traer). Mercado de planeta = **1 slot**
  de nave (más con **hangar**); el **hub central de la galaxia tiene aparcamiento infinito**. En el
  hub hay **piratería**: los convoyes pueden ser **saqueados** (no solo destruidos) → conviene
  **escolta militar** (reusa `resolve_combat`). Documentado en SDD 42 (Fases 2/3).

## [1.33.0] - 2026-06-25

### 2026-06-25 — SDD 42 Fase 1: mercado local (comprar/vender minerales con energía)
- Edificio **`market`** + servicio de mercado: **precios por planeta derivados** (no hardcodeados)
  = base / abundancia → barato donde abunda, caro donde escasea, **premium (He-3, etc.) lo más caro**.
  `POST /market/buy|sell` (pagás/recibís **energía**, requiere un mercado activo en ese planeta;
  spread en la venta). `GET /market/prices?planet=` + `GET /market/planets`. Panel web **💱 Mercado**.
  Queda en el journal (`market_buy`/`market_sell`). Bilingüe. Tests + 283 verdes.
- Diseño actualizado (SDD 42): el hub se **repite por galaxia** y desde el hub podés **consultar
  precios de otras galaxias** (arbitraje informado). Fases 2 (inventario por-planeta + transporte) y 3
  (hub dinámico + black market) pendientes.

### 2026-06-25 — SDD 42 diseñado: mercado, comercio y economía por-planeta
- Doc `docs/sdd-market-trade.md`: mercado local por planeta (precios derivados del costo de
  producción × escasez/abundancia, no hardcodeados) + mercado **intergaláctico** por galaxia (hub en
  ubicación real, p.ej. cinturón de asteroides; precios por **oferta/demanda**) + **black market**
  (pagás con materiales pero viajás con nave). Pagás en **energía**; siempre necesitás nave para traer
  lo comprado. Deja lista la estructura de **inventario por-planeta** + transporte y el **policy de
  comercio por alianza** (v1 no chequea). **Fasado** porque el inventario por-planeta es una refactor
  grande del corazón económico. Solo especificación.

## [1.32.0] - 2026-06-25

### 2026-06-25 — NPCs juegan el meta + energía de nivelado matemática + el asistente la conoce
- **NPCs juegan el meta (SDD 41)**: el cerebro rule-based entrena la **unidad con mejor win-rate**
  (si hay muestra ≥5 y >50%) en vez del default tank/soldier; el cerebro LLM recibe el `meta` en su
  estado. Cierra el círculo: la IA aprende del journal **y lo aplica**.
- **Energía de nivelado ahora es proporcional (SDD 40/41)**: en vez de "los 3 últimos llenan / resto
  +100", se calcula `deficit = (promedio_ranking − tu_score)/promedio` y la energía = `deficit × tope`
  → cuanto más lejos del promedio, más recibís; quien está en o sobre el promedio **no recibe nada y
  no gasta cupo** (parejo, sin saltos de ranking ni ventaja).
- **El asistente conoce el nivelado**: se agregó la mecánica `mech_energy_assist` al grafo → cuando
  preguntás "ayudame con energía" explica la regla y te manda al botón ⚡ Nivelar (antes deliraba
  describiendo el contexto). Además se afinó la detección de preguntas de mecánica (no secuestra
  "qué construyo"). Tests + 279 verdes.

## [1.31.0] - 2026-06-25

### 2026-06-25 — SDD 41: la IA aprende el meta de las partidas (insights del journal)
- **Capa de insights** (`insights.py`): mina el journal (`battle_resolved` ahora guarda la **`force`**
  atacante) y calcula el **meta** real — win-rate de ataques + **win-rate por composición** (unidad
  dominante) — guardado en **`MetaInsight`** (upsert por key, persistido, queryable). Se recalcula en
  el tick. Determinista (sin entrenar nada).
- **La IA lo usa**: el asistente recibe `meta_summary_text` en su contexto → aconseja con datos
  ("las flotas con tank ganan 70%, n=…"). API `GET /api/v1/insights` + panel web **📈 Meta**.
- **Preparado para escalar y para cambios del juego**: cada evento del journal queda **versionado**
  (`game_events.version`, poblado desde el tag de deploy vía `APP_VERSION`) → podés **segmentar el
  meta por ruleset** cuando cambie el balance, y la data vieja sigue sirviendo. Los insights agrupan
  por las **claves que hay en los datos** (no hardcodean unidades) → unidades nuevas/removidas se
  manejan solas. El journal + `MetaInsight` quedan como **feature store** para entrenar un modelo a
  futuro (nivel 3, sin hacerlo aún). Doc `docs/sdd-meta-insights.md`. Tests + 276 verdes.

## [1.30.0] - 2026-06-25

### 2026-06-25 — SDD 37: bases lunares (minar recursos premium de las lunas)
- `POST /colonize {mode:"lunar"}`: fundás una **base lunar** sobre una luna (requiere **Robótica
  orbital**); sus minas extraen los **recursos premium de la luna** (He-3, tierras raras, hielo de
  agua) que los planetas no tienen — `abundance = grant/100 × orbital_yield`. Botón **🌙 Base lunar**
  en la sección lunas del modal de planeta; el panel de bases marca 🌙. Tests + 273 verdes. Con esto
  **SDD 37 queda completo** (superficie + orbital + lunar + tech-gating + producción/costo por-colonia).

## [1.29.0] - 2026-06-25

### 2026-06-25 — SDD 40: métricas del asistente por jugador + energía de nivelado por ranking
- **Uso del asistente por jugador**: cada consulta deja un evento **`advisor_ask`** en el journal
  (`game_journal_events_total{kind="advisor_ask"}`) → cruzable con todo. (Quién + qué modelo
  GPU/nube/free/pago ya viene de SDD 28 vía litellm `end_user`×`model`.)
- **Energía de nivelado por ranking** (`POST /players/me/advisor/assist-energy`, botón **⚡ Nivelar**):
  los **3 últimos** del ranking (entre pares de tu galaxia) **llenan el pool** de energía (nivelan
  rápido); el resto recibe **+100**, hasta **3 veces/día**. Capeado a `energy_max` y transitorio
  (regenera) → sin snowball/ventaja. Determinista (lo calcula el server, no el LLM). Migración
  aditiva (cupo diario). Tests + 271 verdes. Doc `docs/sdd-assistant-metrics-energy-assist.md`.

## [1.28.0] - 2026-06-25

### 2026-06-25 — Perfil: cambiar nick y contraseña (sin validar) + reset por OTP
- `POST /api/v1/players/me/profile` `{username?, password?}`: el jugador autenticado cambia su
  **nick** y/o **contraseña** sin validar email (valida unicidad del nick + longitudes). Devuelve un
  **token nuevo** (el nick viaja en el token, así seguís logueado). Panel **👤 Perfil** en la web.
- **Reset de contraseña olvidada vía OTP**: entrás con código por email (flujo passwordless ya
  existente) y cambiás la clave en el perfil. (Las cuentas invitado tienen email inexistente, así
  que su reset es solo por este endpoint estando logueadas.)

## [1.27.0] - 2026-06-25

### 2026-06-25 — Colonias: costo de construcción por-colonia + tipo visible
- Construir en una **colonia hostil** cuesta más (modificador `build_cost` de `compat` según
  habitabilidad) y en una **base orbital** cuesta ×1.5 (los robots construir es caro). El mundo natal
  queda igual.
- El panel **Bases y edificios** ahora marca cada base: ⭐ natal · 🪐 colonia · 🛰 orbital
  (`base_type` expuesto en `/players/me`). Tests + 268 verdes.

## [1.26.0] - 2026-06-25

### 2026-06-25 — SDD 37 v2: bases orbitales con robots (colonizar mundos letales)
- Tecnología **Robótica orbital** + tipo de base **orbital** (`Base_.base_type`): una estación con
  robots que **extrae recursos de mundos letales** (Mercurio sin atmósfera, etc.) sin habitarlos —
  nadie vive ahí, las naves van y vienen. Rinde fijo bajo (`orbital_yield` 0.4, sin importar
  habitabilidad) y cuesta más (`orbital_cost_mult`). `POST /colonize {mode:"orbital"}`; botón
  **🛰 Base orbital** en el modal de planeta (aparece si investigaste la tech). Migración aditiva
  (`base_type` default surface → no rompe partidas). Tests + 267 verdes.

## [1.25.0] - 2026-06-25

### 2026-06-25 — SDD 37: fundar colonias + tech para mundos hostiles + producción por-colonia
- **Tecnologías de colonización** (`antigravity`, `thermal_shielding`, `sealed_domes`): vencen
  gravedad/temperatura/atmósfera → desbloquean colonizar mundos antes imposibles. `compat()` ahora
  considera las techs investigadas (razas con tolerancias amplias necesitan menos). En el sistema
  solar **sin tech no se puede** colonizar nada no-natal (científicamente fiel).
- **`POST /colonize`**: funda una base en otro planeta (valida compat+galaxia+límite, consume
  transbordador + energía). Botón **🪐 Colonizar** en el modal de planeta.
- **Producción por-colonia**: cada mina rinde según el **planeta de su base** × habitabilidad (antes
  todo usaba el mundo natal). El mundo natal queda idéntico → no rompe partidas.
- Tests + e2e. Visión v2 (bases orbitales/lunares + robots + exploración + descuentos por raza)
  documentada en el SDD.

### 2026-06-25 — Eventos: el panel ahora muestra activos + pasados (2 días) + posibles
- `GET /events/feed` y el panel **📣 Eventos** muestran lo **activo ahora**, lo que **pasó** (≤2 días)
  y lo que **puede aparecer** (catálogo) → ya no queda vacío. Subida la frecuencia de aparición
  (25%/tick, cooldown 30 min) para que haya movimiento.

## [1.24.0] - 2026-06-24

### 2026-06-24 — SDD 37 v1: grafo de colonización (raza × planeta, read-only)
- `compat(race, planet)` determinista: a partir de los atributos del planeta (gravedad, temperatura,
  atmósfera, agua) y las `tolerances` de la raza, da **habitabilidad**, **veredicto**
  (🟢 ideal / 🟡 colonizable / 🟠 hostil / 🔒 imposible) y **modifiers** (prod/energía/costo) que
  tendría esa colonia, con el **por qué**. Cada raza es "great" en su mundo natal; otros mundos van
  de hostiles a imposibles (Mercurio sin atmósfera = imposible para todos; Venus imposible para
  terrícolas por el calor, pero great para venusianos).
- API `GET /colonize/options` (el grafo para tu raza/galaxia). La web muestra el veredicto en el
  modal de planeta. Data-driven (editar `tolerances` rebalancea). Bilingüe.
- Pendiente (con el usuario): fundar la colonia + aplicar los modifiers por-base (cambio estructural).
- Test: además, robustecido `test_npc_strategy_runs_in_tick` (postura válida en vez de exacta) para
  quitar un flake de orden entre tests.

## [1.23.0] - 2026-06-24

### 2026-06-24 — SDD 36: eventos dinámicos "happy hour" (implementado)
- Eventos globales temporales que se disparan en **horas aleatorias** desde el tick y aplican a
  todos mientras duran: **todo más barato** (build_cost ×0.5), **energía ×2**, **+50% producción**,
  **+30% ataque/defensa**, **soldados gratis** (una vez). Data-driven en `content/events.yaml`
  (rebalancear = editar YAML).
- Reusa el motor de multiplicadores: `effects.multiplier` apila el evento (prod/atk/def), la energía
  y el costo de construir lo leen perezosamente, y los free_units se acreditan una vez por jugador en
  `advance`. Modelos `WorldEvent`/`EventGrant` + migración. Scheduling determinista (RNG sembrable,
  uno a la vez + cooldown).
- API `GET /events/active` · `GET /events/catalog` · `POST /events/start/{key}` (admin). Panel web
  **📣 Eventos** con cuenta regresiva. Journal registra `world_event_started`. Bilingüe. 254 verdes.

## [1.22.0] - 2026-06-24

### 2026-06-24 — Asistente IA: ve el grafo COMPLETO y deduce (no solo keyword-match)
- El contexto del asistente ahora incluye **todo el grafo del juego** (todos los objetos con
  costo/requisitos/qué habilitan + todas las mecánicas), no solo los ~6 nodos que matcheaban por
  palabra. El prompt le pide **deducir** cruzando esos datos (prerequisitos, qué edificio habilita
  qué unidad, etc.). Así "sabe todo el juego" de verdad. `relevant` marca los nodos más cercanos a
  la pregunta y `blockers` da el cálculo exacto.
- **Aliases de retrieval** (`ALIASES`): términos del jugador (sinónimos/errores) encuentran el nodo
  correcto. Arregla "edificio contra inteligencia" → `counter_intel` (antes caía al fallback y
  recomendaba una mina de aluminio sin sentido); "espías" → `spy`, etc.

## [1.21.0] - 2026-06-24

### 2026-06-24 — Calculadora de ataque visible en el panel ⚔ Atacar
- Botón **📊 Calcular** en el panel de ataque: estima, para el objetivo cargado (id o tocando una
  base en el mapa), cuánto necesitás según **tu intel** — defensa estimada, poder requerido (margen
  2×) y por unidad cuántas llevar + pérdidas, con botón **usar** que llena el selector de unidades.
  Antes la calculadora (`/combat/plan`) solo estaba como "📊 planear" dentro del modal de planeta y
  únicamente para enemigos ya espiados → poco visible. Sin intel del objetivo, avisa "espialo primero".
  Bilingüe ES/EN.

## [1.20.0] - 2026-06-24

### 2026-06-24 — SDD 38: journal de eventos (medir todo + reproducir la partida)
- Modelo **`GameEvent`** append-only (orden total por `id`) + servicio `journal.record()` que en
  **un solo punto registra y mide**: agrega el evento y bumpea `game_journal_events_total{kind}`
  (Prometheus). Enganchado en onboarding, build, train, research, expedición, ataque (launch +
  battle_resolved), espionaje (spy_launched + intel_gathered). → **espionaje y combate ahora SÍ se
  miden en Grafana** (antes el gap), y queda el log para reproducir.
- API: `GET /journal` (tus acciones, en orden) y `GET /journal/export?format=yaml` (admin: toda la
  partida como YAML ordenado → "guardo todo" / replay). Doc `docs/sdd-event-journal-replay.md`.

### 2026-06-24 — Asistente IA: ahora entiende las MECÁNICAS del juego
- El corpus del asistente (grafo SDD 1) sumó **docs de reglas** (`mechanics_documents`): combate
  (sin capacidad de transporte: en un ataque mandás cualquier cantidad; el transbordador es para
  expediciones), flotas/viaje, expediciones, espionaje, energía, investigación — con números reales
  de la config. El asistente **detecta preguntas de mecánica** (cómo/cuántos/capacidad/funciona…) y
  responde la regla en vez de desviar a "qué construir". Antes, preguntar "cuántos militares entran
  en un transbordador" devolvía consejos de construcción.

### 2026-06-24 — SSE con heartbeat + UI de unidades más clara
- El stream de notificaciones (SSE) ahora manda un `: ping` cada ~15s sin tráfico → mantiene viva la
  conexión a través de proxies (p.ej. HAProxy corta a `timeout server` si no fluyen bytes; SSE no es
  upgrade, `timeout tunnel` no aplica). Evita la reconexión cada ~50s.
- El selector de ataque aclara el stat: "⚔ 8 de ataque c/u · tenés 1" (con tooltip) en vez del
  confuso "⚔8 · tenés 1".

## [1.19.0] - 2026-06-24

### 2026-06-24 — Panel de reportes de combate (qué pasó en cada batalla)
- Nueva tarjeta **⚔ Reportes de combate** que lee `GET /combat/reports`: por cada batalla muestra
  si **atacaste o te atacaron** y contra quién, **ganaste/perdiste**, **qué perdiste vos** y **qué
  perdió el otro**, **botín/saqueo**, los scores ⚔ vs 🛡 y la fecha. Antes solo se veía el evento
  público del mundo; ahora tenés el detalle (incl. cuando tu flota fue aniquilada y no volvió nada).
  Bilingüe ES/EN.

## [1.18.0] - 2026-06-24

### 2026-06-24 — UX: menú de ataque más fácil (sin escribir unidades a mano)
- El panel ⚔ Atacar ahora muestra un **selector por unidad** (un input de cantidad por cada unidad
  de ataque que tenés, con su ⚔ y "tenés N") en vez del texto libre `tank:5,...`.
- **Energía clara:** muestra `⚡ costo (tenés X)` con aviso si no alcanza (costo expuesto en el
  catálogo: `catalog.costs.attack_energy`, sin hardcodear).
- El plan 📊 ahora tiene botón **usar** por opción → autocompleta objetivo + cantidad en el menú de
  ataque. Click en una base del mapa muestra el nombre del objetivo y baja al panel. Bilingüe ES/EN.

### 2026-06-24 — SDD 37 diseñado: colonización (grafo raza × planeta)
- Doc `docs/sdd-colonization.md`: colonizar otros planetas con un **grafo raza×planeta** — cada
  planeta tiene atributos (ya existen, SDD 13) y cada raza sus `tolerances`; `compat(race,planet)`
  (pura) da `habitability`, gate `can_colonize` (algunas combinaciones imposibles) y **modifiers**
  (prod/energía/costo/defensa por colonia). `POST /colonize` + `GET /colonize/options` (la matriz/
  grafo de veredictos para tu raza). Solo especificación.

### 2026-06-24 — SDD 36 diseñado: eventos dinámicos ("happy hour")
- Doc `docs/sdd-dynamic-events.md`: eventos globales temporales en horas aleatorias (todo más barato,
  energía ×2, soldados gratis, +prod…) que **reusan el motor de multiplicadores** (boons/effects),
  se schedulean en el tick (RNG sembrable), viven en DB (`WorldEvent`, lectura lazy) y se muestran en
  un panel de anuncios dinámico con cuenta regresiva. `GET /events/active`. Solo especificación.

## [1.17.0] - 2026-06-24

### 2026-06-24 — SDD 34: calculadora de combate (determinista + grounded en intel)
- Servicio `combat_calc.py` con helpers **puros** (`loss_ratios`, `min_attack_power`,
  `units_for_power`, `defense_needed`) sobre la **misma fórmula** que `resolve_combat`.
- `POST /api/v1/combat/simulate` — calculadora determinista (mismo resultado que el combate real).
- `POST /api/v1/combat/plan` — plan contra una base real **estimando su defensa desde TU intel**
  (SDD 35): sin intel → "espiá primero"; con intel da defensa estimada, tu multiplicador de
  ataque efectivo, poder necesario (margen 2×) y por cada unidad cuántas llevar + pérdidas
  estimadas. No filtra el estado exacto del rival (usa la intel graduada).
- Web: botón **📊 planear** en el panel de intel (al lado de 🕵 espiar / ⚔ atacar) que muestra
  el plan en vivo. Bilingüe ES/EN.
- Tests: helpers vs la matriz del SDD, `simulate`==`resolve_combat`, plan requiere intel y la
  fuerza sugerida gana al simularla; e2e `test_combat_simulate_and_plan_e2e`. **242 verdes.**

## [1.16.0] - 2026-06-24

### 2026-06-24 — SDD 35: tecnologías, visión de alianza e intel en el asistente
- **Tecnologías** `espionage` (+40% poder de espías) y `counter_espionage` (+40% defensa de
  espionaje), data-driven en `content/technologies.yaml`; entran por el mismo `effects.multiplier`
  que ya usa `process_spy_missions` (espionage sube tu depth/baja detección; counter_espionage
  ofusca tu info y detecta intrusos). Aparecen solas en el panel 🔬 Investigación.
- **Visión de alianza (`shared_vision`) = red de espionaje compartida:** `GET /intel` fusiona tu
  intel con la de tus aliados (gana la mejor confianza por objetivo; la propia siempre pisa).
  Marcada `shared`/`via` en API y en la web (chip 🤝). Sin `shared_vision` la intel queda privada.
- **Asistente IA usa tu intel (grounded):** el contexto del LLM incluye un resumen de tu intel
  (depth/confianza/antigüedad/datos); el prompt le exige no inventar datos del rival y recomendar
  re-espiar si la intel es vieja/poco confiable.
- Tests: servicio (techs como multiplicador, pooling con/sin shared_vision) + e2e
  (`test_shared_vision_shares_intel_e2e`). **235 verdes.**

### 2026-06-24 — SDD 35 v1: UI web de intel (click → ver + espiar)
- En el modal de planeta, cada colonia enemiga muestra ahora la **intel guardada** (profundidad,
  confianza con color por antigüedad, "hace Xh", aviso ⚠ desactualizada) con los campos **graduados**
  que devuelve el server (score, ataque/defensa, minerales, torretas, edificios, unidades — en rangos o
  exacto según depth) + botones **🕵 espiar** y **⚔ atacar**. "🕵 espiar" pide cuántos espías y llama
  `POST /api/v1/spy`; la intel se recarga (`GET /api/v1/intel`) en cada refresh. Bilingüe ES/EN.
  Sin objetivo espiado → "sin intel — espialo para ver qué tiene" (solo info pública). Front-only
  sobre el backend ya testeado (e2e `test_spy_and_intel_e2e`).

## [1.15.0] - 2026-06-24

### 2026-06-24 — SDD 35 v1: espionaje e inteligencia (backend)
- Unidad **`spy`** + edificio **`counter_intel`**; modelos **`SpyMission`**/**`IntelReport`** + migración.
  Servicio `espionage.py`: `resolve_spy` (depth = spy/(spy+counter)), payload **graduado** (rangos→exacto
  según depth = ofuscación), `start_spy` + `process_spy_missions` (viaje → resuelve intel + detección/
  bajas + notifica → vuelven sobrevivientes), confianza con decay. API `POST /spy`, `GET /intel`,
  `GET /intel/{target}`. Tests servicio + e2e. **231 verdes.** Follow-up: UI web (click→intel),
  integración con calculadora de combate (SDD 34) y asistente.

### 2026-06-24 — SDD 35 diseñado: espionaje e inteligencia
- Doc `docs/sdd-espionage-intel.md`: espías + contraespías + edificio/tech de contraespionaje, con
  **fórmula** `depth = spy/(spy+counter)` (rendimientos decrecientes → mandar de más es al pedo) y
  detección. **Intel persistida por objetivo** (`IntelReport`), revelada **graduada** según depth
  (rangos→exacto = ofuscación) y que **se desactualiza** (confianza decae → seguir espiando). Se ve al
  clickear un player/NPC; alimenta la **calculadora de combate** (SDD 34) y al **asistente** (grounded,
  no inventa datos del rival). Solo especificación.

### 2026-06-24 — SDD 34 diseñado: estrategia de combate (fórmula + calculadora + IA)
- Doc `docs/sdd-combat-strategy.md`: documenta la **fórmula exacta** de `resolve_combat`
  (attack_score vs defense_score; multiplicadores boons×tech×alianza; flat defense de torretas;
  pérdidas proporcionales), la **matriz de stats** de unidades, y los **cálculos** para atacar/defender
  (fuerza mínima para ganar, pérdidas según margen 2-3×, defensa necesaria). Diseña una **calculadora**
  (`/combat/simulate` + `/combat/plan`, deterministas) y **cómo la IA lo sabe sin alucinar** (cálculo
  server-side + grounding, patrón SDD 1/2). Nota: `hp` aún no se usa. Solo especificación.

### 2026-06-24 — SDD 33 diseñado: seguridad (pods sin root + RBAC/sandbox + defensa IA)
- Doc `docs/sdd-security-hardening.md`: modelo de amenaza + estrategias. **Pods sin root**
  (Dockerfile `USER` + `securityContext`: runAsNonRoot/drop caps/seccomp/readOnlyRootFs), **RBAC
  mínimo** (`automountServiceAccountToken:false`, SA sin permisos), **NetworkPolicy** default-deny, y
  **vCluster** como aislamiento fuerte (futuro). Análisis del miedo "hablar con la IA → exploit": la
  IA del juego **no tiene tools** (texto + hack capeado + acciones NPC validadas + salida `textContent`
  sin XSS) → blast-radius bajo; el poder real está en los agentes de ops (hermes/holmes), separados.
  Solo especificación.

### 2026-06-24 — Resiliencia validada + fix nodeSelector Postgres (drill de apagado)
- **Drill de "apagar el nodo"** (cordon srv-t7910 + borrar pod Postgres): reveló que un PVC Longhorn
  **debe** fijarse a nodos Longhorn — si no, reagenda a un nodo sin Longhorn y cuelga
  (`AttachVolume ... node.longhorn.io not found`). **Fix:** `postgres.nodeSelector: {storage:
  rk1-longhorn}` en el chart. Re-drill OK: Postgres reagenda a un RK1 en ~40 s, **datos intactos**.
- **SDD 30** ampliado con el **blast-radius completo** de srv-t7910 (además del juego: KubeVirt VMs =
  control-planes de clústers anidados, vclusters de tenants, Longhorn, HAMI). **SDD 32** con el
  registro de ejecución + la lección del nodeSelector.

### 2026-06-24 — SDD 32 EJECUTADO: Postgres del juego migrado a Longhorn
- `galaxy-postgres` movido de `local-path` (node-local en srv-t7910) a **`longhorn`** (replicado).
  Procedimiento seguro: `pg_dump` verificado → **dry-run de restore en un Postgres Longhorn
  descartable** (players=10/tablas=22 OK) → PV viejo a `Retain` → recrear STS+PVC en Longhorn (API en
  0) → DROP SCHEMA + restore → verificado (players=10, tablas=22, alembic head) → API/tick reanudados,
  `/health` y datos OK. Resultado: si se apaga/pierde el nodo GPU, **Postgres reagenda y el juego
  sigue** (sólo la IA degrada a OpenRouter free, SDD 30). Cambio en `values-local` (gitignored).

### 2026-06-24 — SDD 31 + 32: HA/durabilidad de Postgres
- **SDD 31** (`docs/sdd-postgres-ha-cnpg.md`): HA real con **CloudNativePG** (primary+réplicas,
  failover en segundos, backups/PITR) — opción "pro"/proyecto; el juego apunta por `externalUrl`
  (cero código). Diseño.
- **SDD 32** (`docs/sdd-postgres-longhorn-migration.md`): **plan ejecutable** (runbook) para mover el
  Postgres del juego de `local-path` a **Longhorn** → reagenda al apagar el fierro. Backup→borrar→
  recrear→restore, con ventana, retención del PV viejo y rollback. Opción A, lista para ejecutar.

### 2026-06-24 — SDD 30 diseñado: mantenimiento/resiliencia (apagar el fierro GPU)
- Doc `docs/sdd-maintenance-resilience.md`: impacto de apagar `srv-t7910` (GPU/amd64). La **IA cae
  sola a OpenRouter free** (LiteLLM fallback + fallback del juego, ya implementado). **Punto crítico:**
  `galaxy-postgres-0` está en `local-path` sobre ese nodo → no reagenda → juego caído. **Fix:** mover
  Postgres a **Longhorn** (replicado) → reagenda y sobrevive. Runbook cordon/drain + backup; tabla
  "qué sobrevive". Solo especificación.

## [1.14.0] - 2026-06-24

### 2026-06-24 — SDD 29 v1: inteligencia estratégica de NPCs (cerebro de 2 capas)
- NPCs que **cada ~30 min leen el scoreboard de su galaxia** (score + crecimiento `delta`) y sus
  recursos → fijan una **postura** persistida (`aggressive`/`defensive`/`expand`/`raid`/`opportunist`)
  + objetivo, que **sesga la capa táctica** (LLM y reglas: prioriza atacar al objetivo). Campos nuevos
  en `Player` + migración. Capa estratégica medible por `npc:<nombre>` (SDD 28) y con **fallback** a la
  postura previa si el LLM falla (SDD 9). Config `npc_strategy_*`. Tests servicio + e2e. **226 verdes.**

### 2026-06-24 — SDD 29 diseñado: inteligencia estratégica de NPCs (cerebro de 2 capas)
- Doc `docs/sdd-npc-strategic-intelligence.md`: NPCs que **cada tanto leen el scoreboard de su galaxia
  + su trayectoria de recursos** y fijan una **postura** (agresivo/defensivo/expansión/raid) persistida,
  que sesga la capa táctica per-turn. Más inteligencia + más uso de GPU (medible por `npc:<nombre>`,
  SDD 28), con fallback a reglas (SDD 9). Solo especificación.

### 2026-06-24 — SDD 28: end_user verificado + DCGM-exporter (GPU física)
- LiteLLM: `enable_end_user_cost_tracking_prometheus_only: true` (vía Ansible) — sin él, `end_user`
  no aparecía. **Verificado**: tokens/spend/requests **por usuario** ya se loguean.
- **DCGM-exporter** en `infra-ai` (`make dcgm`, idempotente): utilización física real por placa
  (util%/VRAM/temp/watts), sin pasar por HAMI. Verificado (M4000 58 °C / P4 88 °C). Dashboard Grafana.

## [1.13.0] - 2026-06-24

### 2026-06-24 — SDD 28 v1: métricas de uso LLM por usuario (monetización) + GPU + dashboard
- **App**: `llm_chat(user=...)` manda el campo OpenAI `user` (asistente `player:<id>`, NPCs
  `npc:<id>`) → LiteLLM puebla `end_user` → tokens/requests/spend **por jugador y backend**
  (GPU/free/pago). **Dashboard Grafana** `llm-usage.json` (uso LLM por usuario + spend + fallbacks +
  GPU por placa vía HAMI). Tests del payload. 220 verdes.

### 2026-06-24 — SDD 28 diseñado: métricas de uso LLM por usuario + GPU en vivo
- Doc `docs/sdd-llm-usage-metrics.md`: cómo ver en **Grafana** el uso de GPU en tiempo real y
  **atribuir el uso de LLM por jugador** (tokens/requests/spend por `end_user` y backend —
  GPU/OpenRouter free/pago) para **monetizar**. Clave: LiteLLM ya emite Prometheus con `end_user`
  (tracking ON) → **solo falta que el juego pase `user` en cada llamada** (`app/services/llm.py`).
  GPU vía HAMI (vGPU por pod) + DCGM-exporter opcional (% cómputo). Solo especificación.

## [1.12.0] - 2026-06-24

### 2026-06-24 — /tech refleja el stack de IA real (GPU dual)
- `/tech`: la fila IA/LLM y el hardware ahora muestran el stack implementado — **LiteLLM → 2× Ollama
  (Tesla P4 + Quadro M4000, vGPU HAMI) con balanceo + fallback OpenRouter free**. ES/EN.

### 2026-06-24 — IA self-hosted vía LiteLLM + GPU dual (SDD 9 v2)
- **SDD 9 v2** (`docs/sdd-local-gpu-llm.md`): arquitectura final — un LiteLLM compartido enruta
  `local-gpu` a un **tier Ollama dual** (1 por placa: Tesla P4 + Quadro M4000, vía HAMI
  `use-gputype`) con `least_busy` + **fallback OpenRouter free** (`timeout: 8`). **Rockchip NPU
  descartado** (formato roto + lento). Documentada la **decisión técnica** (2 Ollama `gpu:1` vs 1
  `gpu:2`: PCIe sin NVLink, paralelismo por workers, aislamiento HAMI), el **benchmark**
  (`local-gpu` 0.9s caliente, JSON válido) y el **análisis de capacidad** (5-60 jugadores/juego →
  sizing `gpumem 3000`/`gpucores 40%`, `KEEP_ALIVE=24h`).
- **Deploy idempotente** en `infra-ai/infra`: rol `install-gpu-ollama` + `make gpu-ollama` (aislado);
  ruteo en el rol `install-litellm-proxy`. El juego apunta a `local-gpu` (env-only, `values-local`).

## [1.11.0] - 2026-06-24

### 2026-06-24 — /tech bilingüe ES/EN + ollama GPU dedicado (SDD 9)
- `/tech`: ahora **bilingüe** (toggle 🌐 ES/EN con dict + persistencia, sin CDNs). vCluster marcado
  como **(planeado)** — es futuro (igual que el bot hermes); el diagrama suma el path IA
  (LiteLLM → GPU/Rockchip/OpenRouter).
- `deploy/gpu-llm/ollama.yaml`: Ollama **dedicado** a online-game con el patrón HAMI correcto
  (`nvidia.com/gpu: 1` + caps por device `gpumem`/`gpucores`, **sin nodeSelector**, PVC `local-path`,
  Job idempotente de pull). Benchmark: **`llama3.2:3b` en GPU ~2-4s** (a la par de OpenRouter, pero
  self-hosted) vs Rockchip NPU ~30s — el GPU vale la pena para asistente y NPCs.

## [1.10.0] - 2026-06-24

### 2026-06-24 — SDD 13: `real`/`sources` en edificios y unidades
- `content/buildings.yaml` y `content/units.yaml`: cada edificio/unidad declara su **contraparte
  real** (`real`/`real_en`) + `sources` (NASA/IAEA/Wikipedia), como minerales y planetas. Expuesto y
  localizado en `GET /catalog`; el cliente web lo muestra en la guía in-game (Edificios/Unidades
  in-game ↔ real). Tests de contenido + e2e (ES/EN) + browser. **218 verdes** + browser.

## [1.9.0] - 2026-06-24

### 2026-06-24 — Página técnica /tech (PoC self-hosted + flujo de tráfico)
- `web/tech.html` + ruta `GET /tech`: página pública que explica el stack (k3s arm64 bare-metal,
  FastAPI API-first, Cilium Gateway API, cert-manager, Postgres/Redis, Kaniko/Argo in-cluster,
  Prometheus/Grafana) y el **flujo de tráfico** con un diagrama SVG inline (sin CDNs): Internet →
  **HAProxy (SNI passthrough)** → **VIP del Cilium Gateway** (termina TLS) → HTTPRoute → Service →
  Pod. Omite direccionamiento privado exacto (IPs LAN/hostnames) por seguridad. Test e2e. Topología
  verificada en vivo con `kubectl`.

### 2026-06-24 — SDD 27 diseñado: sección de Anuncios / "Lo que viene"
- Doc `docs/sdd-announcements.md`: sección pública **"📣 Anuncios / Lo que viene"** con anuncios
  **tipados** (`content/announcements.yaml`) en categorías (`release`/`incoming`/`spinoff`/`season`/
  `maintenance`) y `status` (`live`/`coming`/`planned`), bilingüe (SDD 4), servidos por
  `GET /announcements`. Categoría **`spinoff`** ([SDD 26](docs/sdd-spinoff-universes.md)) con
  `differences`/`standard_baseline`: explica qué trae cada universo y su diferencia con el estándar.
  **Solo especificación** (se implementa después; editar el SDD para cambiar el modelo).

## [1.8.0] - 2026-06-24

### 2026-06-24 — SDD 13 §4: refrigeración por temperatura (completa los multiplicadores físicos)
- `mean_temp_c` → **refrigeración**: temperaturas lejos del confort (frío o calor) **drenan** la
  regen de energía (nunca la suben), acotado al piso configurable. La regen efectiva ahora es
  base × insolación × temperatura. Ej.: Venus (mucho sol, 464 °C) ⇒ la penalización térmica
  compensa su alta insolación. Config `physics_comfort_temp_c`/`physics_temp_sensitivity`/
  `physics_temp_scale_c`. Tests unit + e2e (planeta extremo regenera menos energía). **215 verdes.**

## [1.7.0] - 2026-06-24

### 2026-06-24 — SDD 13 §4: multiplicadores físicos del planeta
- `app/services/physics.py`: **gravedad → tiempo de construcción** (más gravedad ⇒ build más lento)
  e **insolación → regen de energía** (más sol ⇒ más energía). **Opt-in** (`PHYSICS_ENABLED`) y
  **data-driven**, anclados a la Tierra=1.0 (off o sin datos ⇒ neutral) y **acotados**
  (`physics_min_mult`/`physics_max_mult`) para que extremos como Mercurio no rompan el balance.
  Sensibilidad configurable (`physics_gravity_sensitivity`/`physics_insolation_sensitivity`).
  Wireado en advance/build/train/research/expedición/ataque + display advisor/NPC. **Encendido en
  prod**. Tests unit + e2e (gravedad cambia el build; off ⇒ neutral). **212 verdes.**

## [1.6.0] - 2026-06-24

### 2026-06-24 — Deuda técnica de prod: secretos fuertes + locks distribuidos
- **Secretos fuertes en prod**: `Settings.weak_secrets()` detecta `JWT_SECRET`/`OTP_SECRET`
  default o cortos (<16 bytes); con `ENVIRONMENT=production` el **arranque aborta** si hay alguno
  débil (el pod no levanta → obliga a setear uno real); en dev solo avisa. OTP solo se exige cuando
  el login passwordless está activo (allowlist o mailer real). Tests `tests/test_secrets_guard.py`.
- **Locks distribuidos por jugador** (Redis): `player_lock()` (SET NX PX + release con check de token;
  degrada a no-op sin Redis o si Redis falla) + dependency `lock_current_player` aplicada a las
  acciones que gastan recursos (build/train/research/expedición/ataque/recall) → **serializa** los
  requests concurrentes del mismo jugador y evita doble-gasto; en contención devuelve **409**. Tests
  unit (`test_redis.py`) + e2e (409 con Redis simulado). **205 verdes.**

### 2026-06-24 — SDD 26 diseñado: universos spin-off (Star Trek / BSG / Star Wars)
- Doc `docs/sdd-spinoff-universes.md`: packs de datos **tipados** (mismo modelo de objetos del
  contenido) con mundos/naves/materiales **fieles al canon** de cada franquicia (`canon: fiction` +
  `universe` + `sources` de wikis). **Solo especificación** (es la fuente; se edita el SDD para
  cambiar datos; se implementa cuando se decida). Incluye **nota legal/IP** (fan/no-comercial; modo
  genérico recomendado para publicar). Selección de universo por galaxy instance/temporada (SDD 8/11/13).

## [1.5.0] - 2026-06-24

### 2026-06-24 — SDD 25 v1: catch-up del recién llegado (nivelar sin dar ventaja)
- `app/services/catchup.py` (hook en onboarding): a quien entra a una partida con ≥3 pares en su
  galaxia, lo lleva al **P40 del stock de minerales** de los pares (top-up, nunca por encima →
  sin ventaja), le da **energía full** y asegura **mina + torreta** (defensa; nada ofensivo).
  Config `catchup_*`. Tests `tests/test_catchup.py` (P40 < mediana, partida joven no aplica). **195 verdes.**

## [1.4.0] - 2026-06-24

### 2026-06-24 — SDD 13 v2: jerarquía `system` + exosistemas reales + nivel `speculative`
- `content/planets.yaml`: campo **`system`** por planeta (Sistema Solar / sistemas de Andrómeda),
  nueva región **`solar_neighborhood`** (`canon: real`) con **Proxima Centauri b** y **TRAPPIST-1e**
  (datos publicados + `sources` + `confidence: low`), y un planeta **`speculative`** (`nova_terra` +
  `rationale`). Aditivo (no se removió nada → no rompe jugadores existentes).
- `registry`: `system`/`rationale` se localizan (ES/EN). Modal de planeta muestra system/canon/
  confidence/rationale. Tests `tests/test_science.py`.

### 2026-06-24 — SDD 25 diseñado: catch-up del recién llegado (nivelar sin dar ventaja)
- Doc `docs/sdd-newcomer-catchup.md`: al entrar a una partida vieja, grant proporcional a días +
  baseline de pares (P40 de su galaxia, leyendo `PlayerStats`/score), **priorizando defensa**,
  capeado a ≤ baseline (equalizar, no boostear). Una vez por cuenta. En la cola.

## [1.3.0] - 2026-06-24

### 2026-06-24 — SDD 24: landing pública /game (bilingüe, social-share)
- `web/landing.html` (ES/EN, toggle 🌐) servida en **`GET /game`**: hero + features + modelo
  **Free / BYOD (open source, self-host + tu API key de LLM) / Paid (nada por ahora)** + CTA a jugar.
- **Open Graph / Twitter cards** con `PUBLIC_URL` inyectada (og:url/og:image absolutas) →
  `GET /og-image.png` (1200×630, generado con Playwright vía `scripts/capture_og.py`).
- Tests e2e (`/game` bilingüe + OG, `/og-image.png` png). config `public_url`.

### 2026-06-24 — SDD 23: `make release V=X.Y.Z` (corte de release con una sola fuente del número)
- `scripts/release.py` + target `make release`: valida SemVer + tree limpio, mueve el CHANGELOG
  `[Unreleased]`→`[X.Y.Z]`, setea `Chart.appVersion` + tag del build manifest, commit + `git tag`.
  `DRY=1` para dry-run; no hace push. Tests `tests/test_release.py` (5). **188 verdes.**

### 2026-06-24 — SDD 23 diseñado: estrategia de versionado (SemVer) + releases
- Doc `docs/sdd-versioning.md`: MAJOR.MINOR.PATCH, **versión por release (no por commit)**, los
  cambios de **solo env/config (allowlist) NO llevan versión ni rebuild**, tag de imagen = release,
  `git tag vX.Y.Z`, y flujo CHANGELOG[Unreleased]→[X.Y.Z]. Follow-up: `make release V=`. (Motivado
  por la ráfaga 0.2.0→1.2.3.)

### 2026-06-24 — fix(deps): aiosqlite en runtime (lo necesita el smoke --selftest)
- El smoke (SDD 22 capa 2) levanta la app en SQLite efímero → necesita `aiosqlite`, que estaba
  solo en `[dev]`. Agregado a las deps principales (es el driver default de dev; inofensivo en prod
  con Postgres). 2do falso positivo del gate, ya cubierto.

### 2026-06-24 — fix(packaging): `pip install .` instalaba un paquete incompleto (faltaba app.api)
- `pyproject` listaba `packages=["app","clients"]` (solo top-level) → la instalación no traía los
  subpaquetes (`app.api`, `app.services`, …). El runtime no lo notaba (corre desde el fuente), pero
  **rompió el initContainer smoke** (capa 2 de SDD 22) con `ModuleNotFoundError: app.api`. Fix:
  `[tool.setuptools.packages.find] include=["app*","clients*"]`. Además `scripts/smoke.py` ahora
  fuerza el fuente al `sys.path` (como uvicorn). **El gate capa 2 hizo su trabajo: frenó el rollout
  y el pod viejo siguió sirviendo (sin downtime)** — fue un falso positivo por este bug de packaging.

### 2026-06-24 — SDD 22 capa 2: initContainer smoke (gate de rollout) + doc completa
- **initContainer `smoke`** (opt-in `api.smokeInit.enabled`): corre `scripts/smoke.py --selftest`
  (app en SQLite efímero, sin tocar Postgres/Redis) **antes de migrar/servir**; si falla, el pod no
  arranca → el rollout queda frenado y los pods viejos siguen. Cierra la capa 2 del SDD 22.
- **SDD 22 documentado** a fondo: flujo build→upgrade→test, qué hace/qué NO, y la prueba real (el
  build de 1.2.0 se cortó por un test rojo y no publicó imagen). Capas 1+2+3 implementadas.

### 2026-06-24 — SDD 22 capa 1: gate de tests en el build (Dockerfile multi-stage)
- El `deploy/Dockerfile` ahora es **multi-stage** con un stage `test` que corre `pytest -q`
  (unit/e2e, browser excluido) **durante el build**; el `runtime` depende de él (`COPY --from=test`).
  → un build con tests rojos **falla y NO produce imagen** (Kaniko/docker, sin tocar el Workflow).
  Cierra la capa 1 del SDD 22 (no publicar una versión que no pasa la suite). Runtime queda lean.

### 2026-06-24 — SDD 22: tests del deploy (helm test + smoke) + i18n de errores (SDD 4)
- **i18n errores**: handler global traduce el `detail` de errores conocidos (auth/seguridad) a EN
  con `?lang=en`/`Accept-Language` (`app/core/i18n_errors.py`); la web manda `lang` en
  register/login/verify. Test `test_error_message_i18n_en`.
- **SDD 22 — tests del deploy** (`docs/sdd-deploy-testing.md`): 3 capas (CI/build, initContainer
  smoke, `helm test`). v1: `scripts/smoke.py` (health/catalog/register/me; `--selftest` levanta la
  app en SQLite) + `COPY scripts` en el Dockerfile + **`helm test`** hook
  (`templates/tests/smoke.yaml`) → `helm test galaxy`. Recomendado `helm upgrade --atomic` (rollback
  auto). Tests `tests/test_smoke_script.py`. **183 verdes.**
- Follow-up: step de pytest previo al build (Kaniko) + initContainer smoke opt-in + `--atomic` en el runbook.

### 2026-06-24 — i18n del server: notificaciones en EN (SDD 4)
- `GET /notifications?lang=en` (o `Accept-Language`) **re-renderiza** el mensaje desde `type`+`data`
  (`notifications.localize`): building/training/research/expedition/incoming_attack/battle/attacked/
  fleet_returned/season_end. Tipos sin data (npc_taunt/advisor_hack) o desconocidos → mensaje
  original. La web manda `lang` en `loadFeed`. Empty-state del feed también traducido (`tr('nofeed')`).
- Tests: `tests/test_notif_i18n.py` (3). **180 verdes.** Follow-up: errores (HTTPException) y el
  `outcome` de combate (códigos) si se quiere traducir también.

### 2026-06-24 — SDD 21 v1: presencia (quién está online) + métricas por usuario/galaxia
- **Presencia** (`app/services/presence.py`, Redis ZSET + fallback memoria): heartbeat en
  `/players/me`; `GET /public/online` (conteo) y `GET /admin/online` (lista de usernames, admin).
- **Métricas**: `game_online_players` + opt-in `game_player_online{player,galaxy}`
  (`metrics.perPlayer.enabled`, tope) → en Grafana filtrás por player/galaxy. Gauge con `clear()`
  para no dejar series stale.
- Tests: `tests/test_presence.py` (2) + e2e (`test_presence_online_endpoints`). **177 verdes.**
  El bot (hermes) ya puede preguntar `/admin/online` o PromQL `game_online_players`.

### 2026-06-24 — SDD 21 diseñado: presencia (quién está online) + métricas por usuario/galaxia
- Doc `docs/sdd-presence-dimensional-metrics.md`: presencia vía Redis (SSE + last-seen),
  `/public/online` (conteo) y `/admin/online` (lista, admin); label **`galaxy`** (seguro) y
  **`player`** (opt-in por cardinalidad) para filtrar en Grafana; cómo lo consulta el bot. En la cola.

### 2026-06-24 — i18n EN del cliente completo (SDD 4): toda la web traduce
- El toggle 🌐 ahora pasa a inglés **toda la UI del cliente**: pantalla de login/registro/OTP,
  onboarding, "tu imperio", tips, botones, y todos los strings generados en JS (alianzas, colas,
  mapa, ranking/temporada, planeta, chat, stream, estados vacíos, guía). Helper `tr()` + dict plano
  `s` (es/en) + `data-i18n-html`/`data-i18n-ph`; guía con array por idioma.
- Browser test `test_language_toggle_to_english` + **aislamiento del `.env`** en el server de los
  browser-tests (ALLOWED_EMAILS/ADMIN_EMAIL/MAIL_BACKEND por env) → herméticos. **16 browser verdes.**
- Pendiente (backend, aparte): texto **generado por el server** (notis/combate/errores) sigue en ES.

### 2026-06-23 — SDD 18 v1: GitHub Pages auto-generado desde los SDDs
- `scripts/build_site.py` (stdlib) genera `site/index.html` desde `docs/sdd-*.md` + CHANGELOG
  (features+estado+novedades+botón Jugar). **Guard de privacidad** que aborta si hay PII/secretos.
  `GAME_URL` por variable de repo (no hardcodeada). `.github/workflows/pages.yml` publica en cada
  push a main. Tests `tests/test_site.py` (4). **174 unit/e2e verdes.** Falta habilitar Pages
  (Settings → Pages → GitHub Actions) — 1 vez, manual.

### 2026-06-23 — SDD 19 v1.1: métricas de negocio + tick/LLM + dashboard Grafana
- **`game_events_total{kind}`** instrumentado en `stats.bump` (un solo punto) → cubre
  construcciones/entrenamientos/investigación/expediciones/ataques/batallas/minería/saqueo/pérdidas.
- **Tick**: `game_tick_duration_seconds` (histogram) + `game_tick_last_run_timestamp`.
- **LLM**: `game_llm_requests_total{status}` + `game_llm_latency_seconds` (en `llm_chat`).
- **Dashboard Grafana** (`deploy/helm/dashboards/online-game.json`) como ConfigMap opt-in
  (`metrics.grafanaDashboard.enabled`, label `grafana_dashboard` → sidecar de kube-prometheus-stack).
- Test `test_bump_increments_prometheus_events`. **170 unit/e2e verdes.**

### 2026-06-23 — SDD 19 v1: métricas Prometheus (/metrics) + ServiceMonitor
- **`/metrics`** (formato Prometheus, módulo stdlib `app/core/metrics.py`, sin deps): RED por ruta
  (path-template), `game_sse_connections` (conectados ahora), `game_players_total`,
  `game_signups_total{method}`, `game_logins_total{method}`. Middleware + instrumentación en
  auth/OTP/SSE.
- **No público**: `METRICS_TOKEN` (Secret) → `/metrics` exige Bearer; sin PII en labels (test).
- **Helm**: ServiceMonitor opt-in (`metrics.serviceMonitor.enabled`), Service con puerto `http`
  nombrado, `METRICS_TOKEN` por Secret. Para kube-prometheus-stack: label
  `release: kube-prometheus-stack`.
- Tests: `test_metrics_endpoint_and_no_pii`, `test_metrics_token_guard`. **169 unit/e2e verdes.**
- **Desplegado y verificado**: kube-prometheus-stack scrapea `galaxy-api` (`game_players_total`=6,
  RED, SSE). **PrometheusRule** opt-in con alertas (`OnlineGameSignup` → avisa altas vía
  Alertmanager→openclaw/Telegram, `OnlineGameApiDown`, `OnlineGameHighErrorRate`). PromQL para los
  bots en el SDD 19. (rev 18, imagen 0.6.0.)

### 2026-06-23 — Privacidad: nick neutro en alta OTP (no derivar del email) (SDD 20)
- El alta por OTP genera `comandante-<hex>` en vez de derivar el username del local-part del email
  (que lo exponía en el nombre público). `auth_otp._unique_username`. Test
  `test_otp_username_is_neutral_not_from_email`. **167 unit/e2e verdes.** Follow-up: endpoint de
  renombrado (requiere re-emitir el JWT). Incluye también el log INFO de envío de email (resend_id).

### 2026-06-23 — Seguridad: admin gate + rate-limit OTP + registro web por email; SDDs 20/usuarios
- **Gate de `/admin/*` (SDD 14 v2)**: `get_current_admin` (`Player.is_admin` + `ADMIN_EMAIL`).
  Antes `tick`/`season/close` los llamaba cualquier logueado. Migración aditiva `is_admin`
  (`server_default`). Sin `ADMIN_EMAIL` (dev/test) queda abierto como antes. e2e
  `test_admin_endpoints_gated`.
- **Rate-limit por IP en `/auth/request-code`** (`otp_rate_limit_per_min`, 429): defensa anti-abuso
  del endpoint (el envío ya estaba acotado por allowlist+cooldown). e2e `test_otp_request_rate_limited`.
- **Web alineada con la allowlist**: el form de registro ahora manda **email** (antes daba 403 al
  gatear register por email). `register()` envía email; login sigue user+pass. `is_admin` se siembra
  desde `ADMIN_EMAIL` al crear la cuenta (register + OTP).
- **SDD 20 — Usuarios** (`docs/sdd-users.md`): modelo `Player`, campos, e identidad **nickname
  público / email privado**. **SDD 10 ampliado**: estrategia de **Redis** (cache, no requiere
  backup) + runbook de recuperación. **Backlog**: i18n EN incompleto + nickname OTP no derivar del email.
- **166 unit/e2e verdes.**

### 2026-06-23 — Deploy: mailer Resend + OTP_SECRET vía Secret (entrega real de códigos)
- El chart ahora wirea el **envío de email** (SDD 6/14): `mail.backend`/`mail.from` (env) +
  `mail.resendApiKey`/`mail.otpSecret` **vía Secret** (`templates/secret.yaml` + `commonEnv`). Reusa
  el mismo proveedor que `bot-telegram` (**Resend**, dominio verificado). Cierra el blocker: antes
  `MAIL_BACKEND=console` no entregaba el código OTP. Ahora `request-code` envía de verdad.
- `OTP_SECRET` fuerte (no el default) por Secret. Datos reales en `values-local.yaml` (gitignored).

### 2026-06-23 — fix(seguridad): cerrar bypass de allowlist en /auth/register (SDD 14 v1.1)
- **Bug**: `/auth/register` (usuario+contraseña) NO respetaba la allowlist → cualquiera podía
  crear cuenta salteando el gate (solo el OTP estaba gateado). Detectado probando en vivo.
- **Fix**: register ahora exige `email` autorizado cuando hay allowlist (403 si falta/no está;
  201 si está). Da acceso a los permitidos **sin depender del mailer** (email+clave). Sin
  allowlist, registro abierto (dev) como antes.
- Tests (regla e2e que faltaba aplicar): `test_register_gated_by_allowlist` +
  `test_register_open_without_allowlist`. **164 unit/e2e verdes.**

### 2026-06-23 — SDD 19 diseñado: métricas Prometheus + dashboard Grafana
- Doc `docs/sdd-observability-metrics.md` (propuesto): `/metrics` (stdlib, sin dep) con RED de la
  API + métricas de negocio (construcciones/entrenamientos/investigación/expediciones/combate/altas/
  asistente), conectados en vivo (gauge de conexiones SSE), tick, LLM e infra. ServiceMonitor +
  dashboard Grafana versionado. Guard de cardinalidad/privacidad; `/metrics` no público. En la cola.

### 2026-06-23 — SDD 18 diseñado: GitHub Pages auto-generado desde los SDDs
- Doc `docs/sdd-github-pages.md` (propuesto, sin código aún): landing del juego en GitHub Pages
  generada por un script stdlib que lee `docs/sdd-*.md` + ROADMAP + CHANGELOG (auto-actualizable en
  cada push a `main` vía Action). URL del juego por variable de repo (no hardcodeada); guard de
  privacidad sobre el HTML. En la cola.

### 2026-06-23 — 🚀 Publicado: build Kaniko + upgrade + migraciones (SDD 15/16/17)
- **El juego está LIVE** detrás del dominio público con TLS Let's Encrypt **prod** válido, login
  OTP + allowlist (SDD 14) y asistente AI (OpenRouter free). Release `galaxy`, ns `online-game`.
- **SDD 15 — build Kaniko/Argo** (`docs/sdd-image-build-kaniko.md` + `deploy/build/online-game-kaniko.yaml`):
  build in-cluster arm64 desde `git`, push al registry interno. Reproducible.
- **SDD 16 — migraciones en deploy** (`docs/sdd-migrations-deploy.md`): el initContainer `migrate`
  corre `alembic upgrade head` antes de servir; aditivo e idempotente (no-op si no hay cambios),
  datos intactos (PVC, SDD 10). Guía expand/contract + rollback.
- **SDD 17 — runbook de upgrade** (`docs/sdd-deploy-upgrade.md`): build → `helm upgrade
  --set image.tag` → migraciones → smoke. Casos: cambió esquema / solo env / flip cert / allowlist.

### 2026-06-23 — Deploy: bootstrap reproducible del secret acme-dns (cert DNS-01)
- `deploy/gateway-tls/create-acme-dns-secret.sh` (idempotente, server-side apply) crea el secret
  `acme-dns-account` en `cert-manager` — el ÚNICO prerequisito que el chart no crea (un secret no
  va al repo en claro). `acme-dns-account.example.json` (placeholders, versionado) + el real
  `acme-dns-account.json` gitignored. Documentado en `deploy/gateway-tls/README.md` (proceso de
  emisión del cert). HAProxy/SNI-passthrough → VIP del LB del Gateway (sin IPs internas en el repo).

### 2026-06-23 — Deploy: chart con Gateway/Certificate/ClusterIssuer + values personales gitignored
- **Templates nuevos (genéricos, opt-in por values, aditivos):** `gateway.yaml` (Gateway dedicado
  cuando `gateway.create=true`, o reusar uno existente), `certificate.yaml` (Certificate público
  cuando `gateway.tls.enabled`), `clusterissuer.yaml` (Let's Encrypt staging+prod DNS-01/acme-dns
  cuando `letsencrypt.enabled`). No tocan `cluster-gateway` ni a otros tenants.
- **Privacidad (mismo concepto que `.env`):** los values con datos reales (dominio/IPs/email) van
  en `deploy/helm/values-*.yaml` **gitignored**; el repo solo lleva ejemplos genéricos con
  placeholders en `deploy/helm/examples/` (`remote.example.yaml`, perfiles local y remoto). El
  default de `values.yaml` quedó sin datos reales.
- Verificado: `helm lint` + `helm template` (default y ejemplo) OK.

### 2026-06-23 — SDD 14 v1: allowlist de altas (passwordless)
- Variante simple elegida: **`ALLOWED_EMAILS`** (env, lista por coma) gatea `/auth/request-code`
  — solo emails autorizados (o jugadores ya existentes) reciben código. Vacío = registro abierto.
  Salida uniforme (anti-enumeración); sigue passwordless (sin claves que repartir).
- `app/core/config.py` (`allowed_email_set`), `app/services/auth_otp.py` (gate). Emails reales en
  `.env`/`values-local.yaml` (gitignored), nunca en el repo.
- Tests: 3 servicio (`tests/test_auth_otp.py`) + 1 e2e + fixture autouse `_open_registration`.
  **162 unit/e2e verdes.** Doc `docs/sdd-admin-approval.md` (el panel/aprobación queda como v2).

### 2026-06-23 — Deploy: TLS público con cert-manager + Gateway API
- **Dónde va el dominio**: `gateway.host` del chart; el HTTPRoute liga por hostname al listener
  del Gateway. Comentario aclaratorio en `values.yaml`.
- **TLS (fuera del chart, en el Gateway compartido)**: `deploy/gateway-tls/` con ClusterIssuer
  Let's Encrypt (staging+prod, solver **DNS-01** por defecto — sirve detrás de NAT; HTTP-01 como
  alternativa), el listener HTTPS a agregar al Gateway (+ annotation
  `cert-manager.io/cluster-issuer` → el shim pide el cert solo) y README con pasos. Genérico/sin
  datos de infra. Nota de frente TCP/SNI-passthrough → backend a la VIP del LB del Gateway.

### 2026-06-23 — SDD 7 + SDD 9 implementados (v1): capacidad/autoscaling + LLM local en GPU
- **App (testeable):**
  - **Pool de DB tuneable** (SDD 7): `engine_kwargs()` aplica `pool_size`/`max_overflow`/
    `pool_timeout`/`pool_recycle`/`pool_pre_ping` en Postgres (SQLite intacto). El techo de
    conexiones es por réplica → de ahí PgBouncer a gran escala.
  - **Intervalo del SSE configurable** (SDD 7): `STREAM_INTERVAL` como default del stream;
    subirlo baja drásticamente la carga DB (el SSE pollea por conexión).
  - **Timeout del LLM configurable** (SDD 9): `LLM_TIMEOUT_SECONDS` (antes 20s fijo) corta la
    espera de la GPU serial y dispara el fallback (NPC→reglas, asistente→determinista).
  - **Rate-limit del asistente** (SDD 9): `/advisor/ask` limitado por jugador
    (`advisor_rate_limit_per_min`, 429 al pasarse) — protege la GPU del pico simultáneo.
- **Helm (SDD 7):** `api.resources`/`worker.resources` (requests/limits → el HPA necesita
  requests), **HPA** opt-in (`autoscaling.enabled`, CPU 70%, ignora `api.replicas`),
  **PodDisruptionBudget** opt-in, `topologySpreadConstraints`, y envs `STREAM_INTERVAL`/
  `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`/`LLM_TIMEOUT_SECONDS`. Verificado con `helm lint`/`template`.
- **Infra/ejemplos (SDD 9, fuera del chart):** `deploy/gpu-llm/` (Ollama en GPU + LiteLLM proxy
  con cola/fallback + README: topología, elección de modelo 3–4B/7B Q4, concurrencia serial).
- **Load test (SDD 7):** `tests/load/k6_ccu.js` + README con el modelo de cálculo de CCU
  (~0.8 rps/CCU) — no corre en CI.
- Tests: `tests/test_scaling.py` (4) + 1 e2e (rate-limit del asistente 429). **158 unit/e2e +
  15 browser verdes.**
- Follow-up: métrica custom rps/pod (KEDA), PgBouncer + réplicas de lectura, tick shardeado por
  galaxia (SDD 8), benchmark real de tok/s por modelo en P4/Maxwell.

### 2026-06-22 — SDD 13 implementado (v1): rigor científico del contenido
- **Propiedades físicas reales** por planeta en `content/planets.yaml` (`gravity_g`, `mean_temp_c`,
  `atmosphere`, `has_liquid_water`, `insolation`, `canon`, `sources` — NASA Fact Sheets). Sistema
  Solar = `real`; Andrómeda = `fiction`. Expuesto por `/catalog` y en el modal de planeta.
- **Restricciones físicas data-driven**: **aviones requieren atmósfera** (no en Mercurio) y
  **barcos requieren agua líquida** (solo Tierra) — gateado en `start_training`. `propulsion`
  descriptivo.
- Tests: `tests/test_science.py` (2) + 2 e2e. **153 unit/e2e + 15 browser verdes.**
- Follow-up: jerarquía sistema estelar + exosistemas reales (Proxima/TRAPPIST-1), nivel
  `speculative`, universos/spin-offs, multiplicadores físicos.

### 2026-06-22 — SDD 12 implementado (v1): métricas + historial + showcase público
- **`PlayerStats`** (contadores de por vida) incrementados en los procesadores existentes:
  batallas ganadas/perdidas, ataques, edificios, unidades, investigaciones, expediciones,
  minerales minados/saqueados/perdidos. Historial de temporadas desde el `HallOfFame` (SDD 11).
- **Endpoints públicos SIN auth** `/public/{stats,leaderboard,hall-of-fame,players/{username}}`:
  solo agregados + username (**nunca email**); perfil 404 si no existe.
- **Web**: showcase en la **página de login** (stats del universo + top-10), sin estar logueado.
- `app/services/stats.py` (`bump`/`leaderboard`/`global_stats`/`player_profile`). Migración aditiva.
- Tests: `tests/test_stats.py` (5) + 1 e2e (público/sin-email/404) + 1 browser. **149 unit/e2e +
  15 browser verdes.** Cierra el combo 11+8+12. Follow-up: cachear `/public/*` (SDD 7), backfill.

### 2026-06-22 — SDD 8 implementado (v1): límites de galaxia (shards con cupo)
- **`GalaxyInstance`** (shard con `capacity`) + `Player.galaxy_instance_id`. El onboarding asigna
  una instancia **abierta** del template elegido; al llenarse (`GALAXY_CAPACITY`, default 50) crea
  una nueva. Los **NPC son ambientales** (sin instancia, atacables desde cualquier shard).
- **Aislamiento humano↔humano**: no podés atacar a un jugador de **otra galaxia** y el scoreboard
  (`GET /players`) se **filtra a tu instancia** (+ NPCs). `GET /galaxies` lista instancias con cupo;
  `/players/me` expone `galaxy_instance`; el header de la web muestra tu galaxia.
- Backfill perezoso para cuentas legacy. Migración aditiva (FK nombrada para SQLite).
- Tests: `tests/test_galaxies.py` (5 servicio) + 2 e2e + 1 browser. **143 unit/e2e + 14 browser.**
- Follow-ups: NPCs por instancia, ranking/temporada por instancia, tick por shard (SDD 7).

### 2026-06-22 — SDD 11 implementado (v1): temporadas + Hall of Fame + newbie protection
- **Mundo persistente + temporadas**: modelo `Season` (abre/cierra en el tick), al cerrar toma
  foto del ranking → top-N al **`HallOfFame`** (persiste) y abre la siguiente; **el imperio no se
  borra**. Ranking de temporada **en vivo** por `player_score` (tabla `SeasonScore` acumulable =
  follow-up).
- **Newbie protection** (`Player.protected_until`): el onboarding te da escudo
  (`NEWBIE_PROTECTION_HOURS`, default 48 h); no se puede **atacar a un protegido**, y **atacar a un
  humano cancela tu propia protección** (opt-out); atacar NPCs no la afecta.
- **API**: `GET /seasons`, `/seasons/current/ranking`, `/seasons/hall-of-fame`,
  `POST /admin/season/close`; `/players/me` agrega `protected_until` + `season`.
- **Web**: card "📅 Temporada" (countdown + ranking + aviso de protección), i18n ES/EN.
- Config `SEASON_DAYS`/`SEASON_HALL_OF_FAME_TOP`/`NEWBIE_PROTECTION_HOURS`. Migración aditiva.
- Tests: `tests/test_seasons.py` (8 servicio) + 2 e2e + 1 browser; tests de combate existentes
  ajustados (la protección bloquea atacar novatos). **137 unit/e2e + 13 browser verdes.**

### ⏳ Pendiente de implementar (diseñado, con SDD) — al 2026-06-22
> Detalle y orden en [`ROADMAP.md`](ROADMAP.md). Cada uno entra con su test e2e + entrada acá.
- **SDD 11 — follow-ups**: `SeasonScore` acumulable, evento del mundo al cerrar, ligar temporada a
  galaxy instances (SDD 8). (v1 ya implementado.)
- **SDD 12 — follow-ups**: cachear `/public/*` en Redis, `career_points` all-time, backfill de
  contadores. (v1 ya implementado.)
- **SDD 13 — follow-ups**: jerarquía sistema estelar + exosistemas reales (Proxima/TRAPPIST-1),
  nivel `speculative`, universos/spin-offs, multiplicadores físicos. (v1 ya implementado.)
- **SDD 8 — follow-ups**: NPCs por instancia, ranking/temporada por instancia, tick por shard.
  (v1 ya implementado.)
- **SDD 7 — Capacidad y autoscaling** (`docs/sdd-capacity-autoscaling.md`): HPA + resource requests
  + PgBouncer; atacar `run_tick` O(N) y SSE.
- **SDD 9 — LLM local en GPU** (`docs/sdd-local-gpu-llm.md`): Ollama/LiteLLM en P4/Quadro,
  concurrencia serial + fallback, modelo local recomendado.
- **SDD 5 — Bot de Telegram** (`docs/sdd-telegram-bot.md`): ⛔ bloqueado, necesita `TELEGRAM_BOT_TOKEN` real.
- **SDD 10 — Durabilidad (follow-ups)**: backup offsite cifrado + PITR + runbook/drill de restore.
- **SDD 6 — Login (follow-ups)**: rate-limit por IP + entrega real de email + `OTP_SECRET` fuerte en deploy.
- **Deploy online real**: exponer (túnel/cloud) con Postgres + secretos fuertes (decisiones del usuario).
- **Backlog (sin SDD aún)**: tech `build_speed`, combate con `hp`/rondas, más galaxias/minerales premium.
- **Orden recomendado** (ver ROADMAP): **11 → 8 → 12** juntos (lifecycle + galaxy instances +
  métricas/público, comparten modelo); **13** en paralelo, incremental y data-only (empezar por el
  Sistema Solar real); **7 + 9** al armar el deploy; **5** cuando haya token; follow-ups 6/10 +
  deploy atados a publicar.

### 2026-06-22 — SDD 13 (diseño): rigor científico del contenido
- **[SDD 13](docs/sdd-scientific-accuracy.md)**: hacer científicamente correctos galaxias, planetas,
  lunas, materiales, instalaciones, naves y personal. Jerarquía real **Galaxia → sistema estelar →
  planeta → luna** (Sistema Solar real + sistemas reales de la Vía Láctea: Proxima Centauri,
  TRAPPIST-1 vía NASA Exoplanet Archive; se quitan los planetas ficticios de Andrómeda). Propiedades
  físicas (gravedad, atmósfera, agua, insolación, temperatura) con **fuentes citadas**;
  instalaciones/naves/unidades ancladas a tecnología/física reales (ISRU, fusión, propulsión) con
  restricciones (aviones solo con atmósfera, barcos solo con agua). Todo **data-driven**, aditivo.
  Incluye **niveles de canon** (`real`/`speculative`/`fiction`) para arrancar chico e ir inventando
  lo "aún no descubierto", y **universos/spin-offs** (tipo *The Expanse*) como packs de contenido
  seleccionables por partida — sin tocar código.
- En cola, solo diseño.

### 2026-06-22 — SDD 12 (diseño): métricas, historial de temporadas y showcase público
- **[SDD 12](docs/sdd-player-metrics-public.md)**: contadores de por vida por jugador
  (`PlayerStats`: batallas ganadas/perdidas, edificios, unidades, expediciones, minerales
  minados/gastados/saqueados…) incrementados en los procesadores existentes; **historial de
  temporadas** vía HoF (SDD 11); endpoints **públicos sin auth** `/public/{stats,leaderboard,
  hall-of-fame,players/{username}}` (solo agregados, sin email) y **showcase en la página de
  login** (leaderboard + stats del universo + perfiles). Cacheable (SDD 7). Depende del SDD 11.
- En cola, solo diseño.

### 2026-06-22 — SDD 11 (diseño): inicio y final del juego (mundo persistente + temporadas)
- Investigado StarKingdoms (rondas con inicio/fin, tick, newbie protection, ranking por networth,
  Hall of Fame persistente, free-to-play + Premium cosmético ~US$2.33/mes — no pay-to-win).
- Decisión del usuario: **híbrido** — mundo persistente + **temporadas** (clímax, ganadores,
  **Hall of Fame + insignias cosméticas** que persisten, **sin wipe** del imperio) + **newbie
  protection**. **Monetización: fuera de alcance por ahora.**
- **[SDD 11](docs/sdd-game-lifecycle.md)**: modelo `Season`/`SeasonScore`/`HallOfFame` +
  `Player.protected_until`, apertura/cierre de temporada en el tick, puntos de temporada (delta de
  score + bonus), endpoints `/seasons*`, e interacción con galaxy instances (SDD 8). Solo diseño.

### 2026-06-22 — SDD 6 implementado: login passwordless por email + código OTP
- **Passwordless (código siempre)**: `POST /auth/request-code` (respuesta uniforme anti-enumeración)
  + `POST /auth/verify-code` → JWT (signup = login: crea el `Player` si el email es nuevo). El JWT
  mantiene la sesión, así que no pide código en cada visita.
- **Servicio** `app/services/auth_otp.py` adaptando el patrón de `bot-telegram` a SQLAlchemy async:
  CSPRNG (`secrets`), código guardado como **HMAC-SHA256(code, OTP_SECRET)** (nunca en claro), TTL,
  máx intentos, **compare constant-time**, cooldown de reenvío. Modelo `EmailOtp` + `Player.email`
  (migración aditiva).
- **Mailer agnóstico sin deps** `app/services/mailer.py`: `console` (default, loguea el código —
  dev/CI sin SMTP) / `smtp` (stdlib) / `resend` (httpx). Email del código **i18n** (ES/EN).
- **Dev no se fuerza**: el login **usuario+contraseña** actual se mantiene (`/auth/login`,
  `/auth/register`) para dev/CLI/tests/NPC.
- **Web**: sección "Entrar con email (sin contraseña)" en la card de login.
- Tests: `tests/test_auth_otp.py` (7) + 3 e2e (`request/verify`, uniforme/inválido, código malo)
  + 1 browser. 128 unit/e2e + 12 browser verdes. SDD 6 actualizado con decisiones e impl.

### 2026-06-22 — Durabilidad: Postgres con PVC + backup (impl SDD 10)
- **Fix de pérdida de datos**: el Postgres del chart pasó de `Deployment` **sin volumen** a
  **`StatefulSet` con `volumeClaimTemplates` (PVC)** en `/var/lib/postgresql/data` (`PGDATA` en
  subdir para evitar `lost+found`) + `readinessProbe` `pg_isready`. **El PVC sobrevive a que el pod
  muera** → ya no se pierde la base. (`deploy/helm/templates/datastores.yaml`)
- **Knobs** (`values.yaml`): `postgres.persistence.{enabled,size,storageClass}` (default on, 8Gi).
  `persistence.enabled=false` → `emptyDir` (solo pruebas).
- **Postgres externo**: `postgres.externalUrl` + `postgres.enabled=false` (managed/operador con
  PITR); `dbUrl` lo honra (`_helpers.tpl`).
- **Backup opt-in**: `backup.enabled` → CronJob `pg_dump -Fc` a un PVC con retención
  (`postgres-backup-cronjob.yaml`). Offsite/cifrado y PITR quedan como follow-up.
- Verificado con `helm lint` + `helm template` (persistente / emptyDir / DB externa / backup on).
  SDD 10 actualizado con estado de implementación.

### 2026-06-22 — SDD 10 (diseño): durabilidad, backup y restore
- **[SDD 10](docs/sdd-durability-backup-restore.md)**: cómo no perder datos si un pod muere.
  🔴 **Hallazgo bloqueante**: el Postgres del chart (`datastores.yaml`) corre como `Deployment`
  **sin PVC** → si el pod se reprograma, **se pierde toda la base**. Fix: `StatefulSet`+PVC (o
  `postgres.enabled=false` + Postgres gestionado/operador con PITR). Backups offsite cifrados
  (`pg_dump` CronJob + retención, o WAL/PITR) y **runbook de restore probado** (RPO/RTO).
- Aclarado por qué la **app ya es crash-safe**: API stateless + estado lazy por timestamp
  (se reconstruye al leer) + transacciones atómicas + Redis como cache reconstruible. La
  durabilidad depende solo de Postgres. Solo diseño.

### 2026-06-22 — SDD 7/8/9 (diseño): escalado, límites de galaxia y LLM local en GPU
- **[SDD 7 — Capacidad y autoscaling](docs/sdd-capacity-autoscaling.md)**: metodología para
  estimar CCU, HPA + resource requests + PgBouncer; identifica los cuellos reales (el `run_tick`
  O(N) global y el SSE que abre sesión DB por poll) y cómo atacarlos.
- **[SDD 8 — Límites de galaxia](docs/sdd-galaxy-limits.md)**: `GalaxyInstance` con `capacity`
  (shard del mundo) para que una partida no colapse; tick e interacciones por instancia —
  también es la unidad de sharding del SDD 7.
- **[SDD 9 — LLM local en GPU](docs/sdd-local-gpu-llm.md)**: servir NPCs/asistente desde GPU local
  (Tesla P4 / Quadro Maxwell) con Ollama/LiteLLM; una GPU = serial (se encola, con fallback),
  reserva por pod, y qué modelo local conviene (Qwen2.5 3–7B JSON/ES-EN). La app ya es agnóstica;
  es operación + config.
- Solo diseño; sin código. Implementación tras decisiones de deploy.

### 2026-06-22 — SDD 6 (diseño): login para producción (email + código OTP)
- Diseño del login passwordless por **email + código** para abrir al público, **adaptando el
  patrón OTP de `bot-telegram`** (`src/otp.py`: CSPRNG, HMAC-SHA256 con salt, TTL, máx intentos,
  compare constant-time, respuestas uniformes anti-enumeración) a **SQLAlchemy async** (modelo
  `EmailOtp` + `Player.email`), con **mailer agnóstico sin deps nuevas** (console/SMTP stdlib/
  Resend httpx) y rate-limit. Convive con el login username+password actual (no rompe).
  [docs/sdd-auth-login.md](docs/sdd-auth-login.md). Solo diseño; la entrega real de email se
  verifica en deploy.

### 2026-06-22 — SDD 5 (diseño): bot de Telegram
- Diseño del bot como **cliente delgado** sobre `/api/v1`: long-poll con `httpx` (sin deps
  nuevas), opt-in por `TELEGRAM_BOT_TOKEN`, comandos `/login /me /build /train /attack /research`,
  push de notificaciones, tests con transporte mockeado. [docs/sdd-telegram-bot.md](docs/sdd-telegram-bot.md).
- **Implementación bloqueada** hasta tener un token real (verificación end-to-end). Solo diseño.

### 2026-06-22 — SDD 4: i18n del juego (ES/EN)
- **Contenido data-driven bilingüe**: cada item de `content/*.yaml` suma `name_en`/
  `description_en`/`real_en` (ES sigue siendo el default; si falta el `_en`, cae al ES).
  `personality`/`taunts` de las NPC quedan en su idioma (son model-facing, no UI).
- **API**: `GET /catalog?lang=en|es` (gana sobre `Accept-Language`; default `es`); cache Redis
  **por idioma** (`catalog:v1:<lang>`). Helpers puros `localize`/`localize_catalog`/`normalize_lang`
  en el registry. Planetas anidados en `galaxies` también se localizan; las claves `*_en` se quitan
  de la respuesta.
- **Web**: toggle **🌐 ES/EN** (persistido en `localStorage`) que recarga el catálogo en el idioma
  y traduce el chrome (títulos de panel vía `data-panel`, botones vía `data-i18n`, placeholder del
  asistente). Cobertura parcial del chrome (resto de textos fijos = follow-up).
- Tests: `tests/test_i18n.py` (unit) + e2e `test_catalog_i18n` + browser `test_language_toggle_en_es`.
  Diseño en [docs/sdd-i18n.md](docs/sdd-i18n.md). Sin migraciones ni deps.

### 2026-06-22 — SDD 3: paneles de la web colapsables (front-only)
- Cada card tiene un `data-panel` estable; un clic en su título lo **pliega a la cabecera**
  (`.collapsed` oculta todo menos el `h2` por CSS, sin reestructurar el HTML). Caret ▾/▸.
- Estado **persistido en `localStorage`** (`panels.collapsed`) → sobrevive recargas. Botones
  globales **⊟ plegar todo / ⊞ expandir todo**.
- Sin API ni backend (pura presentación, coherente con API-first). Diseño en
  [docs/sdd-web-panels.md](docs/sdd-web-panels.md).
- Test de navegador `test_panels_collapse_persist_and_expand` (colapsa, recarga, expande, todo).

### 2026-06-22 — Asistente: claridad hack vs. acción + mina del mineral nombrado
- **Bug**: pedir "mina de silicio" no daba una sugerencia con el mineral, así que se construía
  con el mineral viejo del dropdown (p.ej. hierro). Ahora el asistente detecta el mineral
  nombrado (ES/EN) y ofrece **"Construir mina de <silicio>"** que lleva `target_mineral`; al
  tocarla, el form de build se **sincroniza** (edificio+mineral) para que lo que ves sea lo que
  se construye.
- **UX**: la card separa **Acciones** (gastan recursos) del **Hack** (te *regala* el material/
  energía que falta; no construye), con texto explicativo y nombres legibles — antes parecían dos
  menús sueltos y no se entendía que el hack te da el material.
- Test de servicio `test_ask_named_mineral_suggests_that_mine` + browser actualizado.

### 2026-06-22 — SDD 2 implementado: asistente AI personal + hack (full-API)
- **`app/services/advisor.py`**: consejero por jugador que se apoya en el grafo (SDD 1) y en la
  **misma LLM agnóstica que las NPC** (con **fallback determinista** a los blockers si no hay
  LLM/falla). `ask()` usa **RAG `retrieve`** para enfocar la respuesta y devuelve prosa +
  `BlockerReport` + `suggestions`. Las **suggestions se generan deterministas** del análisis
  (siempre acciones válidas: build/train/research) — la LLM solo redacta.
- **Hack de emergencia** `grant_hack()`: otorga el **faltante mínimo** (minerales/energía, nunca
  unidades/ataques) para desbloquear un objetivo; **cap diario** (default 3) con **reset lazy en
  `Player`** (`assistant_hacks_used`/`assistant_hacks_reset_at`, sin cron/Redis). 4º del día → 429;
  objetivo ya construible → 400; emite notificación privada.
- **LLM compartido**: se extrajo el transporte a **`app/services/llm.py`** (`llm_chat`), usado
  por NPC y asistente (sin duplicar; tests del NPC siguen verdes).
- **Endpoints**: `POST /players/me/advisor/ask`, `POST /players/me/advisor/hack`,
  `GET /players/me/advisor/messages`. Modelo `AdvisorMessage` + migración Alembic aditiva.
- **Web**: card "🧠 Asistente AI" (preguntar, sugerencias de un clic, botón de hack N/3).
- Tests: `tests/test_advisor.py` (4 servicio) + 2 e2e (`ask`/`hack` con budget→429) + 1 browser.
  SDD 2 actualizado (suggestions deterministas). 112 unit/e2e + 9 browser verdes.

### 2026-06-22 — SDD 1 implementado: grafo de dependencias + RAG (full-API)
- **`app/services/depgraph.py`** (puro, sin DB/red): construye el grafo data-driven desde
  `content/*.yaml` y expone consultas deterministas — `prerequisites`, `mineral_sources`
  (mina local / expedición / loot / comercio; los minerales premium se marcan como
  *importados* porque no están en la abundancia de ningún planeta), `analyze`/`BlockerReport`
  (qué falta y **cuánto** — el `need-have` que consumirá el "hack" del SDD 2) y `build_graph`.
- **RAG ligero, sin dependencias nuevas**: `graph_documents` serializa el grafo en documentos
  cortos y `retrieve(query, k)` rankea los relevantes por score léxico **con sinónimos ES/EN**
  (fábrica↔factory, tanque↔tank, hierro↔iron…). Pensado para que la NPC/asistente LLM reciban
  solo los trozos útiles. (Backend de embeddings opcional con fallback léxico, igual patrón que
  el brain LLM — diseñado en el SDD, no implementado aún.)
- **Endpoints full-API** (sin auth, cacheables como `/catalog`): `GET /catalog/graph`,
  `GET /catalog/graph/docs`, `GET /catalog/graph/search?q=&k=`. Raza/planeta inválidos → 404.
- Schemas `Cost`/`Source`/`Blocker`/`BlockerReport` en `app/schemas`.
- Tests: `tests/test_depgraph.py` (10 unit puros) + e2e `test_catalog_graph` y
  `test_catalog_graph_docs_and_search`. SDD actualizado con la sección RAG y el principio
  full-API. Próximo: SDD 2 (asistente) sobre esta base.

### 2026-06-22 — Fix web: "marcar leídas" ahora vacía el feed
- El feed de 🔔 Notificaciones se renderiza desde la API (`GET /notifications?unread=true`) en
  cada `refresh()`; antes era un log de solo-escritura que el stream SSE iba acumulando en el
  DOM y **nunca se limpiaba**, así que "marcar leídas" bajaba el contador pero las notis seguían
  visibles. Ahora muestra solo las no leídas y al marcarlas queda "sin notificaciones sin leer".
- El backend ya marcaba bien (`POST /notifications/read` + filtro `unread`); el bug era de front.
- Test de navegador `test_mark_read_clears_notifications_feed` (mockea el endpoint para ser
  determinista). El contrato del backend sigue cubierto por `test_building_completion_notifies_and_mark_read`.

### 2026-06-22 — Diseño: asistente AI personal + grafo de dependencias (SDDs)
- **[SDD 1 — Grafo de dependencias](docs/sdd-dependency-graph.md)**: modelo data-driven
  (minerales→minas→edificios→unidades→tecnologías→efectos) con consultas deterministas
  (`prerequisites`, `mineral_sources`, `analyze`/blockers) y endpoint `GET /catalog/graph`. Es el
  *skill*/grounding del asistente; razona sin LLM (fallback) y sin depender de Redis.
- **[SDD 2 — Asistente AI personal](docs/sdd-ai-assistant.md)**: consejero por jugador que usa el
  grafo + el **mismo LLM que las NPC** (agnóstico, con fallback) para decirte *qué te falta y
  cómo conseguirlo* y sugerir acciones de un clic; incluye un **"hack" de emergencia** que otorga
  el faltante mínimo, acotado a **3/día** (contador lazy en `Player`, sin cron/Redis).
- ROADMAP actualizado: asistente AI + **i18n del juego (ES/EN)** (contenido/UI, no docs/SDDs).
- Solo documentación de diseño (sin código todavía); la implementación entrará con sus tests e2e.

### 2026-06-21 — NPCs: estrategia (taunts + rivalidad + few-shot)
- **Taunts in-character**: cuando una NPC ataca a un **humano** le manda una notificación con
  una frase de su raza (al despachar, y otra al ganar/perder). Data-driven: `taunts.{attack,
  win,lose}` por raza en `content/races.yaml`. No-op en humano→x y NPC↔NPC. Llega por el feed
  de notificaciones + SSE + sonido, sin tocar el front.
- **Rivalidad dinámica**: entre las bases que claramente puede vencer, la NPC (rule brain)
  prioriza al **humano con más score** (las NPC se coordinan contra el líder); si no hay
  humano batible, pega a la base más débil. El `state` del LLM ahora marca `enemies[].is_human`
  y el prompt instruye lo mismo.
- **Few-shot** en el prompt LLM (formato + prioridades) para decisiones más consistentes.
- Tests de servicio: taunt al humano atacado, y que el rule brain ataca al humano líder
  cuando hay varios batibles. Sin dependencias nuevas (Python + YAML).

### 2026-06-21 — Helm: LLM agnóstico del proveedor
- El chart ahora expone `llm.baseUrl` / `llm.model` / `llm.apiKey` / `llm.jsonMode` y los pasa
  como `LLM_*` a la API y al worker (la key vía Secret). Permite apuntar las NPC a cualquier
  endpoint OpenAI-compatible (OpenRouter, LiteLLM, Ollama, vLLM) **sin que el chart levante
  ningún LLM** — eso queda en tu infra. `openrouter.*` sigue como fallback/compat.
- `secret.yaml` crea el Secret si hay `llm.apiKey` y/o `openrouter.apiKey`. README +
  `values-local.example.yaml` actualizados. Verificado con `helm lint` + `helm template`.

### 2026-06-21 — NPCs LLM: proveedor agnóstico (OpenRouter/LiteLLM/Ollama) + JSON mode
- El cerebro LLM ahora habla con **cualquier endpoint OpenAI-compatible** vía `LLM_BASE_URL` /
  `LLM_MODEL` / `LLM_API_KEY` (con fallback a los `OPENROUTER_*` para no romper configs viejas).
  Permite apuntar a **Ollama** (modelo local/GPU), **LiteLLM** (router) o **vLLM** sin tocar código.
- `_openrouter_decide` → `_llm_decide`; usa propiedades resueltas `settings.llm_url/llm_model_name/llm_key`.
- **JSON mode**: pide `response_format=json_object` (`LLM_JSON_MODE=true`, default) → respuestas
  parse-safe; configurable por si el server no lo soporta.
- Log de arranque muestra el proveedor/modelo cuando `NPC_BRAIN=llm`.
- Tests de servicio: resolución de settings (LLM_* gana, fallback a OPENROUTER_*) y que
  `_llm_decide` postea al endpoint configurado con JSON mode (sin red). Docs (.env.example,
  CLAUDE.md, development.md) con recetas para OpenRouter/Ollama/LiteLLM.

### 2026-06-21 — Web: sonidos de eventos
- Beeps con WebAudio (sin archivos de audio) al llegar notificaciones por SSE; tono distinto
  por tipo (ataque/ reporte/ expedición). Toggle 🔊/🔇 en el header, preferencia persistida en
  `localStorage`; el `AudioContext` se crea/reanuda con el gesto del usuario.
- e2e de navegador: el toggle cambia el ícono, persiste la preferencia y expone `playBeep`.

### 2026-06-21 — Eventos del mundo
- Nuevo endpoint `GET /api/v1/world/events`: feed público de la galaxia (batallas resueltas
  con nombres + resultado, y alianzas formadas), ordenado del más nuevo al más viejo. Sin
  modelo nuevo: se deriva de `CombatLog` + `Alliance` (servicio `app/services/world.py`).
- Web: tarjeta **🌍 Eventos del mundo** en la columna derecha, refrescada cada 4s.
- e2e: el feed muestra la alianza formada y la batalla (ambos jugadores + tipos battle/alliance)
  + caso de error (sin auth → 401) + test de navegador. Screenshot `09-world.png`.

### 2026-06-21 — Chat de alianza
- Nuevo modelo `AllianceMessage` (+ migración) y servicio `post_message`/`list_messages`
  (solo miembros). Endpoints `POST /api/v1/alliances/messages` y `GET .../messages`
  (declarados antes de `/{alliance_id}` para no chocar con el path param).
- Web: tarjeta **💬 Chat de alianza** (aparece al estar en una alianza); feed con autoscroll,
  marca tus mensajes "(vos)", input que sobrevive al refresh de 4s (card propia).
- e2e: chat entre dos miembros (orden viejos→nuevos, resuelve `sender_username`) + caso de
  error (sin alianza no podés leer ni postear) + test de navegador. Screenshot `08-chat.png`.

### 2026-06-21 — Web: detalle de planeta (modal)
- Click en un planeta del mapa → modal con **abundancia mineral** (barras por mineral, ricos en
  verde / pobres en ámbar, con el multiplicador de minas), **lunas** y **colonias** del planeta
  (con acceso directo a "⚔ atacar" enemigos). Cierra con ✕ o Escape. Todo data-driven desde
  `catalog` (sin backend nuevo).
- e2e de navegador: abre el detalle de la Tierra y verifica abundancia/lunas/colonias y el
  cierre. Screenshot `07-planet.png`.
- Fix CSS: `.modal.hidden` para que el overlay oculto no tape la pantalla (bloqueaba clicks).

### 2026-06-21 — Web: naves viajando + mapa por galaxia
- **Flotas en tránsito** ("naves viajando"): nueva sección en el mapa que dibuja cada flota en
  vuelo como una nave que se desplaza por su trayecto, con ETA en vivo:
  - 🚀 ataque saliente (origen → destino) · ↩ flota volviendo · 🛰 expedición a una luna ·
    ☄ ataque entrante (fog of war: origen `???`).
  - El progreso es exacto sin tocar el backend: para ataques deriva la duración de un tramo de
    `returns_at − arrives_at`; para expediciones usa `duration_seconds` del catálogo; para
    entrantes (solo `arrives_at`) hace fallback midiendo desde que se ve. La nave interpola
    suave (`transition: left`) entre los samples de 1s.
- **Mapa agrupado por galaxia**: usa `catalog.galaxies` (Vía Láctea + Andrómeda), resalta la
  galaxia donde estás y atenúa el resto. Orbes con color para todos los planetas
  (mercury/vega_prime/nyx) y fallback para nuevos.
- e2e de navegador (`tests/browser/test_ui.py`): inyecta el shape real de la API
  (`missions_outgoing`/`expeditions`/`missions_incoming`) y verifica que se renderiza una nave
  por tramo, ubicada al 50% del trayecto, con origen→destino resueltos por planeta; + caso
  vacío ("sin flotas en vuelo", sin naves sueltas). Screenshot `06-transit.png`.

### 2026-06-20 — make run mata el server viejo antes de arrancar
- `make run`/`run-lan` hacen un `pkill` del uvicorn previo antes de levantar, para no quedar
  con **dos servers en el mismo puerto** (causa real de 500s al jugar local: el server viejo
  servía el 8099 con un `game.db` ya borrado/reseteado por debajo). Patrón `[u]vicorn` para que
  `pkill` no se mate a sí mismo. `make stop` usa el mismo patrón.

### 2026-06-20 — Expuesto vía Gateway API (Cilium)
- Chart: `HTTPRoute` opcional (`--set gateway.enabled=true`, host/gateway configurables) para
  exponer la API por un Gateway (ej. Cilium). Desplegado: el juego queda en
  `http://online-game.cluster.home/`. Verificado end-to-end por el gateway (health/register/web).

### 2026-06-20 — Desplegado en k3s (ARM64) ✅
- Imagen construida con **Kaniko** in-cluster desde el repo público → `registry.registry:5000`,
  arquitectura ARM64. Helm chart desplegado en namespace `online-game` (API + Postgres + Redis +
  initContainer de migraciones). Verificado: `/health` `db=postgres`, register/onboard OK, web sirve.
- Chart: **`nodeSelector` configurable** (cluster mixto / imagen single-arch). Aprendizajes del
  deploy real: pods en el nodo amd64 daban `exec format error` (→ fijar arch), y un nodo no
  resolvía el registry interno (→ fijar a un nodo bueno o arreglar `registries.yaml`).

### 2026-06-20 — Fix Dockerfile (build de imagen)
- El Dockerfile hacía `pip install .` con solo `pyproject.toml` copiado → fallaba
  (`package directory 'app' does not exist`). Ahora copia `app/` y `clients/` antes de instalar.
  Lo detectó el build real con **Kaniko** en el cluster (el path de Docker no estaba cubierto
  por los tests, que usan `pip install -e` con el código completo).

### 2026-06-20 — Deploy en k8s: OpenRouter en el chart + imagen multi-arch por CI
- Helm chart: soporte de **OpenRouter** (token como `Secret` vía `--set openrouter.apiKey`,
  no se commitea; si está vacío las NPC usan reglas), `npc.brain`, `AUTO_TICK_SECONDS`, y
  `imagePullSecrets` opcional. Imagen por defecto desde **GHCR**.
- CI: workflow `build-image` que construye **multi-arch (amd64+arm64)** y publica en GHCR
  (para clusters Raspberry Pi/k3s sin builder local) + workflow `ci` (ruff + pytest).
- `deploy/helm/values-local.example.yaml` (gitignored `values-local.yaml`) para el token local.
- README con pasos de deploy en k3s/ARM. `helm lint` ok; render validado con token+pull-secret.
- Nota: el deploy real (`helm install`) corre una vez que la CI publica la imagen ARM (esta
  máquina no tiene builder de contenedores).

### 2026-06-20 — Replicable y publicable (probado en Linux)
- `make publish REPO=nombre` crea el repo público en GitHub y sube todo (vía `gh`).
- `make run`/`run-lan` ahora prenden el auto-tick por defecto (`AUTOTICK=15`), así una copia
  recién clonada tiene mundo vivo sin tocar `.env`.
- README con flujo de publicar + replicar (clonar → `make install` → `make run`).
- **Verificado en Linux** (clean-room): clon fresco desde GitHub → install → server arranca,
  DB migra sola, registro 201, web sirve, 86 tests verdes; sin `.env` (defaults).

### 2026-06-20 — Visibilidad de la DB en uso
- Al arrancar, el server **loguea qué base usa** (`[online-game] DB=sqlite (...) · auto-tick=...`),
  con la contraseña redactada. `/health` ahora devuelve `db` (sqlite/postgres) y la web muestra
  un pill 🗄 en el header. Para que quede claro si estás en SQLite local o Postgres (Docker) y
  no confundir partidas. e2e: `/health` expone `db`.

### 2026-06-20 — Tests de navegador (Playwright) con screenshots
- `tests/browser/` maneja la web real en Chromium: registro → onboarding → construir →
  crear alianza (ve beneficios explicados) → guía; + verifica que la alianza NPC sale
  marcada "no unible". Guarda **screenshots** de cada pantalla en
  `tests/browser/screenshots/` (gitignored). Corren con `make test-ui` (aparte de `make test`,
  que los ignora porque necesitan navegador). Deps opcionales en el extra `ui`.

### 2026-06-20 — Web: alianzas más claras + CLAUDE.md
- UI de alianzas reescrita para que se entienda: al crear, cada **tipo** muestra su
  descripción y **beneficios explicados** (no solo el nombre); estando en una alianza ves
  **miembros, beneficios en lenguaje claro, alertas y comercio**; las alianzas de **NPC**
  salen marcadas y **sin botón de unirse** (con el motivo). El formulario ya no se borra solo.
- `CLAUDE.md` agregado (guía de arquitectura/comandos para el repo).
- e2e: el catálogo expone `alliance_types` con `benefits`+`description` (lo que la web muestra).

### 2026-06-20 — Web: UI de alianzas (tipo, beneficios, comercio, visión) + repo público
- La web ahora deja **elegir el tipo de alianza** al crear, muestra sus **beneficios**, una
  **alerta de visión compartida** (aliados bajo ataque) y un mini-form de **comercio** para
  transferir minerales a un aliado (si el tipo lo permite). Sigue consumiendo solo la API.
- **Fix (code-review)**: un humano ya no puede unirse a la alianza de las NPC (daba inmunidad
  + beneficios); la alianza NPC se identifica por tener miembros NPC (no por nombre), evitando
  que un humano la "capture" usando el mismo nombre.
- Repo preparado para publicar: `LICENSE` (MIT), `.dockerignore`, `.gitignore` endurecido
  (nunca sube `.env` ni `*.db`), README con 3 modos (full-local / LAN / online) y `make`
  targets `run`/`run-lan`/`up`/`tunnel`.

### 2026-06-20 — Alianzas con beneficios y tipos (data-driven)
- **Tipos de alianza** en `content/alliances.yaml` (no-agresión / defensiva / plena), cada uno
  habilita beneficios. Se elige al crear (`type`). La no-agresión aplica siempre.
- **Beneficios**:
  - `shared_bonus`: multiplicador compartido (prod/ataque/defensa) a todos los miembros.
  - `shared_unit_tech`: cada raza de la alianza comparte su `unit_perk` (en `races.yaml`) →
    p.ej. terran+marciano = +prod y +ataque para todos. Se aplica vía `services/effects.py`.
  - `mutual_defense`: los aliados prestan 25% de su defensa cuando atacan a un miembro.
  - `shared_vision`: ves los ataques entrantes sobre tus aliados (`/me.alliance_incoming`).
  - `trade`: `POST /alliances/transfer` mueve minerales entre aliados.
- `/me` expone `alliance_type`; el catálogo lista los tipos. CLI `alliance-create ... [tipo]`,
  `alliance-transfer`. Migración Alembic (`alliances.type`).
- Tests: 6 de servicio (bonus, unit-tech, defensa mutua, comercio) + 2 e2e (tipo+comercio,
  visión compartida). Smoke en vivo: alianza plena terran+marciano → ataque/prod ×1.21.

### 2026-06-20 — DB auto-migra al arrancar + Guía in-game + sacar "Avanzar" del jugador
- **Migraciones automáticas en el arranque** (`run_migrations()` vía `asyncio.to_thread`):
  el server aplica Alembic a head al iniciar → **ya no hace falta `make db-reset`** al cambiar
  el esquema en dev (idempotente; sirve para SQLite local y Postgres). Solo se necesita un
  último reset si venías de una DB vieja creada con `create_all`.
- **Guía in-game** (web): tarjeta "📖 ¿qué es cada cosa?" que explica energía, minerales
  (in-game ↔ real, desde el catálogo), edificios, unidades, expediciones, combate,
  investigación y alianzas.
- **Quitado el botón "Avanzar"** de la UI del jugador (rompía el tiempo real; el mundo ya
  avanza solo con el auto-tick). `/admin/tick` queda como herramienta de dev/CLI/tests.

### 2026-06-20 — Ranking por alianza + NPCs aliados + UX de costos en la web
- **Ranking por alianza**: `GET /alliances/ranking` (suma de scores de miembros). Score de
  jugador extraído a `services/scoring.py` y reutilizado por ambos rankings. CLI `alliance-ranking`.
- **NPCs aliados**: todas las NPC entran a una alianza compartida ("Consorcio Estelar"/AI),
  cooperan y no se atacan entre sí; el cerebro NPC excluye bases aliadas al elegir objetivo.
- **Web — costos y avisos**: ahora muestra el costo (en minerales reales por raza) y un aviso
  **⚠ te falta / ✓ alcanza** para construir, entrenar (×cantidad) y expediciones; tooltips que
  explican "Avanzar" (forzar tick) y "Refrescar" (F5 de datos).
- Migración: ninguna nueva (reusa `alliances`). Tests: 2 e2e (ranking de alianza, NPCs comparten alianza).

### 2026-06-20 — Web: paneles de Investigación, Ranking y Alianzas
- La web ahora expone las features de profundidad (sigue siendo puro consumidor de la API):
  - **🔬 Investigación**: lista las techs del catálogo con efecto/costo, botón "investigar",
    estado ✓ lista / en progreso con barra (de `/catalog` + `/me`).
  - **🏆 Ranking**: tabla bajo demanda desde `/players/ranking`.
  - **🤝 Alianzas**: tu alianza con "salir", o crear (nombre+tag) y lista para "unirse"
    (de `/alliances` + `/me`).
- e2e: la página servida incluye los paneles (Investigación/Ranking/Alianzas/Galaxia).

### 2026-06-20 — Alianzas
- Jugadores forman alianzas (`Alliance` + `Player.alliance_id`, `services/alliances.py`):
  crear, unirse, salir, listar y ver detalle con miembros.
- **No se puede atacar a un aliado**: `start_attack` rechaza si atacante y defensor comparten
  alianza. `/me` muestra `alliance_id`/`alliance_name`; el scoreboard incluye `alliance_id`.
- API `POST /alliances`, `/{id}/join`, `/leave`, `GET /alliances`, `/{id}`. CLI
  `alliances`, `alliance-create`, `alliance-join`, `alliance-leave`.
- Migración Alembic (`alliances` + `players.alliance_id`, FK nombrada para batch SQLite).
- Tests: 3 e2e (crear/unirse/listar, no atacar aliado, salir).

### 2026-06-20 — Más juego: investigación, ranking y más mundos
- **Investigación/tecnologías** (`content/technologies.yaml`, `services/research.py`):
  cuesta minerales+energía, requiere laboratorio activo, tarda un tiempo, y al completarse
  otorga un **efecto permanente** (producción/ataque/defensa). `services/effects.py` unifica
  boons + techs y se aplica en economía y combate. API `POST /research`; `/me` expone
  `technologies` y `research`; el catálogo lista las techs. CLI `research <key>`.
- **Ranking**: `GET /players/ranking` con puntaje (edificios + poder militar + minerales +
  techs + victorias), ordenado. CLI `ranking`.
- **Más mundos**: Mercurio en la Vía Láctea + nueva galaxia **Andrómeda** (Vega Prime, Nyx),
  todo data-driven en `content/planets.yaml`. Onboarding ya soporta múltiples galaxias.
- Migración Alembic (`player_techs`, `research_orders`). Tests: 3 de servicio + 4 e2e
  (research flow, requiere lab, ranking, más planetas/galaxias). Smoke en vivo: prod 1.0→1.25.

### 2026-06-20 — Pulido visual de la web
- **Mapa de la galaxia**: planetas (Tierra/Marte/Venus) con orbes animados y sus colonias;
  click en una base enemiga autocompleta el objetivo de ataque.
- **Barras de progreso animadas** en colas (construcción/entrenamiento/expedición) calculadas
  desde el catálogo; flotas con countdown + botón recall; ataques entrantes resaltados.
- Refresco suave (countdowns/mapa cada 1s, estado cada 4s), tema más prolijo, responsive,
  indicador "● en vivo" del stream. Todo sigue siendo puro consumidor de la API.

### 2026-06-20 — World auto-tick + UX de sesión en la web
- **Auto-tick**: loop en segundo plano (`AUTO_TICK_SECONDS`, lifespan de FastAPI) que avanza
  el mundo (turnos NPC, llegadas de flotas, colas) sin intervención. 0 = apagado
  (multi-réplica usa el CronJob). Verificado: dejando el server solo, las NPC nacen y juegan.
- Web: recuerda el último usuario, aclara que los datos persisten en la cuenta del servidor
  (entrás desde cualquier dispositivo) y muestra errores de auth claros.

### 2026-06-20 — Push en tiempo real (SSE) + cliente web jugable
- **SSE**: `GET /notifications/stream?token=...` empuja notificaciones en vivo
  (catch-up + nuevas). Auth por query (EventSource no manda headers). Lógica en
  `stream_events` (testeable con `once=True`); el endpoint hace loop hasta desconexión.
- **Cliente web** (`web/index.html`, vanilla JS) servido en `GET /`: registro/login,
  onboarding, estado, construir/entrenar/atacar/expedición/tick, scoreboard y un panel de
  **notificaciones en vivo** vía `EventSource`. Ahora se puede jugar desde el navegador.
- Tests: generador SSE emite la notificación; la web responde en `/`.

### 2026-06-20 — NPCs más tácticos
- **Reglas tácticas** (`RuleBasedBrain`): respuesta a amenazas (si hay ataque entrante,
  **recall** de la flota propia para defender, o construir **torreta**); fabrica **tanques**
  (build factory) además de soldados; ataca el blanco con **menor defensa estimada** y solo
  si su poder de ataque la supera con margen; manda **expediciones** si tiene transbordador.
- **LLM táctico**: el `state` ahora incluye `incoming_attacks`, `my_missions`,
  `defense_estimate` por enemigo y `reachable_moons`; el dispatcher acepta acciones
  `recall` y `expedition`. (El default por reglas es el confiable; el LLM free es opcional.)
- Tests: 4 de servicio (recall y torreta bajo ataque, state táctico, LLM recall).

### 2026-06-20 — Notificaciones
- Tabla `Notification` + `services/notifications.py`. Se emiten en los puntos donde el
  estado cambia del lado servidor (una sola vez por evento): **ataque entrante** (al
  defensor, fog of war), **batalla resuelta** (atacante y defensor), **flota de vuelta**,
  **expedición de vuelta**, **edificio listo**, **unidades entrenadas**.
- API: `GET /notifications` (`?unread=true`), `POST /notifications/read` (todas o `ids`).
  `/players/me` expone `unread_notifications`.
- CLI: `notifications`, `read`. Migración Alembic `notifications`.
- Tests: 2 e2e (ataque entrante notifica al defensor; edificio listo notifica + marcar leídas).

### 2026-06-19 — Defensas de edificio + recall de flotas
- **Torreta defensiva** (`content/buildings.yaml`, `category: defense`, `defense_power`):
  suma defensa fija a la base. En la resolución, las torretas activas del base objetivo
  refuerzan al defensor (con bonus de raza/boon) → una base bien fortificada aguanta sin unidades.
- `resolve_combat` admite `defender_flat_defense` (puro/testeable).
- **Recall**: `POST /combat/missions/{id}/recall` retira una flota en vuelo de ida; viaja de
  vuelta lo ya recorrido y regresa con toda la fuerza, sin combate. Solo el dueño, solo outbound.
- CLI: `recall <mission_id>`. Tests: 1 unit (flat defense) + 2 e2e (torretas aguantan, recall sin batalla).

### 2026-06-19 — Combate con viaje/tiempo (flotas, resolución diferida, ida y vuelta)
- El ataque deja de ser instantáneo: `POST /combat/attack` ahora **despacha una flota**
  (`AttackMission`). Las unidades se **bloquean** (salen del stock mientras viajan).
- Tiempo de vuelo según **distancia** entre planetas (`TRAVEL_SECONDS_SAME_PLANET` /
  `TRAVEL_SECONDS_CROSS_PLANET`). El defensor ve el ataque entrante (fog of war: sin
  composición) → ventana para reaccionar.
- **Resolución diferida** al llegar (`process_missions` en el tick y en `state.advance`):
  batalla con `resolve_combat` + bonus de raza + boons; bajas y botín.
- **Viaje de ida y vuelta**: sobrevivientes + botín regresan y se re-acreditan al volver.
- `/players/me` muestra `missions_outgoing` (tuyas) y `missions_incoming` (entrantes).
- Migración Alembic `attack_missions`. NPCs ahora lanzan flotas (mismo flujo).
- Tests: 2 e2e (despacho+bloqueo+fog; ciclo completo viaje→batalla→retorno). Smoke en vivo OK.

### 2026-06-19 — Cerebro LLM enriquecido: personalidad + memoria
- Cada raza tiene `personality` en `content/races.yaml` (marciano belicoso, venusiano
  tecnológico/cauto, terrícola económico). Se inyecta en el prompt → las NPC juegan en
  personaje. Verificado en vivo: mismo escenario, marciano ataca / venusiano hace ciencia /
  terrícola mina.
- **Memoria corta** por NPC (`Player.npc_memory`, JSON de últimas 8 acciones) + resumen de
  `recent_battles` (de `CombatLog`), incluidos en el prompt para continuidad.
- Migración Alembic para `npc_memory` (con `server_default`).
- Tests: personalidad distinta por raza, memoria que se acumula entre turnos, prompt-state
  con personality/recent_actions.

### 2026-06-19 — Redis: cache + rate limit (con degradación elegante)
- Capa `app/core/redis.py`: si `REDIS_ENABLED=false` o Redis no responde, todo degrada a
  no-op (sin romper local/tests). `get_redis` es dependency de FastAPI.
- **Cache** del catálogo (`GET /catalog`, TTL configurable) y **rate limit** de ataques
  (`POST /combat/attack` → 429 al exceder `ATTACK_RATE_LIMIT_PER_MIN`).
- compose/Helm activan `REDIS_ENABLED=true`. Tests con `fakeredis`: 4 unit + 2 e2e.

### 2026-06-19 — Tooling: Makefile + script de demo
- `Makefile` con targets: `install`, `run`, `demo`, `test`, `lint`, `fmt`, `migration`,
  `up`/`down` (docker), `clean`. `make help` los lista.
- `scripts/demo.sh`: levanta un server efímero (SQLite fresca) en un puerto libre (8099),
  corre el flujo completo por CLI (register→onboard→build→train→tick→players→me) y apaga
  el server solo. Evita el choque típico con un `http.server` en el 8000.

### 2026-06-19 — Razas NPC con IA (reglas + OpenRouter opcional)
- NPCs como jugadores reales (`is_npc`), uno por raza, creados/onboardeados automáticamente.
- Cerebro **enchufable** (`services/npc.py`): `RuleBasedBrain` (default, heurística
  determinista) y `LlmBrain` (OpenRouter, opcional) detrás de la misma interfaz, con
  **fallback duro a reglas** ante cualquier fallo (red/rate-limit/JSON inválido/acción
  infactible) — el tick nunca se rompe.
- Toman **una acción por tick** vía los mismos servicios que un humano (build/train/attack),
  ejecutado por `worker.run_tick` (refactor: corre sobre una sesión, drivable por HTTP).
- API: `GET /players` (scoreboard con bases NPC para atacar) y `POST /admin/tick`
  (avanzar el mundo a demanda; útil para demo/tests). CLI: `players`, `tick`.
- OpenRouter: modelo free por defecto `google/gemma-4-31b-it:free` (elegido por latencia
  + JSON correcto). Config: `NPC_BRAIN`, `OPENROUTER_*`. Key en `.env` (gitignored).
- Migración Alembic para `is_npc` (con `server_default` seguro en tablas pobladas).
- Tests: 4 de servicio (incl. LLM con `decide` inyectado + fallback) + 2 e2e HTTP
  (tick crea NPCs y actúan; humano ataca un NPC). Smoke en vivo confirmado contra OpenRouter.

### 2026-06-19 — Migraciones con Alembic
- **Alembic** configurado para esquema de base de datos (async, lee `DATABASE_URL`).
  - `alembic.ini`, `migrations/env.py`, migración inicial con todas las tablas.
  - Prod usa migraciones; dev/sqlite sigue pudiendo usar `init_models()`.
  - Test que verifica que `alembic upgrade head` crea todas las tablas de los modelos.
- **CHANGELOG.md** creado para trackear el progreso.

### 2026-06-19 — Expediciones a lunas + boons de dioses
- Enviar expedición a una luna de tu galaxia: cuesta energía + requiere transbordador;
  al volver entrega recursos premium (He-3, tierras raras, hielo) y un **boon temporal**.
- Boons (`production`/`attack`/`defense`) aplicados *lazy* en producción y combate,
  encima de los bonus de raza. Todo data-driven en `content/gods.yaml`.
- API: `GET /expeditions/moons`, `POST /expeditions`. `/players/me` expone `expeditions` y `boons`.
- Servicios: `services/expedition.py`, `services/boons.py`. CLI: `moons`, `expedition`.
- Tests: 5 de servicio + 3 e2e HTTP.

### 2026-06-19 — Combate PvP
- Atacar la base de otro jugador comprometiendo una fuerza; resolución con `stats`
  (attack/defense) + bonus de raza (marciano +ataque, venusiano +defensa).
- Bajas en ambos lados y **botín** de minerales al ganar. Historial de combates.
- API: `POST /combat/attack`, `GET /combat/reports`. Servicio: `services/combat.py`
  (`resolve_combat()` puro/determinista). Config: `ATTACK_ENERGY_COST`, `LOOT_FRACTION`.
- CLI: `attack`, `reports`. Tests: 4 puros + 3 e2e HTTP.

### 2026-06-19 — Entrenamiento de unidades
- Entrenar personajes (trabajador/militar/científico) y unidades pesadas
  (tanque/barco/avión/transbordador). Cuesta energía + minerales (resueltos por raza),
  requiere el edificio activo correspondiente, entra a una cola y se entrega al cumplirse.
- API: `POST /bases/{id}/train`. `/players/me` expone `units` y `training`.
- Servicio: `services/training.py`. CLI: `train`. Tests: 3 integración + 2 e2e HTTP.
- Suite **e2e HTTP** (`tests/test_api_e2e.py`) creada para cubrir todos los endpoints.

### 2026-06-19 — Slice vertical jugable (MVP inicial)
- Juego online por turnos asíncrono, **API-first** (FastAPI), con planetas y minerales
  **reales** (Vía Láctea: Tierra, Marte, Venus). 3 razas con mapeo configurable
  rol→mineral. Energía que regenera por hora (cálculo *lazy* por timestamp).
- Flujo: registro/login (JWT) → onboarding (galaxia/planeta/raza) → construir edificios
  (incl. minas que producen minerales) vía API.
- **Contenido data-driven** en `content/*.yaml` (minerales, planetas, razas, edificios,
  unidades, dioses): rebalancear = editar un valor.
- Stack: FastAPI + SQLAlchemy async + Postgres/Redis (SQLite para dev/tests).
- Portabilidad: `Dockerfile`, `docker-compose`, chart **Helm** (api + worker CronJob + pg + redis).
- Cliente **CLI** de referencia. Documentación: `README`, `docs/{game-design,architecture,development}.md`.
- Tests: energía, producción, contenido, flujo end-to-end.
