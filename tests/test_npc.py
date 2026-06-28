from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import Settings
from app.core.security import hash_password
from app.models import AttackMission, Base_, Building, Player
from app.services import npc as npc_mod
from app.services.npc import (
    LlmBrain,
    RuleBasedBrain,
    _load_memory,
    _npc_state,
    ensure_npcs,
    run_npc_turn,
)
from app.services.onboarding import onboard_player


def _settings(**kw) -> Settings:
    # _env_file=None so the local .env can't leak into the assertion.
    return Settings(_env_file=None, **kw)


async def _npc(session, race="npc_martian") -> Player:
    res = await session.execute(select(Player).where(Player.username == race))
    return res.scalar_one()


async def _base_of(session, player) -> Base_:
    res = await session.execute(select(Base_).where(Base_.player_id == player.id))
    return res.scalars().first()


async def _make_mission(session, attacker, defender, **kw) -> AttackMission:
    base = await _base_of(session, defender)
    m = AttackMission(
        attacker_id=attacker.id,
        defender_id=defender.id,
        target_base_id=base.id,
        force='{"tank": 1}',
        status="outbound",
        arrives_at=datetime.now(UTC) + timedelta(seconds=120),
        **kw,
    )
    session.add(m)
    await session.flush()
    return m


async def test_ensure_npcs_one_per_race_idempotent(session):
    assert await ensure_npcs(session) == 3
    assert await ensure_npcs(session) == 0  # idempotent
    res = await session.execute(select(Player).where(Player.is_npc.is_(True)))
    assert {n.race_key for n in res.scalars()} == {"terran", "martian", "venusian"}


async def test_rule_brain_first_action_builds_a_mine(session):
    await ensure_npcs(session)
    npc = await _npc(session)
    action = await run_npc_turn(session, npc)
    await session.commit()
    assert action and "mine" in action
    res = await session.execute(select(Building).where(Building.building_key == "mine"))
    assert res.first() is not None


async def test_rule_brain_trains_worker_to_staff_mines(session):
    # SDD 47: con minas activas y sin obreros, el NPC entrena un obrero para operarlas (staffing).
    from app.content.registry import get_content
    from app.models import TrainingOrder
    from app.services.economy import get_or_create_stock
    await ensure_npcs(session)
    npc = await _npc(session)
    base = await _base_of(session, npc)
    roles = get_content().races[npc.race_key]["resource_roles"]
    for mineral in (roles["structural"], roles["energetic"]):   # minas core ya presentes y activas
        session.add(Building(base_id=base.id, building_key="mine", status="active",
                             production_mineral=mineral))
    for m in get_content().minerals:                            # recursos de sobra en su planeta
        (await get_or_create_stock(session, npc.id, m, npc.planet_key)).amount = 100000
    npc.energy = 100000
    await session.flush()
    action = await run_npc_turn(session, npc)
    await session.commit()
    assert action == "train worker (staffing)", action
    q = await session.execute(select(TrainingOrder).where(TrainingOrder.base_id == base.id,
                                                          TrainingOrder.unit_key == "worker"))
    assert q.first() is not None


def test_npc_llm_choice_gpu_vs_cloud(monkeypatch):
    # Comparación GPU vs nube: el NPC designado usa el modelo de nube; el resto, GPU local.
    from app.core.config import get_settings
    from app.models import Player
    from app.services.npc import npc_llm_choice
    s = get_settings()
    monkeypatch.setattr(s, "npc_cloud_username", "npc_venusian")
    monkeypatch.setattr(s, "npc_cloud_model", "gemma4-paid")
    monkeypatch.setattr(s, "npc_llm_model", "local-gpu")
    assert npc_llm_choice(Player(username="npc_venusian")) == ("gemma4-paid", "cloud")
    assert npc_llm_choice(Player(username="npc_terran")) == ("local-gpu", "gpu")


