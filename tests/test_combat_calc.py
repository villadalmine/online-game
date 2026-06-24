"""SDD 34 — calculadora de combate: helpers puros + plan basado en intel."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import Base_, Player, UnitStock
from app.services.combat import resolve_combat
from app.services.combat_calc import (
    PlanError,
    defense_needed,
    loss_ratios,
    min_attack_power,
    plan_attack,
    units_for_power,
)
from app.services.espionage import process_spy_missions, start_spy
from app.services.onboarding import onboard_player


def test_loss_ratios_matches_sdd_matrix():
    # k = attack/defense = 2 → atacante pierde ~33%, defensor ~67% (tabla §4)
    a, d = loss_ratios(200, 100)
    assert round(a, 2) == 0.33 and round(d, 2) == 0.67
    # empate → 50/50
    assert loss_ratios(100, 100) == (0.5, 0.5)
    # sin nada → sin pérdidas
    assert loss_ratios(0, 0) == (0.0, 0.0)


def test_min_attack_power_and_units():
    # para 2× una defensa de 100 con multiplicador 1.0 → 200 de poder de ataque
    assert min_attack_power(100, 1.0, margin=2.0) == 200
    # con +30% de ataque, necesitás menos poder bruto
    assert round(min_attack_power(100, 1.3, margin=2.0), 1) == 153.8
    # tank tiene attack 30 → ceil(200/30) = 7
    assert units_for_power(200, "tank") == 7
    # worker no ataca → None
    assert units_for_power(200, "worker") is None


def test_defense_needed():
    # aguantar un ataque de 300 con def_mult 1.0 y 80 de torretas → 220 de defensa en unidades
    assert defense_needed(300, 1.0, flat_defense=80) == 220
    # si las torretas ya cubren, 0
    assert defense_needed(100, 1.0, flat_defense=200) == 0.0


def test_simulate_reproduces_resolve_combat():
    # la calculadora y el combate real son la MISMA función pura
    r = resolve_combat({"tank": 10}, {"ship": 5}, 1.0, 1.0, 80)
    assert r.outcome == "attacker"  # 300 > 5·30+80 = 230
    assert r.attack_score == 300 and r.defense_score == 230


async def _player(session, name) -> Player:
    p = Player(username=name, password_hash="x")
    session.add(p)
    await session.flush()
    await onboard_player(session, p, "milky_way", "mars", "martian")
    await session.commit()
    return p


async def _base_id(session, player) -> int:
    return (
        await session.execute(select(Base_).where(Base_.player_id == player.id))
    ).scalars().first().id


async def test_plan_requires_intel(session):
    obs = await _player(session, "planner")
    tgt = await _player(session, "prey")
    base = await _base_id(session, tgt)
    try:
        await plan_attack(session, obs, base)
        raise AssertionError("debió pedir intel")
    except PlanError as e:
        assert "espia" in str(e).lower() or "espiá" in str(e).lower()


async def test_plan_after_spying_suggests_winning_force(session):
    obs = await _player(session, "planner2")
    tgt = await _player(session, "prey2")
    session.add(UnitStock(player_id=obs.id, unit_key="spy", quantity=8))
    session.add(UnitStock(player_id=tgt.id, unit_key="ship", quantity=4))  # defensa 4·30=120
    await session.commit()
    base = await _base_id(session, tgt)

    m = await start_spy(session, obs, base, {"spy": 8})  # sin counter → depth alta
    m.arrives_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    await process_spy_missions(session, datetime.now(UTC), observer_id=obs.id)

    plan = await plan_attack(session, obs, base, margin=2.0)
    assert plan["estimated_defense"] > 0
    assert plan["options"], "debe sugerir unidades"
    # la fuerza sugerida (margen 2×) gana al simularla con la defensa estimada
    top = plan["options"][0]
    r = resolve_combat({top["unit"]: top["qty"]}, {}, plan["atk_mult"], 1.0,
                       plan["estimated_defense"])
    assert r.outcome == "attacker"
