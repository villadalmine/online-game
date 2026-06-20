from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.security import hash_password
from app.models import AttackMission, Base_, Building, Player
from app.services.npc import (
    LlmBrain,
    RuleBasedBrain,
    _load_memory,
    _npc_state,
    ensure_npcs,
    run_npc_turn,
)
from app.services.onboarding import onboard_player


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
    await ensure_npcs(session)
    npc = await _npc(session, "npc_martian")
    enemy = await _npc(session, "npc_terran")
    await _make_mission(session, enemy, npc)       # inbound attack, no fleet of ours
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
