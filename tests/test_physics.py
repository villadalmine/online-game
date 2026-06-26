"""SDD 13 §4 — multiplicadores físicos del planeta (gravedad→build, insolación→energía).
Opt-in y anclados a la Tierra=1.0; acotados a [min,max]. Off ⇒ neutral (comportamiento actual)."""
import pytest

from app.core.config import Settings
from app.services import physics


def _on(**kw) -> Settings:
    base = dict(
        physics_enabled=True,
        physics_gravity_sensitivity=0.5,
        physics_insolation_sensitivity=0.5,
        physics_min_mult=0.5,
        physics_max_mult=2.0,
        physics_comfort_temp_c=15.0,
        physics_temp_sensitivity=0.5,
        physics_temp_scale_c=200.0,
    )
    base.update(kw)
    return Settings(**base)


def test_disabled_is_neutral():
    off = Settings(physics_enabled=False)
    assert physics.gravity_build_multiplier("mars", off) == 1.0
    assert physics.insolation_energy_multiplier("mercury", off) == 1.0


def test_earth_is_neutral_even_when_enabled():
    s = _on()
    assert physics.gravity_build_multiplier("earth", s) == 1.0
    assert physics.insolation_energy_multiplier("earth", s) == 1.0


def test_low_gravity_builds_faster():
    # Marte g=0.38 → 1 + 0.5*(0.38-1) = 0.69 (construir tarda menos)
    assert physics.gravity_build_multiplier("mars", _on()) == pytest.approx(0.69)


def test_high_insolation_more_energy_and_clamped():
    s = _on()
    # Venus insolación 1.91 → 1 + 0.5*0.91 = 1.455
    assert physics.insolation_energy_multiplier("venus", s) == pytest.approx(1.455)
    # Mercurio 6.67 → 3.835, recortado al techo 2.0
    assert physics.insolation_energy_multiplier("mercury", s) == 2.0


def test_missing_planet_or_field_is_neutral():
    s = _on()
    assert physics.gravity_build_multiplier("planeta-inexistente", s) == 1.0
    assert physics.gravity_build_multiplier(None, s) == 1.0


def test_temperature_penalizes_energy_and_never_boosts():
    s = _on()
    assert physics.temperature_energy_multiplier("earth", s) == 1.0  # 15°C = confort
    # Marte -63°C → desvío 78 → 1 - 0.5*78/200 = 0.805
    assert physics.temperature_energy_multiplier("mars", s) == pytest.approx(0.805)
    # Venus 464°C → desvío enorme → recortado al piso 0.5 (nunca negativo, nunca >1)
    assert physics.temperature_energy_multiplier("venus", s) == 0.5


def test_temperature_disabled_or_missing_is_neutral():
    assert physics.temperature_energy_multiplier("venus", Settings(physics_enabled=False)) == 1.0
    assert physics.temperature_energy_multiplier("planeta-x", _on()) == 1.0


def test_effective_energy_regen_combines_insolation_and_temperature():
    s = _on(energy_regen_per_hour=10.0)

    class _P:
        planet_key = "mars"  # insolación 0.43 → 0.715 ; temp -63 → 0.805

    # 10 * 0.715 * 0.805 ≈ 5.756
    assert physics.effective_energy_regen(_P(), s) == pytest.approx(10 * 0.715 * 0.805)
    # off ⇒ regen base intacta
    off = Settings(physics_enabled=False, energy_regen_per_hour=10.0)
    assert physics.effective_energy_regen(_P(), off) == 10.0


# ── Plantas de energía: suben tope y regen (antes el edificio no hacía nada) ──────────────
class _FakePlayer:
    def __init__(self, plants, planet="earth", is_npc=False):
        self.active_power_plants = plants
        self.planet_key = planet
        self.is_npc = is_npc


def test_power_plants_raise_energy_cap():
    s = Settings(energy_max=240.0, energy_max_per_power_plant=120.0)
    assert physics.effective_energy_max(_FakePlayer(0), s) == 240.0
    assert physics.effective_energy_max(_FakePlayer(2), s) == 480.0


def test_power_plants_raise_regen():
    # physics off ⇒ multiplicadores de planeta = 1; regen = base + plantas×bonus
    s = Settings(physics_enabled=False, energy_regen_per_hour=10.0,
                 energy_regen_per_power_plant=5.0)
    assert physics.effective_energy_regen(_FakePlayer(0), s) == pytest.approx(10.0)
    assert physics.effective_energy_regen(_FakePlayer(3), s) == pytest.approx(25.0)


def test_no_plants_cap_is_base():
    # sin el atributo (jugador viejo) ⇒ tope base, sin romper
    class _Bare:
        planet_key = "earth"
        is_npc = False
    s = Settings(energy_max=240.0, energy_max_per_power_plant=120.0)
    assert physics.effective_energy_max(_Bare(), s) == 240.0


async def test_building_power_plant_raises_cap_end_to_end(session):
    """Construir y activar una planta sube active_power_plants y el tope efectivo (bug reportado:
    el tope quedaba clavado en 240 por más plantas que hicieras)."""
    from datetime import UTC, datetime, timedelta

    from app.core.config import get_settings
    from app.core.security import hash_password
    from app.models import Player
    from app.services.build import start_build
    from app.services.economy import finalize_due_builds
    from app.services.onboarding import onboard_player
    from app.services.physics import effective_energy_max

    p = Player(username="ppower", password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    base = await onboard_player(session, p, "milky_way", "earth", "terran")
    p.energy = 99999.0
    await session.commit()
    s = get_settings()
    before = effective_energy_max(p, s)

    order = await start_build(session, p, base, "power_plant")
    order.completes_at = datetime.now(UTC) - timedelta(seconds=1)   # forzar fin del timer
    await session.commit()
    await finalize_due_builds(session, p)
    await session.commit()

    assert p.active_power_plants == 1
    assert effective_energy_max(p, s) == before + s.energy_max_per_power_plant
