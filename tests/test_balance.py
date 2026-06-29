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


# --- SDD 53: balance de costos por rol/mineral -----------------------------------------------
RACES = ["terran", "martian", "venusian"]


def test_defense_and_infantry_cost_only_structural_role():
    # Meta 1: la defensa NO depende de un solo mineral 'energetic'. turret + soldier se pagan SOLO
    # con el rol structural → con tu mineral base SIEMPRE podés defenderte (nunca indefenso).
    c = get_content()
    assert set(c.buildings["turret"]["cost"]) == {"structural"}
    assert set(c.units["soldier"]["cost"]) == {"structural"}


def test_anti_lockout_resolved_per_race():
    # Resuelto a minerales concretos: para CADA raza, turret/soldier caen 100% en su mineral
    # estructural (0 en el resto) → asimetría por raza preservada, pero siempre defendible.
    c = get_content()
    for race in RACES:
        struct = c.resolve_role(race, "structural")
        for key, table in (("turret", c.building_cost_in_minerals),
                           ("soldier", c.unit_cost_in_minerals)):
            cost = table(race, key)
            assert set(cost) == {struct}, (race, key, cost)


def test_role_diversified_per_branch():
    # Meta 2 (parte): ningún rol gatea todo. Cada rama pesa en un rol distinto.
    c = get_content()
    # ground (tank) sin energetic; air (aircraft) sin structural.
    assert "energetic" not in c.units["tank"]["cost"]
    assert "structural" not in c.units["aircraft"]["cost"]
    # ciencia/energía = energetic dominante (ahí vive el cuello del energético, no en la defensa).
    for b in ("research_lab", "power_plant"):
        cost = c.buildings[b]["cost"]
        assert cost["energetic"] == max(cost.values())


def test_per_race_mineral_asymmetry_preserved():
    # Meta 2: cada raza depende de un mineral distinto (la "gracia" estratégica). El energetic y el
    # advanced difieren entre razas; el structural también (iron vs basalt).
    c = get_content()
    for role in ("structural", "energetic", "advanced"):
        minerals = {c.resolve_role(r, role) for r in RACES}
        assert len(minerals) >= 2, (role, minerals)