async def test_llm_fallback_is_remembered_for_learning(session):
    # APRENDIZAJE: cuando la jugada del LLM falla, la NPC la memoriza con el motivo → el próximo
    # prompt la trae en recent_actions y el modelo no la repite.
    await ensure_npcs(session)
    npc = await _npc(session)

    async def boom(state):
        raise RuntimeError("sin energia")

    await LlmBrain(decide=boom).act(session, npc)
    await session.commit()
    npc = await _npc(session)
    assert any("intento LLM" in e and "falló" in e for e in _load_memory(npc))


async def test_npc_turn_records_action_metric(session):
    # Observabilidad: cada turno de NPC registra qué hizo (game_npc_actions_total) para entender
    # cómo juega la IA y si mejora. Ver SDD/CHANGELOG métricas NPC.
    from app.core import metrics
    await ensure_npcs(session)
    npc = await _npc(session)
    await run_npc_turn(session, npc)
    await session.commit()
    out = metrics.render()
    assert "game_npc_actions_total" in out


async def test_llm_brain_dispatches_decided_action(session):
    await ensure_npcs(session)
    npc = await _npc(session)

    async def fake_decide(state):
        # prompt state includes personality + memory for richer, in-character play
        assert "minerals" in state and "build_options" in state
        assert state["personality"] and "recent_actions" in state
        return {"action": "build", "building": "mine", "mineral": "iron"}

    desc = await LlmBrain(decide=fake_decide).act(session, npc)
    await session.commit()
    assert desc == "llm build mine (iron)"


async def test_npc_state_has_personality_per_race(session):
    await ensure_npcs(session)
    martian = await _npc(session, "npc_martian")
    venusian = await _npc(session, "npc_venusian")
    sm = await _npc_state(session, martian)
    sv = await _npc_state(session, venusian)
    assert sm["personality"] != sv["personality"]
    assert "agresiv" in sm["personality"].lower()  # martian = belicoso


async def test_memory_accumulates_across_turns(session):
    await ensure_npcs(session)
    npc = await _npc(session)
    for _ in range(3):
        await run_npc_turn(session, npc)
        await session.commit()
        npc = await _npc(session)
    assert len(_load_memory(npc)) == 3


# ---- tactical behavior ------------------------------------------------------

async def test_rule_brain_recalls_fleet_when_under_attack(session):
    await ensure_npcs(session)
    npc = await _npc(session, "npc_martian")
    enemy = await _npc(session, "npc_terran")
    await _make_mission(session, npc, enemy)       # our fleet is away (outbound)
    await _make_mission(session, enemy, npc)       # an attack is inbound on us
    await session.commit()

    action = await RuleBasedBrain().act(session, npc)
    assert action == "recall fleet to defend"


async def test_rule_brain_builds_turret_when_under_attack_without_fleet(session):
    from app.models import PlayerTech
    await ensure_npcs(session)
    npc = await _npc(session, "npc_martian")
    enemy = await _npc(session, "npc_terran")
    await _make_mission(session, enemy, npc)       # inbound attack, no fleet of ours
    # SDD 1 (árbol): la torreta pide Laboratorio activo + investigar 'weapons'
    base = (await session.execute(select(Base_).where(Base_.player_id == npc.id))).scalars().first()
    session.add(Building(base_id=base.id, building_key="research_lab", status="active"))
    session.add(PlayerTech(player_id=npc.id, tech_key="weapons"))
    await session.commit()

    action = await RuleBasedBrain().act(session, npc)
    assert "turret" in action


async def test_llm_state_exposes_tactical_info(session):
    await ensure_npcs(session)
    npc = await _npc(session, "npc_martian")
    # a non-allied human enemy (NPCs are all allied with each other now)
    human = Player(username="human", password_hash=hash_password("secret123"))
    session.add(human)
    await session.flush()
    await onboard_player(session, human, "milky_way", "earth", "terran")
    await session.commit()
    await _make_mission(session, human, npc)
    await session.commit()
    state = await _npc_state(session, npc)
    assert state["incoming_attacks"] and "reachable_moons" in state
    assert "defense_estimate" in state["enemies"][0]


