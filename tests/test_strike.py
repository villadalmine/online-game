"""SDD 49 — pruebas puras de la intercepción de misiles (simulate_strike, sin DB)."""
from app.services.strike import simulate_strike


def test_swarm_of_sonics_saturates_interception():
    # capacidad 6 frena 3 sónicos (intercept_cost 2 c/u); los 2 que sobran impactan → daño 2×60.
    r = simulate_strike({"sonic_missile": 5}, intercept_capacity=6)
    assert sum(r.intercepted.values()) == 3
    assert r.impacted == {"sonic_missile": 2}
    assert r.damage == 120


def test_nuclear_is_nearly_unstoppable():
    # un nuclear cuesta 30 de capacidad: con capacidad 20 (2 torretas) no se frena → impacta + área.
    r = simulate_strike({"nuclear_missile": 1}, intercept_capacity=20)
    assert r.intercepted == {}
    assert r.impacted == {"nuclear_missile": 1}
    assert r.damage == 600 and r.area is True


def test_cheap_missiles_are_intercepted_first():
    # la capacidad se gasta primero en los baratos (sónico cost 2), luego el crucero (cost 6).
    r = simulate_strike({"sonic_missile": 2, "cruise_missile": 1}, intercept_capacity=4)
    assert r.intercepted == {"sonic_missile": 2}      # los 2 baratos (2+2=4)
    assert r.impacted == {"cruise_missile": 1}        # el caro pasa
    assert r.damage == 160


def test_no_interception_all_impact_with_attack_mult():
    r = simulate_strike({"sonic_missile": 2}, intercept_capacity=0, atk_mult=2.0)
    assert r.impacted == {"sonic_missile": 2}
    assert r.damage == 240   # 2×60×2.0


def test_full_interception_no_damage():
    r = simulate_strike({"sonic_missile": 3}, intercept_capacity=20)
    assert r.impacted == {} and r.damage == 0.0
