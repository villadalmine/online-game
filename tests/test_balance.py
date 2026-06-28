"""SDD 49/50 — invariantes de balance (vigilan que un cambio de YAML no rompa el diseño).

No fijan números exactos (esos se afinan), sino RELACIONES: progresión de tiers, trade-offs y la
escala de intercepción/supervivencia. Si un futuro rebalanceo viola la intención, esto falla.
Ver scripts/balance.py para el reporte legible.
"""
from app.content.registry import get_content
from app.services.drones import simulate_drones
from app.services.strike import simulate_strike

MISSILES = ["sonic_missile", "cruise_missile", "nuclear_missile"]
RECON = ["recon_drone", "recon_drone_mk2", "recon_drone_mk3"]


def _roles(u):
    return sum(u.get("cost", {}).values())


def test_missile_tiers_progress():
    c = get_content()
    ms = [c.units[k] for k in MISSILES]
    powers = [m["power"] for m in ms]
    costs = [_roles(m) for m in ms]
    ics = [m["intercept_cost"] for m in ms]
    assert powers == sorted(powers) and len(set(powers)) == 3      # poder creciente
    assert costs == sorted(costs) and len(set(costs)) == 3         # costo creciente
    assert ics == sorted(ics) and len(set(ics)) == 3              # más difícil de interceptar


def test_higher_tier_missiles_are_more_housing_efficient():
    # plazas de ordnance son escasas: invertir en misiles grandes rinde más daño por plaza.
    c = get_content()
    dph = [c.units[k]["power"] / c.units[k].get("housing_size", 1) for k in MISSILES]
    assert dph == sorted(dph) and len(set(dph)) == 3


def test_cheap_missiles_are_more_mineral_efficient():
    # el sónico (spam) es el más eficiente por mineral; el nuclear, el menos (es premium/endgame).
    c = get_content()
    dpr = [c.units[k]["power"] / _roles(c.units[k]) for k in MISSILES]
    assert dpr[0] > dpr[1] > dpr[2]


def test_one_turret_cannot_intercept_a_nuclear():
    # intención del SDD: el nuclear es casi imposible de frenar salvo MUCHA defensa.
    c = get_content()
    ip = c.buildings["turret"]["intercept_power"]
    assert c.units["nuclear_missile"]["intercept_cost"] > ip
    # 1-2 torretas no lo frenan; 3 sí.
    assert simulate_strike({"nuclear_missile": 1}, 2 * ip).impacted
    assert not simulate_strike({"nuclear_missile": 1}, 3 * ip).impacted


def test_one_turret_stops_several_sonics_but_swarm_saturates():
    c = get_content()
    ip = c.buildings["turret"]["intercept_power"]
    per_turret = ip // c.units["sonic_missile"]["intercept_cost"]
    assert per_turret >= 4                       # 1 torreta frena varios sónicos baratos
    # pero un enjambre por encima de la capacidad de 3 torretas igual impacta
    r = simulate_strike({"sonic_missile": 40}, 3 * ip)
    assert sum(r.impacted.values()) > 0 and sum(r.intercepted.values()) > 0


def test_recon_drone_tiers_progress():
    c = get_content()
    ds = [c.units[k] for k in RECON]
    hps = [d["hp"] for d in ds]
    drains = [d["energy_per_tick"] for d in ds]
    intel = [d["intel_quality"] for d in ds]
    costs = [_roles(d) for d in ds]
    for seq in (hps, drains, intel, costs):
        assert seq == sorted(seq) and len(set(seq)) == 3   # hp/drenaje/intel/costo crecientes


def test_durable_drone_survives_more_turret_ticks_but_drains_faster():
    # trade-off del pedido: más durable ⇒ aguanta más torretas, pero drena más (menos por energía).
    c = get_content()
    aa = c.buildings["turret"]["antiair_power"]
    light = simulate_drones({"recon_drone": 4}, aa, 1e9, 1e9)
    heavy = simulate_drones({"recon_drone_mk3": 4}, aa, 1e9, 1e9)
    assert heavy.survive_ticks > light.survive_ticks                       # más durable vs torretas
    assert heavy.drain_per_tick > light.drain_per_tick                     # pero drena más


def test_no_turrets_means_only_energy_kills_drones():
    sim = simulate_drones({"recon_drone": 5}, 0, 1e9, 1e9)
    assert sim.losses == {} and sim.eta_turrets_ticks is None