async def test_llm_brain_can_recall(session):
    await ensure_npcs(session)
    npc = await _npc(session, "npc_martian")
    enemy = await _npc(session, "npc_terran")
    mission = await _make_mission(session, npc, enemy)
    await session.commit()
    mid = mission.id

    async def decide(state):
        return {"action": "recall", "mission_id": mid}

    desc = await LlmBrain(decide=decide).act(session, npc)
    await session.commit()
    assert desc == f"llm recall {mid}"


async def test_llm_brain_falls_back_to_rules_on_error(session):
    await ensure_npcs(session)
    npc = await _npc(session)

    async def boom(state):
        raise RuntimeError("openrouter down")

    desc = await LlmBrain(decide=boom).act(session, npc)
    await session.commit()
    assert desc and "mine" in desc  # rules took over


def test_llm_settings_prefer_llm_then_fall_back_to_openrouter():
    # Explicit LLM_* wins (point at Ollama/LiteLLM/anything OpenAI-compatible).
    s = _settings(llm_base_url="http://ollama:11434/v1", llm_model="llama3.1", llm_api_key="x")
    assert s.llm_url == "http://ollama:11434/v1"
    assert s.llm_model_name == "llama3.1"
    assert s.llm_key == "x"
    # With LLM_* unset, the legacy OPENROUTER_* values are used (back-compat).
    s2 = _settings(
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_model="m",
        openrouter_api_key="k",
    )
    assert s2.llm_url == "https://openrouter.ai/api/v1"
    assert s2.llm_model_name == "m"
    assert s2.llm_key == "k"


async def test_llm_decide_posts_to_configured_endpoint_with_json_mode(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '{"action":"none"}'}}]}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            captured.update(url=url, headers=headers, json=json)
            return FakeResp()

    from app.services import llm as llm_mod

    cfg = _settings(
        npc_brain="llm",
        llm_base_url="http://ollama:11434/v1",
        llm_model="llama3.1",
        llm_api_key="secret",
    )
    # transport lives in app.services.llm now; the NPC builds the prompt and delegates.
    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(llm_mod, "get_settings", lambda: cfg)
    monkeypatch.setattr(npc_mod, "get_settings", lambda: cfg)

    action = await npc_mod._llm_decide({"personality": "rudo"})
    assert action == {"action": "none"}
    assert captured["url"] == "http://ollama:11434/v1/chat/completions"
    assert captured["json"]["model"] == "llama3.1"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert captured["headers"]["Authorization"] == "Bearer secret"


def _capturing_client(captured):
    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": '{"action":"none"}'}}]}

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None):
            captured.update(url=url, headers=headers, json=json)
            return FakeResp()
    return FakeClient


async def test_llm_chat_sends_user_for_billing(monkeypatch):
    # SDD 28: el campo `user` viaja en el payload → LiteLLM lo etiqueta end_user (monetización).
    from app.services import llm as llm_mod
    captured = {}
    cfg = _settings(llm_base_url="http://x/v1", llm_model="m", llm_api_key="k")
    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _capturing_client(captured))
    monkeypatch.setattr(llm_mod, "get_settings", lambda: cfg)
    await llm_mod.llm_chat([{"role": "user", "content": "hola"}], user="player:bob")
    assert captured["json"]["user"] == "online-game:player:bob"   # app-tagged (métricas por app)


async def test_npc_decide_attributes_user_and_keeps_it_out_of_prompt(monkeypatch):
    # SDD 28: el NPC pasa user=npc:<nombre> SIN filtrarlo al prompt del modelo.
    from app.services import llm as llm_mod
    captured = {}
    cfg = _settings(npc_brain="llm", llm_base_url="http://x/v1", llm_model="m", llm_api_key="k")
    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _capturing_client(captured))
    monkeypatch.setattr(llm_mod, "get_settings", lambda: cfg)
    monkeypatch.setattr(npc_mod, "get_settings", lambda: cfg)
    await npc_mod._llm_decide({"personality": "rudo", "__user": "npc:zorg"})
    assert captured["json"]["user"] == "online-game:npc:zorg"   # app-tagged (métricas por app)
    # __user no debe aparecer en el contenido enviado al modelo
    assert "__user" not in captured["json"]["messages"][1]["content"]


