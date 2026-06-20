from app.services.combat import resolve_combat


def test_attacker_overwhelms_defender():
    # 5 tanks (attack 30 = 150) vs 1 soldier (defense 5)
    r = resolve_combat({"tank": 5}, {"soldier": 1})
    assert r.outcome == "attacker"
    assert r.attack_score == 150
    assert r.defender_losses.get("soldier", 0) == 1


def test_empty_forces_draw():
    r = resolve_combat({}, {})
    assert r.outcome == "draw"
    assert r.attacker_losses == {} and r.defender_losses == {}


def test_defender_holds_on_tie_or_weaker_attacker():
    # 1 soldier attacking (attack 8) vs strong defense
    r = resolve_combat({"soldier": 1}, {"tank": 5})
    assert r.outcome == "defender"


def test_race_multipliers_apply():
    base = resolve_combat({"soldier": 10}, {"soldier": 10})
    boosted = resolve_combat({"soldier": 10}, {"soldier": 10}, attacker_atk_mult=1.25)
    assert boosted.attack_score > base.attack_score


def test_flat_base_defense_lets_an_undefended_base_hold():
    # 3 soldiers (attack 24) would beat an empty base...
    assert resolve_combat({"soldier": 3}, {}).outcome == "attacker"
    # ...but a turret's static defense (100) holds them off.
    assert resolve_combat({"soldier": 3}, {}, defender_flat_defense=100).outcome == "defender"
