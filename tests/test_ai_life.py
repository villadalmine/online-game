"""SDD 69 Fase 4 — vida artificial: subir de nivel (evolve_ai) + autopiloto de auto-staffing."""
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import Base_, Building, Bunker, Player, PlayerTech, TrainingOrder
from app.services.ai_life import AiLifeError, evolve_ai, run_ai_autopilot
from app.services.economy import get_or_create_stock
from app.services.onboarding import onboard_player


async def _player(session, name="ai_dev", planet="mars", race="martian"):
    p = Player(username=name, password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    base = await onboard_player(session, p, "milky_way", planet, race)
    p.energy = 100000
    await session.commit()
    return p, base


async def test_evolve_ai_needs_flag_tech_electronics_then_levels_up(session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "artificial_life_enabled", True)
    monkeypatch.setattr(s, "bunkers_enabled", True)
    p, base = await _player(session)
    # sin tech → falla
    try:
        await evolve_ai(session, p)
        raise AssertionError("sin la tech no evoluciona")
    except AiLifeError:
        pass
    session.add(PlayerTech(player_id=p.id, tech_key="artificial_life"))
    # búnker con electrónica + minerales avanzados del natal
    b = Bunker(player_id=p.id, base_id=base.id, food_health=100, water_health=100,
               people_health=100, electronics=1000)
    session.add(b)
    from app.content.registry import get_content
    adv = get_content().resolve_role("martian", "advanced")
    (await get_or_create_stock(session, p.id, adv, "mars")).amount = 100000
    await session.commit()
    r = await evolve_ai(session, p)
    await session.commit()
    assert r["level"] == 1 and "workers" in r["scope"]
    assert p.ai_level == 1
    # se cobró la electrónica (nivel 1 cuesta 200)
    b = (await session.execute(select(Bunker).where(Bunker.id == b.id))).scalar_one()
    assert b.electronics == 800


async def test_autopilot_staffs_mines_with_workers(session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "bunker_autonomy_enabled", True)
    p, base = await _player(session)
    p.ai_level = 1   # nivel con scope [workers]
    # mina activa con worker_slots pero sin obreros → deficit → el autopiloto entrena obreros
    struct = None
    from app.content.registry import get_content
    struct = get_content().resolve_role("martian", "structural")
    session.add(Building(base_id=base.id, building_key="mine", status="active",
                         production_mineral=struct))
    await session.commit()
    n = await run_ai_autopilot(session, p)
    await session.commit()
    assert n > 0
    orders = (await session.execute(
        select(TrainingOrder).join(Base_, TrainingOrder.base_id == Base_.id).where(
            Base_.player_id == p.id, TrainingOrder.unit_key == "worker")
    )).scalars().all()
    assert sum(o.quantity for o in orders) == n


async def test_autopilot_off_without_flag(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "bunker_autonomy_enabled", False)
    p, base = await _player(session)
    p.ai_level = 5
    await session.commit()
    assert await run_ai_autopilot(session, p) == 0


async def test_autopilot_paused_by_switch(session, monkeypatch):
    # SDD 69 F4: botón de parada — con ai_autopilot_on=False el autopiloto no actúa pese al déficit.
    from app.content.registry import get_content
    monkeypatch.setattr(get_settings(), "bunker_autonomy_enabled", True)
    p, base = await _player(session)
    p.ai_level = 1
    p.ai_autopilot_on = False
    struct = get_content().resolve_role("martian", "structural")
    session.add(Building(base_id=base.id, building_key="mine", status="active",
                         production_mineral=struct))
    await session.commit()
    assert await run_ai_autopilot(session, p) == 0   # parado por el jugador


async def test_auto_mines_builds_a_missing_role_mine(session, monkeypatch):
    # SDD 69 F4 sub-fase 2: nivel 2 (scope mines) → levanta una mina de un mineral sin minar.
    monkeypatch.setattr(get_settings(), "bunker_autonomy_enabled", True)
    p, base = await _player(session)
    p.ai_level = 2   # scope incluye mines
    for m in ("iron", "sulfur", "magnesium"):   # fondear para poder construir
        (await get_or_create_stock(session, p.id, m, "mars")).amount = 100000
    await session.commit()
    n = await run_ai_autopilot(session, p)
    await session.commit()
    assert n >= 1
    mines = (await session.execute(
        select(Building).where(Building.base_id == base.id, Building.building_key == "mine")
    )).scalars().all()
    assert len(mines) >= 1 and mines[0].production_mineral in ("iron", "sulfur", "magnesium")


async def test_auto_colonize_with_colony_ship(session, monkeypatch):
    # SDD 69 F4 sub-fase 2: nivel 4 (colonize) + colony_ship + techs → coloniza un planeta.
    from app.models import UnitStock
    monkeypatch.setattr(get_settings(), "bunker_autonomy_enabled", True)
    p, base = await _player(session, name="ai_col", planet="earth", race="terran")
    p.ai_level = 4   # scope incluye colonize
    for t in ("antigravity", "thermal_shielding"):   # mars colonizable p/ terran
        session.add(PlayerTech(player_id=p.id, tech_key=t))
    session.add(UnitStock(player_id=p.id, unit_key="colony_ship", quantity=1))
    await session.commit()
    n = await run_ai_autopilot(session, p)
    await session.commit()
    assert n >= 1
    planets = {b.planet_key for b in (await session.execute(
        select(Base_).where(Base_.player_id == p.id))).scalars()}
    assert len(planets) >= 2   # colonizó al menos un planeta nuevo


async def test_brain_auto_prefers_better_route(session, monkeypatch):
    # SDD 81 v2: 'auto' es un bandit — prueba primero la ruta con mejor tasa de aplicadas y
    # registra el resultado per-jugador (para el readout in-game).
    import json

    from app.services import ai_life
    s = get_settings()
    monkeypatch.setattr(s, "ai_autopilot_brain_enabled", True)
    monkeypatch.setattr(s, "ai_brain_min_level", 1)
    monkeypatch.setattr(s, "ai_brain_explore", 0.0)   # exploit puro: elige el mejor, sin explorar
    p, _ = await _player(session, name="ai_brainer")
    p.ai_level = 3
    p.ai_brain_mode = "auto"
    p.ai_brain_stats = json.dumps({"gpu": {"llm": 0, "fallback": 10},   # gpu venía mal
                                   "cloud": {"llm": 10, "fallback": 0}})  # cloud venía bien
    await session.commit()
    tried = []

    async def fake_pick(session, player, scope, route):
        tried.append(route)
        return "workers" if route == "cloud" else None
    monkeypatch.setattr(ai_life, "_llm_pick_skill", fake_pick)
    pick, route = await ai_life._resolve_brain(session, p, ["workers"])
    assert pick == "workers" and route == "cloud"   # eligió y devolvió la ruta de mejor tasa
    assert tried[0] == "cloud"                       # probó primero la mejor (no gpu)


async def test_brain_records_fallback_when_route_fails(session, monkeypatch):
    # SDD 81 v2: una ruta que no logra elegir se marca fallback al toque (y decae lo viejo).
    from app.services import ai_life
    s = get_settings()
    monkeypatch.setattr(s, "ai_autopilot_brain_enabled", True)
    monkeypatch.setattr(s, "ai_brain_min_level", 1)
    p, _ = await _player(session, name="ai_misser")
    p.ai_level = 3
    p.ai_brain_mode = "gpu"
    await session.commit()

    async def no_pick(session, player, scope, route):
        return None
    monkeypatch.setattr(ai_life, "_llm_pick_skill", no_pick)
    pick, route = await ai_life._resolve_brain(session, p, ["workers"])
    assert pick is None and route is None            # sin pick → reglas
    assert ai_life.brain_stats_report(p)["gpu"]["fallback"] >= 1


async def test_brain_quality_weighs_impact(session, monkeypatch):
    # SDD 81 v2/v4: la calidad del cerebro PESA cuánto rindió la skill elegida (acciones, con tope).
    from app.services import ai_life
    s = get_settings()
    monkeypatch.setattr(s, "ai_autopilot_brain_enabled", True)
    monkeypatch.setattr(s, "bunker_autonomy_enabled", True)
    p, _ = await _player(session, name="ai_prod")
    p.ai_level = 1              # scope = [workers]
    await session.commit()

    async def pick_workers(session, player, scope):
        return "workers", "gpu"
    monkeypatch.setattr(ai_life, "_resolve_brain", pick_workers)

    async def workers_did_2(session, player, settings, q=0.5):
        return 2               # la skill priorizada produjo 2 acciones
    monkeypatch.setattr(ai_life, "_auto_workers", workers_did_2)
    await ai_life.run_ai_autopilot(session, p)
    assert ai_life.brain_stats_report(p)["gpu"]["applied"] == 2   # crédito = impacto (2), no 1


async def test_brain_daily_budget_caps_llm(session, monkeypatch):
    # SDD 81 v4: tope diario de llamadas LLM del cerebro → agotado cae a reglas (control de costo).
    from app.services import ai_life
    s = get_settings()
    monkeypatch.setattr(s, "ai_autopilot_brain_enabled", True)
    monkeypatch.setattr(s, "ai_brain_min_level", 1)
    monkeypatch.setattr(s, "ai_brain_llm_calls_per_day", 1)   # solo 1 llamada por día
    p, _ = await _player(session, name="ai_budget")
    p.ai_level = 3
    p.ai_brain_mode = "gpu"
    await session.commit()
    calls = []

    async def fake_pick(session, player, scope, route):
        calls.append(route)
        return "workers"
    monkeypatch.setattr(ai_life, "_llm_pick_skill", fake_pick)
    assert (await ai_life._resolve_brain(session, p, ["workers"]))[0] == "workers"  # 1ra: usa cupo
    assert await ai_life._resolve_brain(session, p, ["workers"]) == (None, None)    # 2da: sin cupo
    assert len(calls) == 1                                    # el LLM se llamó una sola vez


async def test_auto_research_prioritizes_blocked_skill_tech(session, monkeypatch):
    # SDD 81 v3: si un skill del scope está bloqueado por una tech, research va por esa (o prereq).
    from app.services import ai_life
    p, _ = await _player(session, name="ai_researcher")
    p.energy = 1_000_000
    await session.commit()
    picked = []

    async def fake_start(session, player, tech_key):
        picked.append(tech_key)                      # registrá qué eligió investigar
    monkeypatch.setattr("app.services.research.start_research", fake_start)
    # scope con 'bunker' bloqueado (sin bunker_engineering ni su cadena de prereqs)
    from app.content.registry import get_content
    expected = ai_life._first_researchable_toward(get_content(), "bunker_engineering", set())
    assert expected is not None                      # hay un paso researchable hacia el gate
    n = await ai_life._auto_research(session, p, ["research", "bunker"])
    # priorizó ese paso (no una tech barata cualquiera)
    assert n == 1 and picked and picked[0] == expected
    # y el gate de 'colonize' apunta a la tech de la nave colonizadora (antigravity)
    assert ai_life._SKILL_GATE_TECH["colonize"] == "antigravity"


async def test_brain_rules_mode_never_calls_llm(session, monkeypatch):
    # cerebro determinista (default): no piensa con el LLM, devuelve (None, None) = reglas.
    from app.services import ai_life
    s = get_settings()
    monkeypatch.setattr(s, "ai_autopilot_brain_enabled", True)
    p, _ = await _player(session, name="ai_ruler")
    p.ai_level = 5
    p.ai_brain_mode = "rules"
    await session.commit()

    async def boom(*a, **k):
        raise AssertionError("no debería llamar al LLM en modo rules")
    monkeypatch.setattr(ai_life, "_llm_pick_skill", boom)
    assert await ai_life._resolve_brain(session, p, ["workers"]) == (None, None)


async def test_auto_bunker_digs_then_builds_room(session, monkeypatch):
    # SDD 78 v8: la IA cava el búnker y después construye una sala (electrónica).
    from app.content.registry import get_content
    from app.models import Bunker, BunkerRoom, PlayerTech
    from app.services.ai_life import _auto_bunker
    monkeypatch.setattr(get_settings(), "bunkers_enabled", True)
    p, base = await _player(session, name="ai_digger")
    session.add(PlayerTech(player_id=p.id, tech_key="bunker_engineering"))
    for role in ("structural", "energetic", "advanced"):
        mk = get_content().resolve_role(p.race_key, role)
        (await get_or_create_stock(session, p.id, mk, base.planet_key)).amount = 100000
    await session.commit()
    assert await _auto_bunker(session, p) == 1     # cava
    await session.commit()
    assert (await session.execute(
        select(Bunker).where(Bunker.base_id == base.id))).scalar_one_or_none() is not None
    assert await _auto_bunker(session, p) == 1     # construye una sala
    await session.commit()
    assert (await session.execute(select(BunkerRoom))).scalars().all()


async def test_brain_valid_pick_counts_applied_even_if_idle(session, monkeypatch):
    # v5-fix: si el LLM elige una skill VÁLIDA pero el juego no tenía nada que hacer esa jugada, el
    # cerebro igual "APLICÓ" (readout NO queda pegado en 0%). El impacto solo pesa para el bandit.
    from app.services import ai_life
    s = get_settings()
    monkeypatch.setattr(s, "ai_autopilot_brain_enabled", True)
    monkeypatch.setattr(s, "bunker_autonomy_enabled", True)
    p, _ = await _player(session, name="ai_idle")
    p.ai_level = 1              # scope = [workers]
    await session.commit()

    async def pick_workers(session, player, scope):
        return "workers", "gpu"
    monkeypatch.setattr(ai_life, "_resolve_brain", pick_workers)

    async def workers_idle(session, player, settings, q=0.5):
        return 0               # la skill priorizada no produjo nada esta jugada
    monkeypatch.setattr(ai_life, "_auto_workers", workers_idle)
    await ai_life.run_ai_autopilot(session, p)
    rep = ai_life.brain_stats_report(p)["gpu"]
    assert rep["applied"] >= 1 and rep["fallback"] == 0   # contó aplicada (no 0%/fallback)


async def test_auto_bunker_develops_colony_bunkers(session, monkeypatch):
    # v5-fix: el autopiloto desarrolla el búnker de TODAS las bases (antes solo la natal → colonias
    # con búnkeres vacíos). Con natal ya cavada, la siguiente jugada cava el de la colonia.
    from app.content.registry import get_content
    from app.models import Bunker
    from app.services.ai_life import _auto_bunker
    monkeypatch.setattr(get_settings(), "bunkers_enabled", True)
    p, home = await _player(session, name="ai_multi")
    session.add(PlayerTech(player_id=p.id, tech_key="bunker_engineering"))
    colony = Base_(player_id=p.id, planet_key="venus", name="col")
    session.add(colony)
    for role in ("structural", "energetic", "advanced"):
        mk = get_content().resolve_role(p.race_key, role)
        for pk in ("mars", "venus"):
            (await get_or_create_stock(session, p.id, mk, pk)).amount = 100000
    await session.commit()
    assert await _auto_bunker(session, p) == 1   # cava la natal primero
    await session.commit()
    assert await _auto_bunker(session, p) == 1   # ahora cava la colonia (antes no hacía nada)
    await session.commit()
    dug = {b.base_id for b in (await session.execute(select(Bunker))).scalars()}
    assert home.id in dug and colony.id in dug   # las DOS bases tienen búnker


async def test_npc_llm_state_with_datetime_serializes(session, monkeypatch):
    # Fix prod: el estado NPC puede traer datetimes (ETAs, last_battle); json.dumps(default=str)
    # evita el "datetime is not JSON serializable" que tumbaba TODO el cerebro LLM.
    from datetime import UTC, datetime

    from app.services import npc
    seen = {}

    async def fake_chat(messages, **kw):
        seen["user"] = messages[-1]["content"]        # que haya serializado sin romper
        return '{"posture":"expand","target":null,"why":"ok"}'
    monkeypatch.setattr(npc, "llm_chat", fake_chat)
    state = {"personality": "x", "eta": datetime.now(UTC), "__user": "npc:t", "__model": None}
    out = await npc._llm_strategy(state)
    assert out.get("posture") == "expand" and "eta" in seen["user"]


async def test_auto_housing_builds_when_slots_short(session, monkeypatch):
    # SDD 78 v8: si a un dominio le faltan plazas, construye el edificio que aloja.
    from app.content.registry import get_content
    from app.models import Building, UnitStock
    from app.services.ai_life import _auto_housing
    s = get_settings()
    monkeypatch.setattr(s, "base_housing_per_domain", 0)   # sin gracia → falta plaza ya
    p, base = await _player(session, name="ai_houser")
    session.add(UnitStock(player_id=p.id, unit_key="soldier", quantity=20))
    struct = get_content().resolve_role(p.race_key, "structural")
    (await get_or_create_stock(session, p.id, struct, base.planet_key)).amount = 100000
    await session.commit()
    assert await _auto_housing(session, p) == 1
    await session.commit()
    blds = {b.building_key for b in (await session.execute(
        select(Building).where(Building.base_id == base.id))).scalars()}
    assert "barracks" in blds   # construyó el cuartel (aloja infantería)


async def test_auto_defend_builds_turret_on_undefended_base(session, monkeypatch):
    # SDD 78: nivel 5 (guardiana, skill defend) → torreta en la base sin defensa.
    from app.content.registry import get_content
    s = get_settings()
    monkeypatch.setattr(s, "bunker_autonomy_enabled", True)
    p, base = await _player(session, name="ai_guard")
    p.ai_level = 5
    struct = get_content().resolve_role("martian", "structural")
    (await get_or_create_stock(session, p.id, struct, "mars")).amount = 100000
    # la torreta requiere research_lab activo + tech weapons
    session.add(Building(base_id=base.id, building_key="research_lab", status="active"))
    session.add(PlayerTech(player_id=p.id, tech_key="weapons"))
    await session.commit()
    await run_ai_autopilot(session, p)
    await session.commit()
    turrets = (await session.execute(
        select(Building).where(Building.base_id == base.id, Building.building_key == "turret")
    )).scalars().all()
    assert turrets   # fortificó sola la base indefensa


async def test_auto_spy_launches_at_a_rival(session, monkeypatch):
    # SDD 78 v3: con satélites ON y un espía, la IA lo lanza a un rival que aún no espía.
    from app.models import SatelliteMission, UnitStock
    from app.services.ai_life import _auto_spy
    s = get_settings()
    monkeypatch.setattr(s, "satellites_enabled", True)
    p, base = await _player(session, name="ai_spy")
    foe, fbase = await _player(session, name="ai_target")
    foe.galaxy_instance_id = p.galaxy_instance_id
    session.add(UnitStock(player_id=p.id, unit_key="spy_satellite", quantity=1))
    await session.commit()
    assert await _auto_spy(session, p) == 1
    await session.commit()
    sats = (await session.execute(
        select(SatelliteMission).where(SatelliteMission.owner_id == p.id)
    )).scalars().all()
    assert sats and sats[0].target_id == foe.id


async def test_auto_repopulate_after_recent_attack(session, monkeypatch):
    # SDD 78 v5: si te atacaron hace poco y te faltan edificios, reconstruye con electrónica.
    from datetime import UTC, datetime

    from app.models import BunkerRoom, CombatLog, PlayerTech
    from app.services.ai_life import _auto_repopulate
    from app.services.bunkers import dig
    monkeypatch.setattr(get_settings(), "bunkers_enabled", True)
    p, base = await _player(session, name="ai_rebuilder")
    foe, fbase = await _player(session, name="ai_attacker")
    session.add(PlayerTech(player_id=p.id, tech_key="bunker_engineering"))
    await session.flush()
    b = await dig(session, p, base.id)
    session.add(BunkerRoom(bunker_id=b.id, room_key="research_room", cell=0, status="active",
                           completes_at=datetime.now(UTC)))
    b.electronics = 1000.0
    session.add(CombatLog(attacker_id=foe.id, defender_id=p.id, target_base_id=base.id,
                          outcome="attacker"))       # te atacaron y perdiste hace un rato
    await session.commit()
    assert await _auto_repopulate(session, p) == 1   # reconstruyó un set
    # sin ataque reciente NO reconstruye
    p2, base2 = await _player(session, name="ai_calm")
    session.add(PlayerTech(player_id=p2.id, tech_key="bunker_engineering"))
    await session.flush()
    b2 = await dig(session, p2, base2.id)
    b2.electronics = 1000.0
    await session.commit()
    assert await _auto_repopulate(session, p2) == 0


async def test_auto_expedition_sends_to_a_moon(session):
    # SDD 78 v4: con un shuttle, la IA manda una expedición a una luna de su galaxia.
    from app.models import ExpeditionOrder, UnitStock
    from app.services.ai_life import _auto_expedition
    p, base = await _player(session, name="ai_explorer")   # mars → phobos/deimos (shuttle)
    session.add(UnitStock(player_id=p.id, unit_key="shuttle", quantity=1))
    await session.commit()
    assert await _auto_expedition(session, p) == 1
    await session.commit()
    exps = (await session.execute(
        select(ExpeditionOrder).where(ExpeditionOrder.player_id == p.id)
    )).scalars().all()
    assert exps   # mandó una expedición


async def test_meta_best_unit_reads_learned_meta(session):
    # SDD 78 v6: la IA elige la composición que MÁS gana según la meta (winrate_by_unit, SDD 41).
    import json

    from app.models import MetaInsight
    from app.services.ai_life import _meta_best_unit
    assert await _meta_best_unit(session) is None    # sin datos → no sesga
    session.add(MetaInsight(key="winrate_by_unit", sample_n=20, payload=json.dumps(
        {"tank": {"rate": 0.8, "n": 10}, "soldier": {"rate": 0.4, "n": 8}})))
    await session.commit()
    assert await _meta_best_unit(session) == "tank"


async def test_ai_brain_llm_mode_picks_skill(session, monkeypatch):
    # SDD 81: en modo gpu/cloud el cerebro pide al LLM qué priorizar; rules/flag off → determinista.
    import app.services.llm as llm_mod
    from app.services.ai_life import _resolve_brain
    s = get_settings()
    monkeypatch.setattr(s, "ai_autopilot_brain_enabled", True)
    monkeypatch.setattr(s, "ai_brain_min_level", 1)

    async def fake_chat(messages, **kw):
        return "mines"
    monkeypatch.setattr(llm_mod, "llm_chat", fake_chat)
    p, base = await _player(session, name="ai_brainy")
    p.ai_level = 2
    p.ai_brain_mode = "gpu"
    await session.commit()
    scope = ["workers", "mines", "trade"]
    assert await _resolve_brain(session, p, scope) == ("mines", "gpu")   # el LLM eligió
    p.ai_brain_mode = "rules"
    assert await _resolve_brain(session, p, scope) == (None, None)       # determinista
    p.ai_brain_mode = "gpu"
    monkeypatch.setattr(s, "ai_autopilot_brain_enabled", False)
    assert await _resolve_brain(session, p, scope) == (None, None)       # flag off → determinista


async def test_ai_posture_from_winrate(session):
    # SDD 78 v7: la IA elige postura con lo aprendido (gana→agresiva, pierde→defensiva).
    from app.models import CombatLog
    from app.services.ai_life import ai_posture
    p, base = await _player(session, name="ai_posturer")
    foe, fbase = await _player(session, name="ai_rival")
    assert await ai_posture(session, p) == "balanced"        # sin datos
    for _ in range(5):
        session.add(CombatLog(attacker_id=p.id, defender_id=foe.id, target_base_id=fbase.id,
                              outcome="attacker"))
    await session.commit()
    assert await ai_posture(session, p) == "aggressive"      # viene ganando → agresiva


async def test_own_attack_winrate_from_combat_log(session):
    # SDD 78 v3: la IA lee su win-rate de ataque (para atacar más cauta si viene perdiendo).
    from app.models import CombatLog
    from app.services.ai_life import _own_attack_winrate
    p, base = await _player(session, name="ai_warrior")
    foe, fbase = await _player(session, name="ai_foe")
    for outcome in ("attacker", "attacker", "defender", "defender"):
        session.add(CombatLog(attacker_id=p.id, defender_id=foe.id, target_base_id=fbase.id,
                              outcome=outcome))
    await session.commit()
    n, wr = await _own_attack_winrate(session, p)
    assert n == 4 and abs(wr - 0.5) < 1e-9


async def test_auto_diplomacy_offers_tribute_under_nuke(session):
    # SDD 78: con government + diplomacy, la IA ofrece tributo ante un nuclear entrante.
    import json

    from app.content.registry import get_content
    from app.models import PlayerTech, StrikeMission
    from app.services.ai_life import _auto_diplomacy
    p, base = await _player(session, name="ai_diplo")
    foe, fbase = await _player(session, name="ai_nuker")
    session.add(Building(base_id=base.id, building_key="government", status="active"))
    session.add(PlayerTech(player_id=p.id, tech_key="diplomacy"))
    struct = get_content().resolve_role("martian", "structural")
    (await get_or_create_stock(session, p.id, struct, "mars")).amount = 100000
    m = StrikeMission(attacker_id=foe.id, defender_id=p.id, launcher_base_id=fbase.id,
                      target_base_id=base.id, force=json.dumps({"nuclear_missile": 1}),
                      status="outbound")
    session.add(m)
    await session.commit()
    assert await _auto_diplomacy(session, p) == 1
    await session.commit()
    await session.refresh(m)
    assert m.tribute   # ofreció tributo para cancelar el nuclear


async def test_ai_learning_grows_with_experience(session):
    # SDD 78: la calidad EFECTIVA sube con la experiencia (jugadas del journal).
    from app.models import GameEvent
    from app.services.ai_life import ai_learning
    p, base = await _player(session, name="ai_learner")
    p.ai_level = 3
    await session.commit()
    l0 = await ai_learning(session, p)
    assert l0["xp"] == 0 and l0["quality_eff"] == l0["quality_base"]
    for _ in range(50):
        session.add(GameEvent(type="ai_autopilot", player_id=p.id, payload="{}"))
    await session.commit()
    l1 = await ai_learning(session, p)
    assert l1["xp"] == 50 and l1["quality_eff"] > l1["quality_base"]   # aprendió


async def test_auto_attack_hits_a_beatable_enemy(session, monkeypatch):
    # SDD 78: nivel 6 (attack) → ataca a un rival que supera claramente.
    from app.models import AttackMission, UnitStock
    s = get_settings()
    monkeypatch.setattr(s, "bunker_autonomy_enabled", True)
    monkeypatch.setattr(s, "garrison_enabled", False)   # usar el ejército global (simple)
    atk, abase = await _player(session, name="ai_atk")
    atk.ai_level = 6
    dfn, dbase = await _player(session, name="ai_vic")
    dfn.protected_until = None                          # sin protección de novato
    session.add(UnitStock(player_id=atk.id, unit_key="soldier", quantity=100))
    await session.commit()
    n = await run_ai_autopilot(session, atk)
    await session.commit()
    assert n >= 1   # el nivel 5 puede hacer varias acciones; nos importa que atacó
    missions = (await session.execute(
        select(AttackMission).where(AttackMission.attacker_id == atk.id))).scalars().all()
    assert missions and missions[0].target_base_id == dbase.id


async def test_npc_effective_epsilon_scales_with_ceiling(monkeypatch):
    # SDD 69 F4: el techo (admin) da más exploración a los NPC. Default 0 → base; sube y se topea.
    from app.services.npc import npc_effective_epsilon, set_player_ai_ceiling
    set_player_ai_ceiling(0)                 # SDD 78: reset del global de módulo
    s = get_settings()
    monkeypatch.setattr(s, "npc_explore_epsilon", 0.2)
    monkeypatch.setattr(s, "artificial_life_npc_ceiling", 0)
    assert npc_effective_epsilon() == 0.2
    monkeypatch.setattr(s, "artificial_life_npc_ceiling", 2)
    assert abs(npc_effective_epsilon() - 0.36) < 1e-9
    monkeypatch.setattr(s, "artificial_life_npc_ceiling", 100)
    assert npc_effective_epsilon() == 0.6   # topeado
    # SDD 78: el mayor ai_level de los JUGADORES también sube el techo (entrenás vos, suben las NPC)
    monkeypatch.setattr(s, "artificial_life_npc_ceiling", 0)
    set_player_ai_ceiling(3)
    assert abs(npc_effective_epsilon() - (0.2 + 0.08 * 3)) < 1e-9
    set_player_ai_ceiling(0)                 # cleanup del global
