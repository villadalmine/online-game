"""SDD 50 — pruebas puras de la duración/derribos de drones (simulate_drones, sin DB)."""
from app.services.drones import simulate_drones


def test_no_turrets_no_one_dies_by_fire():
    # sin antiaéreo: nadie cae por fuego; con regen ≥ drenaje se sostiene (sin tope corta a 1 tick).
    sim = simulate_drones({"recon_drone": 3}, antiair=0, energy=100, regen_per_tick=10)
    assert sim.losses == {}
    assert sim.survivors == {"recon_drone": 3}
    assert sim.eta_turrets_ticks is None       # sin torretas no hay ETA por torretas


def test_more_drones_survive_more_ticks_under_fire():
    # antiaéreo fijo; cuantos más drones (más hp total), más ticks tardan en caer todos.
    few = simulate_drones({"recon_drone": 2}, antiair=20, energy=10_000, regen_per_tick=10_000)
    many = simulate_drones({"recon_drone": 8}, antiair=20, energy=10_000, regen_per_tick=10_000)
    assert many.survive_ticks > few.survive_ticks
    # ETA por torretas ≈ Σhp / antiair: 8 drones × 20hp / 20 = 8
    assert many.eta_turrets_ticks == 8.0


def test_durable_drones_take_fewer_kills_per_tick():
    # mismo antiaéreo: el pesado (hp 90) aguanta más que el liviano (hp 20) por unidad.
    light = simulate_drones({"recon_drone": 4}, antiair=40, energy=10_000, regen_per_tick=10_000)
    heavy = simulate_drones({"recon_drone_mk3": 4}, antiair=40, energy=1e4, regen_per_tick=1e4)
    assert heavy.survive_ticks > light.survive_ticks


def test_dies_of_energy_when_drain_exceeds_regen():
    # sin torretas pero el drenaje supera la regen y la energía es poca → muere por energía.
    sim = simulate_drones({"recon_drone_mk3": 5}, antiair=0, energy=8, regen_per_tick=0)
    # drenaje = 5×4 = 20/tick, energía 8 → muere en el primer tick
    assert sim.died_of_energy is True
    assert sim.survivors == {}
    assert sim.eta_energy_ticks is not None and sim.eta_energy_ticks < 1


def test_intel_quality_is_best_alive_spy():
    sim = simulate_drones({"recon_drone": 1, "recon_drone_mk3": 1}, antiair=0,
                          energy=1000, regen_per_tick=1000)
    assert sim.intel_quality == 0.95   # el mk3 manda


def test_attack_drones_deal_damage_per_tick():
    sim = simulate_drones({"strike_drone": 2}, antiair=0, energy=10_000, regen_per_tick=10_000,
                          max_ticks=3)
    assert sim.attack_per_tick == 50          # 2 × 25
    assert sim.attack_dealt == 150            # 3 ticks × 50
