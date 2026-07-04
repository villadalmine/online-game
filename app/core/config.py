from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTENT_DIR = REPO_ROOT / "content"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Online Galaxy War"
    environment: str = "development"

    database_url: str = "sqlite+aiosqlite:///./game.db"
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = False  # off by default so local/dev/tests need no Redis

    # Redis-backed features
    catalog_cache_ttl: int = 300  # seconds
    attack_rate_limit_per_min: int = 20

    # Capacidad / escalado (SDD 7). El SSE pollea la DB por conexión: subir el intervalo
    # baja drásticamente la carga (0.5 rps/CCU a 2 s → 0.2 a 5 s). El pool de DB es por
    # réplica; pool_size × n_réplicas ≤ max_connections de Postgres (techo real → PgBouncer).
    stream_interval: float = 2.0          # default del SSE (s) si el cliente no pide otro
    db_pool_size: int = 10                # conexiones persistentes por réplica (no-sqlite)
    db_max_overflow: int = 20             # conexiones extra bajo ráfaga
    db_pool_timeout: int = 10             # s a esperar una conexión del pool antes de fallar
    # (timeout corto: si el pool se satura, el request falla rápido y el cliente reintenta en el
    # próximo ciclo — mejor que colgar 30s y dejar el panel "cargando" eternamente)
    db_pool_recycle: int = 1800           # reciclar conexiones cada N s (evita stale en PgBouncer)

    jwt_secret: str = "change-me-in-prod"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080

    # Game balance (overridable via env)
    energy_regen_per_hour: float = 10.0
    energy_max: float = 240.0
    energy_start: float = 60.0
    # Cada planta de energía ACTIVA sube el tope y la regen (antes el edificio no hacía nada pese a
    # prometerlo). El tope efectivo = energy_max + plantas×energy_max_per_power_plant.
    energy_max_per_power_plant: float = 120.0
    energy_regen_per_power_plant: float = 5.0

    # Colonización (SDD 37): fundar bases en otros planetas.
    max_colonies: int = 3                 # máximo de colonias (además del mundo natal)
    colonize_energy_cost: float = 60.0    # energía por colonización (escala con nº de colonias)
    # Mercado (SDD 42 Fase 1): precio = base × escasez (1/abundancia del planeta).
    market_mineral_base_energy: float = 2.0   # energía por unidad de mineral (precio intrínseco)
    market_scarcity_floor: float = 0.2        # piso de abundancia → tope de carestía (premium ~5×)
    market_sell_spread: float = 0.7           # vendés al 70% del precio de compra (spread)
    # Anti-abuso del mercado local del mundo natal (SDD 42): ventana móvil que "se resetea".
    market_window_seconds: int = 7200         # 2h
    market_sell_pct: float = 0.30             # vendés ≤ 30% de tus tenencias por ventana
    market_buy_pct: float = 0.20              # comprás ≤ 20% (anti-reventa)
    market_buy_floor: float = 100.0           # piso de compra para no bloquear a los que empiezan
    market_transport_ships_per_window: int = 4  # ≤ 4 naves de carga despachadas por ventana (base)
    market_transport_ships_per_hangar: int = 2  # +N al cupo de la ventana por cada hangar activo
    black_market_rate: float = 0.7            # trueque ilegal: peor que el precio justo (premium)
    pirate_raid_chance: float = 0.15          # prob. por tick de que piratas embosquen un convoy
    pirate_strength: float = 0.02             # poder pirata = strength × unidades de carga totales
    pirate_loss_cap: float = 0.5              # un asalto roba como mucho el 50% de la carga
    # Hub galáctico (SDD 42 Fase 3): precio dinámico por oferta/demanda.
    market_hub_impact: float = 0.0008         # cuánto mueve el precio cada unidad comprada/vendida
    market_hub_reversion: float = 0.1         # reversión al valor intrínseco por tick
    market_hub_band: float = 4.0              # banda: precio en [intrínseco/band, intrínseco×band]
    app_version: str = "dev"              # SDD 41: versión del juego (se setea por env APP_VERSION)
    meta_compute_interval_seconds: int = 600   # cada cuánto recalcula el meta (en el tick)
    assist_energy_per_day: int = 3        # SDD 40: veces/día que podés pedir energía de nivelado
    assist_energy_normal: float = 100.0   # +energía para jugadores que no son del fondo
    orbital_yield: float = 0.4            # rinde de una base orbital (robots, sin habitabilidad)
    orbital_cost_mult: float = 1.8        # la colonización orbital cuesta más energía

    # Eventos dinámicos "happy hour" (SDD 36): el tick puede arrancar uno en horas aleatorias.
    event_chance_per_tick: float = 0.25   # prob. por tick (si no hay activo y pasó el cooldown)
    event_cooldown_seconds: int = 1800    # mínimo entre eventos (30 min)

    # Combat balance
    attack_energy_cost: float = 25.0
    # Límite de ataques por ventana (gameplay, aplica a humanos Y NPCs): da tiempo al rival a
    # reagruparse y evita que la IA "se zarpe". Default: 3 ataques cada 4 h. 0 = sin límite.
    attacks_per_window: int = 3
    attack_window_seconds: int = 14400   # 4 h
    # SDD 55 (anti-farmeo): topes por DÍA para que la IA (o un humano) no acose al mismo jugador.
    # Por par (atacante, defensor): cuántas veces le pegás al MISMO rival en 24 h. 0 = sin tope.
    attacks_per_target_per_day: int = 2
    # Por defensor: cuántos ataques ENTRANTES tolera un jugador en 24 h (para reconstruir). 0 = off.
    max_incoming_attacks_per_day: int = 6
    # SDD 54: el combate nunca deja al defensor con menos de N trabajadores → siempre puede seguir
    # juntando material y reconstruir (no quedás trabado sin salida). 0 = sin piso.
    min_surviving_workers: int = 2
    # SDD 79: "fortificar todas" — cuántos soldados garrisonar en una base sin defensa cuando no se
    # puede la torreta (falta weapons/lab) → defensa universal (el soldado solo requiere HQ).
    fortify_soldiers: int = 5
    # SDD 55 §3.2: la IA NO patea al débil — no ataca a un HUMANO cuyo score esté por debajo de esta
    # fracción del suyo (anti-snowball; lo deja crecer). 0 = sin protección (ataca a cualquiera).
    npc_weak_protect_ratio: float = 0.5
    # SDD 57: bombardeo "rompe-bases" — naves con `siege_power` que ganan demuelen edificios
    # EXCEDENTES (nunca HQ/minas ni el último de su tipo). siege_per_building = siege para volar 1.
    siege_enabled: bool = True
    siege_per_building: int = 300
    # SDD 57 v2: una flota con naves espaciales y la tech `hyperspace_travel` viaja a esta fracción
    # del tiempo normal (saltos por el hiperespacio). 1.0 = sin efecto.
    hyperspace_travel_factor: float = 0.5
    loot_fraction: float = 0.2  # share of each defender mineral looted on a win
    # Fleet travel time (seconds): one-way. Same planet is quick; cross-planet is slow.
    travel_seconds_same_planet: int = 60
    travel_seconds_cross_planet: int = 300

    # World auto-tick: background loop that advances the world (NPC turns, mission
    # arrivals, queues) every N seconds. 0 = off. Use >0 for single-instance/dev so the
    # browser feels alive; in multi-replica prod keep 0 and use the k8s CronJob instead.
    auto_tick_seconds: int = 0

    # NPC (AI-controlled races)
    npc_enabled: bool = True
    npc_brain: str = "rules"  # "rules" (default) | "llm" (any OpenAI-compatible server)
    # Si está ON, las NPC comparten una alianza y no se atacan entre sí (cooperan vs humanos). OFF
    # (default) = NPCs INDEPENDIENTES → también se atacan entre ellas (más vida en la galaxia).
    npc_shared_alliance: bool = False

    # Personal AI assistant (SDD 2): emergency "hack" budget per player per day.
    assistant_hacks_per_day: int = 3
    # SDD 9: el asistente manda solo el SUBGRAFO relevante (no el grafo completo) → prompt chico →
    # lo resuelve la GPU local (qwen 1.5b, ~1-3s) sin truncar ni caer a la nube free (tope diario).
    advisor_graph_k: int = 14             # cuántos nodos del grafo (top-k) van al prompt del asesor
    # Modelo/timeout por caso de uso: el ASISTENTE es interactivo (rápido, timeout corto); los NPCs
    # toleran esperar (atacar/comerciar/chat de alianza) → timeout largo, prioriza GPU local (ahorra
    # plata). Modelo vacío = usa LLM_MODEL global; seteá *_llm_model para apuntar a otro alias.
    assistant_llm_timeout_seconds: float = 20.0
    assistant_llm_model: str = ""
    npc_llm_timeout_seconds: float = 60.0
    npc_llm_model: str = ""
    # Comparar GPU local vs nube por NPC (SDD 19 §9): si seteás npc_cloud_username (p.ej.
    # "npc_venusian"), ESE NPC usa el modelo de nube (npc_cloud_model, alias del litellm) y el resto
    # la GPU local (npc_llm_model). Las métricas se etiquetan por backend → comparás quién juega
    # mejor (score/win-rate) y quién decide más por LLM. "" = todos GPU.
    npc_cloud_username: str = ""
    npc_cloud_model: str = "gemma4-paid"
    # Los NPC regeneran energía más rápido (×) para no quedar 'ahogados' y poder jugar por LLM en
    # vez de caer a fallback por energía. No afecta a los jugadores humanos.
    npc_energy_regen_mult: float = 4.0
    # SDD 19 §7.quater: el tick (CronJob) es un pod efímero no-scrapeable → empuja sus métricas
    # (NPC actions/decisions, tick) a la Pushgateway. Vacío = no empuja (dev/local).
    pushgateway_url: str = ""
    # SDD 19 §9.3: ver el dashboard de Grafana DENTRO del admin. Si seteás la URL del dashboard
    # NPC AI (idealmente con &kiosk para embeber limpio), la consola de admin muestra un link
    # "📊 Ver en Grafana" y, si el navegador del admin ya tiene sesión de Grafana, lo embebe en un
    # iframe. Vacío = no muestra nada (sin cambios de UI). Requiere allow_embedding=true en Grafana.
    grafana_npc_dashboard_url: str = ""
    # Presupuesto del asesor por jugador/día (anti-quema de créditos): pasado el cupo NO se llama al
    # LLM (cero tokens) y se cae a los tips deterministas. = patrón DAILY_CAP del repo shooter.
    advisor_llm_calls_per_day: int = 40
    # SDD 77: la IA te ESCRIBE sola (mensaje proactivo) ante una situación notable (ataque entrante,
    # energía crítica), con cooldown por jugador. Determinista (no gasta LLM). Detrás de flag.
    advisor_proactive_enabled: bool = False
    advisor_proactive_cooldown_hours: float = 6.0
    # Selector de modelo del asistente (SDD 9): gpu (local) | cloud (pago barato) | byok (key del
    # jugador). El modo cloud usa este alias; byok apunta a este base_url por defecto.
    assistant_cloud_model: str = "gemma4-paid"
    assistant_byok_base_url: str = "https://openrouter.ai/api/v1"

    # Temporadas + protección de novatos (SDD 11).
    season_days: int = 28                 # duración de cada temporada
    season_hall_of_fame_top: int = 10     # cuántos entran al Hall of Fame al cerrar
    newbie_protection_hours: int = 48     # protección al crear el imperio

    # Galaxy instances / shards (SDD 8): máx humanos por instancia de galaxia.
    galaxy_capacity: int = 50

    # Catch-up del recién llegado (SDD 25): nivela al nuevo al percentil P40 de sus pares (sin
    # ventaja), con energía full + defensa. Solo si hay ≥ min_peers en su galaxia.
    catchup_enabled: bool = True
    catchup_percentile: float = 0.4
    catchup_min_peers: int = 3
    # SDD 25 follow-up: factor EXPLÍCITO por días de temporada. El grant escala de 0 (día 0) a full
    # (P40 de pares) a los `catchup_full_after_days` días → entrar temprano da poco, tarde nivela. 0
    # = sin escalado por días (vuelve al comportamiento v1, top-up directo al P40).
    catchup_full_after_days: float = 7.0

    # Minería: staffing (obreros) + almacén (silos) (SDD 47). PRENDIDOS con balance suave para no
    # romper a los nuevos: `mining_staffing_floor` da un piso de producción con 0 obreros (de ahí a
    # 1.0 con obreros); el storage arranca generoso (base + HQ). Nunca borran stock sobre el tope,
    # solo frenan producción nueva. Apagables por env.
    mining_staffing_enabled: bool = True
    storage_caps_enabled: bool = True
    base_storage_per_mineral: float = 5000.0   # colchón por mineral por planeta aun sin silos
    # SDD 54: piso BAJO sin obreros (10%) → sin gente la mina casi no rinde (los trabajadores SÍ
    # importan), pero no zerea del todo a un novato. Antes 0.34 (demasiado alto).
    mining_staffing_floor: float = 0.10        # producción mínima sin obreros (simbólica)

    # Alojamiento de unidades (SDD 46): cada unidad ocupa una plaza de su dominio; cada edificio da
    # plazas. ENFORCE con GRACIA (`base_housing_per_domain`): cada dominio arranca con N plazas aun
    # sin el edificio → no frena a los nuevos; ampliás construyendo. Nunca destruye unidades.
    # Apagable por env. Ver docs/sdd-unit-housing-capacity.md.
    housing_enforced: bool = True
    base_housing_per_domain: int = 10          # plazas de gracia por dominio aun sin edificio

    # SDD 62 (guarnición): tropas/obreros estacionados POR BASE. OFF = ejército global (histórico):
    # el combate usa TODAS tus unidades para defender cualquier base; las unidades se guardan en
    # `UnitStock.base_id=NULL`. ON = cada base tiene su guarnición; el combate usa solo la base
    # atacada; entrenar deposita en la base; mover tropas viaja. Prender tras balancear.
    garrison_enabled: bool = False

    # SDD 63: salto espacial — la nave `jumper` mueve tropas entre TUS bases al INSTANTE,
    # hasta `jump_capacity` (del YAML) por jumper. Cada salto gasta energía. OFF hasta balancear;
    # gateado por la tech `space_jump` (capstone). Ver docs/sdd-space-jump-jumpers.md.
    space_jump_enabled: bool = False
    jump_energy_cost: float = 40.0        # energía por salto instantáneo

    # SDD 64: búnkeres atómicos — cavar túneles + habitaciones subterráneas + guerra de sabotaje
    # (gas/ratas/agua). Medidores de salud comida/agua/gente (0-100, regen lazy por las salas). OFF
    # hasta balancear; gateado por `bunker_engineering`. Ver docs/sdd-atomic-bunkers.md.
    bunkers_enabled: bool = False
    bunker_grid: int = 4                  # celdas NxN del mapa subterráneo por búnker
    bunker_meter_decay_per_hour: float = 2.0   # decaimiento base de cada medidor por hora
    bunker_gas_damage: float = 25.0       # golpe de gas a la salud de gente (mitiga ventilación)
    bunker_vent_mitigation: float = 0.25  # cada ventilación reduce el gas 25% (tope ~90%)
    bunker_sabotage_damage: float = 25.0  # golpe de ratas (comida) / contaminar (agua)
    bunker_raid_min_map_pct: float = 50.0  # % descubierto (satélites) mínimo para poder sabotear
    bunker_raids_per_target_per_day: int = 3  # tope de sabotajes por (atacante,objetivo)/día
    bunker_raid_energy_cost: float = 20.0  # energía por incursión de sabotaje
    # SDD 69 Fase 1 — expansión subterránea ("me quedo sin espacio"): con la tech
    # `underground_construction` podés EXCAVAR y agrandar la grilla del búnker. Lado efectivo =
    # bunker_grid + grid_level (cada excavación +1 lado, hasta el tope). Detrás de flag.
    bunker_expansion_enabled: bool = False
    bunker_grid_max: int = 8               # lado máximo de la grilla (tope de excavaciones)
    bunker_dig_energy_cost: float = 60.0   # energía por excavación
    bunker_dig_cost_structural: float = 400.0  # estructural base por excavación (escala ×nivel)
    # SDD 75 — TERRAFORMACIÓN: la tech `terraforming` habilita la sala "terraformer" que agranda el
    # búnker (+grid_bonus al lado, data-driven en el YAML de la sala). Detrás de flag.
    terraforming_enabled: bool = False
    # SDD 76 — SALTO CUÁNTICO: la tech `quantum_jump` habilita la sala "quantum_gate" (Puerta
    # cuántica) que teletransporta ELECTRÓNICA de un búnker a otro (instantáneo). El origen necesita
    # una puerta activa. Sirve para consolidar y recuperarte. Detrás de flag.
    quantum_teleport_enabled: bool = False
    quantum_teleport_fee: float = 0.1     # SDD 76: merma por teletransporte (0.1 = 10% se pierde)
    # SDD 69 Fase 4 — VIDA ARTIFICIAL: research por niveles + autopiloto de robots. Dos flags:
    #  - artificial_life_enabled: podés SUBIR de nivel (research en el búnker). Default OFF.
    #  - bunker_autonomy_enabled: el autopiloto ACTÚA solo en el tick (auto-staffing). Default OFF.
    artificial_life_enabled: bool = False
    bunker_autonomy_enabled: bool = False
    ai_autopilot_worker_cap: int = 3       # tope de obreros que el autopiloto entrena por tick
    artificial_life_npc_ceiling: int = 0   # techo de IA que habilita a los NPC (admin, Fase 4)
    # SDD 81: el autopiloto puede PENSAR con el LLM (gpu/cloud). El modo es por jugador
    # (Player.ai_brain_mode: rules|gpu|cloud|auto; auto prueba gpu, cloud, reglas). Este flag lo
    # habilita (default OFF = siempre reglas). Cae a reglas ante cualquier fallo.
    ai_autopilot_brain_enabled: bool = False
    ai_brain_min_level: int = 3            # ai_level mínimo para que el cerebro LLM piense
    ai_brain_explore: float = 0.15        # SDD 81 v2: prob. de que 'auto' explore la otra ruta
    ai_brain_decay: float = 0.97          # SDD 81 v2: decaimiento del rendimiento (media móvil)
    # Sub-fase 2 (autopiloto economía): comercio conservador (vende EXCEDENTE sobre el umbral) +
    # tope de venta por tick. mines/colonize construyen/colonizan 1 por tick (acotado).
    ai_trade_surplus_threshold: float = 10000.0
    ai_trade_sell_qty: int = 500
    # Sub-fase 3 (autopiloto ataque): solo ataca si supera claramente la defensa estimada (×margin),
    # dejando RESERVA defensiva en casa. Respeta topes anti-farmeo (SDD 55) y el botón STOP.
    ai_attack_margin: float = 1.5      # tu poder de ataque debe superar la defensa × este factor
    ai_attack_reserve: float = 0.4     # fracción de tropas que el autopiloto NUNCA manda (defensa)

    # SDD 67: diplomacia nuclear — una salva con nuclear tarda 24 h (ventana para negociar) y el
    # defensor con `diplomacy` (tech) + `government` (edificio activo) puede ofrecer TRIBUTO
    # (minerales+energía) para que el atacante la cancele. Sin recall unilateral.
    nuclear_travel_seconds: int = 86400
    # SDD 67 v3: para HACER VOLVER (recall) misiles o drones en vuelo necesitás la infraestructura
    # diplomática: tech `diplomacy` + edificio `government` activo. Pedido del usuario. Flag
    # reversible (False = recall libre, comportamiento histórico de drones).
    recall_requires_diplomacy: bool = True
    # SDD 49/67: si un misil NO se intercepta del todo pero había ALGO de capacidad antimisil,
    # impacta a esta fracción (intercepción PARCIAL). Nuclear (intercept_cost 100 = 10 torretas): 10
    # torretas lo bloquean; menos → impacta al 50%. 1.0 = sin parcial (todo o nada, histórico).
    strike_partial_impact_factor: float = 0.5
    # SDD 80: el ATACANTE de un nuclear puede DARLE TIEMPO al defensor (posterga el impacto) para
    # que desarrolle diplomacia y pague tributo. Cada vez suma N horas; acotado a M veces por misil.
    nuclear_grant_time_hours: float = 12.0
    nuclear_time_grants_max: int = 3

    # SDD 66: estado de edificios. OFF = los ataques DESTRUYEN el edificio (histórico). ON = daño
    # GRADUAL a `condition` (rinde a fracción; se destruye recién a 0) + reparar/demoler/mejorar.
    building_condition_enabled: bool = False
    building_repair_cost_fraction: float = 0.5   # reparar cuesta (daño%) × esta fracción del costo
    building_salvage_fraction: float = 0.3       # demoler propio devuelve esta fracción del costo
    building_upgrade_cost_mult: float = 1.5      # cada nivel de mejora cuesta ×este del costo base

    # Lanzadera de misiles (SDD 49): vía de "golpe" intra-planeta, paralela a la flota. PRENDIDO
    # (v1.5): el contenido carga y se puede disparar. Frenos: protección de novato (SDD 11), no
    # atacás aliados, intra-planeta, tope de `ordnance` (alojamiento). El daño de una salva destruye
    # edificios de la base objetivo (defensivos primero; el nuclear, además, los no defensivos +
    # fallout). `building_strike_hp` = aguante por defecto de un edificio sin `hp` propio.
    # Apagable por env (STRIKE_ENABLED=false).
    strike_enabled: bool = True
    building_strike_hp: float = 100.0

    # Drones intra-planeta (SDD 50): PRENDIDO (v1.5). Un "tick" de órbita dura `drone_tick_seconds`;
    # en cada tick las torretas hacen `antiair_power` de daño y cada dron drena `energy_per_tick` de
    # TU energía (freno natural: no hay enjambre eterno gratis). Lazy por timestamp (se calcula al
    # leer, como minería). Apagable por env (DRONES_ENABLED=false).
    drones_enabled: bool = True
    drone_tick_seconds: int = 600   # 10 min por tick de órbita

    # Satélites (SDD 61): recon propio + espía que mapea al enemigo. OFF hasta balancear.
    # Mapeo: 1 satélite sin inhibidores → 100% en `sat_scan_hours_solo` h; N satélites lineal.
    # Inhibidores del defensor: coverage = min(1, Σinhibit_power / nº edificios) → topea %; cada
    # inhibidor cubre `sat_inhibitor_jam` edificios. Órbita LEO `sat_orbit_minutes`; por órbita el
    # satélite drena `1 + sat_drain_per_grade·grado` y los drones del defensor lo bajan con prob
    # `sat_base_loss·drones / resist[grado]` (resist 1/2/4/8). Vida útil ~7d sin escudo.
    satellites_enabled: bool = False
    sat_scan_hours_solo: float = 96.0     # 1 satélite, sin inhibidores → 100% en 96 h
    sat_inhibitor_jam: int = 8            # edificios por inhibidor (fallback; YAML manda)
    sat_orbit_minutes: int = 90          # período orbital LEO real
    sat_drain_per_grade: float = 0.3     # drenaje extra de energía por grado de escudo
    sat_base_loss: float = 0.005         # prob de baja por dron del defensor por órbita (grado 0)

    # Analítica por jugador + gráficos in-app (SDD 51): muestreo throttleado del estado en advance.
    analytics_enabled: bool = True
    analytics_sample_seconds: int = 300   # ≤ 1 muestra cada N s por jugador (barato, lazy)

    # Espionaje / inteligencia (SDD 35).
    spy_energy_cost: float = 5.0
    intel_confidence_half_life_seconds: int = 28800   # 8h: la intel pierde confianza con el tiempo

    # Inteligencia estratégica de NPCs (SDD 29): capa estratégica periódica que lee el scoreboard
    # y fija una postura. Opt-in; cae a la postura previa si el LLM falla (SDD 9).
    npc_strategy_enabled: bool = True
    npc_strategy_interval_seconds: int = 1800   # recalcular la estrategia cada ~30 min/NPC
    npc_strategy_max_tokens: int = 250
    # SDD 65 F3 (bandit): si la postura elegida viene PERDIENDO (wr<30%, ≥4 batallas), pasá a
    # la de mejor historial propio; con prob ε insistí igual (explorar). 0 = sin exploración.
    npc_explore_epsilon: float = 0.2

    # Multiplicadores físicos del planeta (SDD 13 §4). Opt-in: off ⇒ comportamiento actual. Anclados
    # a la Tierra=1.0; gravity_g→tiempo de construcción, insolation→regen de energía. Acotados.
    physics_enabled: bool = False
    physics_gravity_sensitivity: float = 0.5      # pendiente de gravity_g sobre el tiempo de build
    physics_insolation_sensitivity: float = 0.5   # pendiente de insolation sobre la regen
    physics_min_mult: float = 0.5                 # techo inferior de un multiplicador físico
    physics_max_mult: float = 2.0                 # techo superior (evita extremos como Mercurio)
    # mean_temp_c → refrigeración: temperaturas lejos del confort (frío o calor) drenan energía.
    physics_comfort_temp_c: float = 15.0          # temperatura "neutral" (≈ Tierra)
    physics_temp_sensitivity: float = 0.5         # cuánto penaliza el desvío térmico
    physics_temp_scale_c: float = 200.0           # escala del desvío térmico (°C por unidad)

    # Passwordless login por email + código OTP (SDD 6). El login usuario+contraseña sigue
    # existiendo (dev/CLI/tests). En prod este es el camino para el público.
    otp_secret: str = "change-me-otp-secret"   # HMAC del código; fuerte en prod (Secret)
    otp_ttl_minutes: int = 10
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    otp_length: int = 6
    # Defensa anti-abuso del endpoint OTP (SDD 6/14): tope de request-code por IP por minuto.
    # El envío real ya está acotado por allowlist + cooldown; esto frena el martilleo del endpoint.
    otp_rate_limit_per_min: int = 5
    # Allowlist de altas (SDD 14, modo simple): lista de emails autorizados a registrarse,
    # separados por coma. Vacío = registro abierto (comportamiento actual). Si está seteada, solo
    # esos emails (o jugadores ya existentes) reciben código en /auth/request-code. Cambiarla =
    # redeploy/restart. El gate es uniforme (no revela la lista → anti-enumeración).
    allowed_emails: str = ""

    # Admin (SDD 14 v2): email del admin. Si está seteado, /admin/* exige ser admin (ese email
    # o is_admin=True). Vacío = sin gate (dev/test, comportamiento actual).
    admin_email: str = ""
    # SDD 14: si está ON, las altas nuevas nacen 'pending' y no pueden jugar hasta que el admin
    # apruebe. OFF (default) = todos 'active' → no rompe nada existente.
    signup_requires_approval: bool = False

    # Observabilidad (SDD 19): si está seteado, /metrics exige Bearer = este token (Prometheus lo
    # manda por bearerTokenSecret) → no queda público por el gateway. Vacío = abierto (dev).
    metrics_token: str = ""

    # Landing pública (SDD 24): URL base absoluta para og:url/og:image (preview en redes).
    # Ej: https://tu-dominio. Vacío = og relativas (preview pobre, pero la página anda).
    public_url: str = ""

    # Presencia + métricas por entidad (SDD 21).
    presence_window_seconds: int = 90       # "online" = visto en esta ventana
    metrics_per_player: bool = False        # opt-in: gauges por jugador (cardinalidad alta)
    metrics_per_player_max: int = 200       # tope de series por jugador

    # Envío de email: console (default, loguea el código — dev/CI sin SMTP) | smtp | resend
    mail_backend: str = "console"
    mail_from: str = "Online Galaxy War <no-reply@localhost>"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    resend_api_key: str = ""

    # LLM provider — any OpenAI-compatible endpoint: OpenRouter, LiteLLM, Ollama, vLLM…
    # Set LLM_* to point anywhere; if unset, falls back to the OPENROUTER_* values below
    # (back-compat). For Ollama: LLM_BASE_URL=http://host:11434/v1, LLM_MODEL=llama3.1,
    # LLM_API_KEY=ollama (ignored). For LiteLLM: its proxy URL + master key.
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_json_mode: bool = True  # ask for response_format=json_object (LiteLLM/Ollama/OpenAI)
    # LLM local en GPU (SDD 9): la IA es serial (una GPU = una cola), NO escala como la API.
    # El timeout corta la espera y dispara el fallback (NPC→reglas, asistente→determinista).
    # El rate-limit del asistente protege la GPU del pico de "todos preguntan a la vez".
    llm_timeout_seconds: float = 20.0
    advisor_rate_limit_per_min: int = 6   # consultas /advisor/ask por jugador por minuto

    # Legacy OpenRouter knobs (still honored as defaults for the LLM_* above).
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "google/gemma-4-31b-it:free"

    @property
    def allowed_email_set(self) -> set[str]:
        """Emails autorizados (lower, sin espacios). Vacío ⇒ registro abierto."""
        return {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}

    @property
    def llm_key(self) -> str:
        return self.llm_api_key or self.openrouter_api_key

    @property
    def llm_url(self) -> str:
        return self.llm_base_url or self.openrouter_base_url

    @property
    def llm_model_name(self) -> str:
        return self.llm_model or self.openrouter_model

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def db_backend(self) -> str:
        if self.is_sqlite:
            return "sqlite"
        if "postgres" in self.database_url:
            return "postgres"
        return "other"

    def weak_secrets(self) -> list[str]:
        """Nombres de secretos que siguen en su default o son demasiado cortos (< 16 bytes).
        En production el arranque falla si esta lista no está vacía (deuda técnica: secretos
        fuertes en prod). Solo se chequea OTP si el login passwordless está activo (allowlist o
        mailer real); en dev/CLI con login usuario+clave no estorba."""
        weak: list[str] = []
        defaults = {"change-me", "change-me-in-prod", "change-me-otp-secret", ""}
        if self.jwt_secret in defaults or len(self.jwt_secret) < 16:
            weak.append("JWT_SECRET")
        otp_in_use = bool(self.allowed_email_set) or self.mail_backend != "console"
        if otp_in_use and (self.otp_secret in defaults or len(self.otp_secret) < 16):
            weak.append("OTP_SECRET")
        return weak

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in ("production", "prod")

    @property
    def safe_database_url(self) -> str:
        """DB URL with any password redacted (safe to log/show)."""
        import re

        return re.sub(r"://([^:/@]+):[^@]+@", r"://\1:***@", self.database_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