async def test_npc_taunts_human_on_attack(session):
    # An NPC attacking a human sends an in-character taunt notification.
    from app.content.registry import get_content
    from app.models import Notification
    from app.services.combat import start_attack
    from app.services.training import get_or_create_unit_stock

    await ensure_npcs(session)
    npc = await _npc(session, "npc_martian")
    human = Player(username="prey", password_hash=hash_password("secret123"))
    session.add(human)
    await session.flush()
    await onboard_player(session, human, "milky_way", "earth", "terran")
    human.protected_until = None  # SDD 11: sin protección para poder ser atacado en el test
    (await get_or_create_unit_stock(session, npc.id, "tank")).quantity = 5
    await session.commit()

    base = await _base_of(session, human)
    await start_attack(session, npc, base.id, {"tank": 3})
    await session.commit()

    res = await session.execute(
        select(Notification).where(
            Notification.player_id == human.id, Notification.type == "npc_taunt"
        )
    )
    taunts = list(res.scalars())
    assert taunts, "el humano debería recibir un taunt del NPC"
    lines = get_content().races["martian"]["taunts"]["attack"]
    assert any(any(line in n.message for line in lines) for n in taunts)


async def test_rule_brain_ganks_the_leading_human(session):
    # With several beatable humans, NPCs coordinate on the highest-scoring one (rivalry).
    from app.models import ResourceStock
    from app.services.economy import get_or_create_stock
    from app.services.training import get_or_create_unit_stock

    await ensure_npcs(session)

    async def add_human(name, planet):
        h = Player(username=name, password_hash=hash_password("secret123"))
        session.add(h)
        await session.flush()
        await onboard_player(session, h, "milky_way", planet, "terran")
        h.protected_until = None  # SDD 11: atacables en el test (sin protección de novato)
        return h

    await add_human("weak_human", "earth")
    leader = await add_human("leader_human", "mercury")
    # Raise the leader's score without adding any defense.
    (await get_or_create_stock(session, leader.id, "iron", leader.planet_key)).amount += 100000

    npc = await _npc(session, "npc_martian")
    npc.energy = 999
    # Strip the NPC's minerals so build/train are unaffordable -> it reaches the attack step.
    for st in (
        await session.execute(select(ResourceStock).where(ResourceStock.player_id == npc.id))
    ).scalars():
        st.amount = 0
    (await get_or_create_unit_stock(session, npc.id, "tank")).quantity = 50
    await session.commit()

    npc = await _npc(session, "npc_martian")
    action = await RuleBasedBrain().act(session, npc)
    leader_base = await _base_of(session, leader)
    assert action == f"attack base {leader_base.id}"


async def test_best_meta_unit_picks_high_winrate(session):
    # SDD 41: la NPC elige la unidad con mejor win-rate (con muestra suficiente).
    import json

    from app.models import GameEvent
    from app.services.insights import compute_meta
    from app.services.npc import _best_meta_unit

    assert await _best_meta_unit(session) is None   # sin datos → None (cae al default)

    win = json.dumps({"force": {"aircraft": 5}, "outcome": "attacker"})
    for _ in range(6):   # aircraft domina
        session.add(GameEvent(type="battle_resolved", payload=win))
    session.add(GameEvent(type="battle_resolved",
                          payload=json.dumps({"force": {"tank": 5}, "outcome": "defender"})))
    await session.commit()
    await compute_meta(session)
    await session.commit()
    assert await _best_meta_unit(session) == "aircraft"


def test_unit_ready_checks_required_building():
    from app.content.registry import get_content
    from app.services.npc import _unit_ready
    c = get_content()
    assert _unit_ready("aircraft", {"factory"}, c)        # factory activo
    assert not _unit_ready("aircraft", {"barracks"}, c)   # falta factory


