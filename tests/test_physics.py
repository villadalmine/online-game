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


def test_effective_energy_regen_scales_with_insolation():
    s = _on(energy_regen_per_hour=10.0)

    class _P:
        planet_key = "mars"  # insolación 0.43 → mult 0.715

    assert physics.effective_energy_regen(_P(), s) == pytest.approx(7.15)
    # off ⇒ regen base intacta
    off = Settings(physics_enabled=False, energy_regen_per_hour=10.0)
    assert physics.effective_energy_regen(_P(), off) == 10.0