def test_push_metrics_noop_without_url(monkeypatch):
    # SDD 19 §7.quater: sin pushgateway_url, el push del tick es no-op (no rompe el tick).
    from app.core.config import get_settings
    from app.worker import _push_metrics
    monkeypatch.setattr(get_settings(), "pushgateway_url", "")
    _push_metrics()  # no debe lanzar
    assert get_settings().pushgateway_url == ""


async def test_rule_brain_softens_with_a_missile_strike(session, monkeypatch):
    # SDD 49: con strike_enabled, una lanzadera activa, misiles y un enemigo del MISMO planeta,
    # el NPC lanza una salva para ablandar antes de la flota.
    from app.core.config import get_settings
    from app.models import PlayerTech, StrikeMission, UnitStock
    from app.services.economy import get_or_create_stock
    monkeypatch.setattr(get_settings(), "strike_enabled", True)

    await ensure_npcs(session)
    npc = await _npc(session)            # martian → mars
    base = await _base_of(session, npc)
    # un humano en MARTE (mismo planeta), sin protección
    human = Player(username="prey_mars", password_hash=hash_password("secret123"))
    session.add(human)
    await session.flush()
    await onboard_player(session, human, "milky_way", "mars", "martian")
    human.protected_until = None

    # NPC: lanzadera activa + tech + misiles + energía; stocks en 0 para saltar economía/ciencia
    session.add(Building(base_id=base.id, building_key="launcher", status="active"))
    session.add(PlayerTech(player_id=npc.id, tech_key="rocketry"))
    session.add(UnitStock(player_id=npc.id, unit_key="sonic_missile", quantity=6))
    from app.content.registry import get_content
    for m in get_content().minerals:
        (await get_or_create_stock(session, npc.id, m, npc.planet_key)).amount = 0
    npc.energy = 100
    await session.flush()

    action = await run_npc_turn(session, npc)
    await session.commit()
    assert action and "strike" in action, action
    q = await session.execute(select(StrikeMission).where(StrikeMission.attacker_id == npc.id))
    assert q.first() is not None


# ---- SDD 29 v2: perfiles deterministas + NPC-vs-NPC ----
async def test_npcs_are_independent_and_can_target_each_other(session):
    # Por default (npc_shared_alliance=False) las NPC NO comparten alianza → se ven como enemigas.
    from app.services.npc import _enemy_bases
    await ensure_npcs(session)
    npcs = list((await session.execute(select(Player).where(Player.is_npc.is_(True)))).scalars())
    assert all(n.alliance_id is None for n in npcs)            # independientes
    martian = await _npc(session)
    enemy_ids = {b.player_id for b in await _enemy_bases(session, martian)}
    assert any(n.id in enemy_ids for n in npcs if n.id != martian.id)   # ve a otras NPC


async def test_pick_posture_turtle_when_under_attack(session):
    from app.services.npc import pick_posture_rules
    await ensure_npcs(session)
    npc = await _npc(session)
    attacker = await _npc(session, race="npc_terran")
    await _make_mission(session, attacker, npc)               # ataque entrante a la NPC
    await session.flush()
    assert await pick_posture_rules(session, npc) == "turtle"


async def test_pick_posture_economy_when_early(session):
    from app.services.npc import pick_posture_rules
    await ensure_npcs(session)
    npc = await _npc(session)                                  # recién creada: poca infraestructura
    assert await pick_posture_rules(session, npc) == "economy"


async def test_pick_posture_rush_when_army_beats_a_target(session):
    # con economía montada + ejército fuerte + un enemigo débil → perfil de ataque (rush/raid).
    from app.models import Building, UnitStock
    from app.services.npc import pick_posture_rules
    await ensure_npcs(session)
    npc = await _npc(session)
    base = await _base_of(session, npc)
    for k in ("mine", "research_lab", "barracks", "factory"):   # ≥4 edificios activos
        session.add(Building(base_id=base.id, building_key=k, status="active"))
    session.add(UnitStock(player_id=npc.id, unit_key="tank", quantity=50))  # ejército fuerte
    await session.flush()
    assert await pick_posture_rules(session, npc) in ("rush", "raid")
