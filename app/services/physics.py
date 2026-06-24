"""Multiplicadores físicos del planeta (SDD 13 §4) — opt-in y data-driven.

Anclados a la Tierra = 1.0 (neutral): con `physics_enabled=False` (default) o si al planeta le
faltan los campos, todo devuelve 1.0 → comportamiento idéntico al actual. Acotados a
[physics_min_mult, physics_max_mult] para que planetas extremos (p.ej. la insolación de Mercurio)
no rompan el balance. Mapeos:
  - `gravity_g`  → tiempo de construcción (más gravedad ⇒ construir tarda más).
  - `insolation` → regen de energía (más sol ⇒ más energía solar).
"""
from app.content.registry import get_content
from app.core.config import Settings, get_settings


def _planet_value(planet_key: str | None, field: str) -> float | None:
    planet = get_content().planets.get(planet_key or "", {})
    value = planet.get(field)
    return float(value) if isinstance(value, int | float) else None


def _bounded(mult: float, settings: Settings) -> float:
    return max(settings.physics_min_mult, min(settings.physics_max_mult, mult))


def gravity_build_multiplier(planet_key: str | None, settings: Settings | None = None) -> float:
    """Factor sobre el tiempo de construcción según la gravedad del planeta. 1.0 en la Tierra."""
    s = settings or get_settings()
    if not s.physics_enabled:
        return 1.0
    g = _planet_value(planet_key, "gravity_g")
    if g is None:
        return 1.0
    return _bounded(1.0 + s.physics_gravity_sensitivity * (g - 1.0), s)


def insolation_energy_multiplier(planet_key: str | None, settings: Settings | None = None) -> float:
    """Factor sobre la regen de energía según la insolación del planeta. 1.0 en la Tierra."""
    s = settings or get_settings()
    if not s.physics_enabled:
        return 1.0
    ins = _planet_value(planet_key, "insolation")
    if ins is None:
        return 1.0
    return _bounded(1.0 + s.physics_insolation_sensitivity * (ins - 1.0), s)


def temperature_energy_multiplier(
    planet_key: str | None, settings: Settings | None = None
) -> float:
    """Penaliza la regen según cuán lejos del confort esté la temperatura (frío o calor ⇒ gastar
    energía en climatizar). 1.0 en el confort; nunca sube de 1.0 (solo penaliza)."""
    s = settings or get_settings()
    if not s.physics_enabled:
        return 1.0
    t = _planet_value(planet_key, "mean_temp_c")
    if t is None:
        return 1.0
    deviation = abs(t - s.physics_comfort_temp_c)
    mult = 1.0 - s.physics_temp_sensitivity * (deviation / s.physics_temp_scale_c)
    return _bounded(min(1.0, mult), s)


def effective_energy_regen(player, settings: Settings | None = None) -> float:
    """Regen efectiva: base × insolación (sol) × temperatura (refrigeración) del planeta."""
    s = settings or get_settings()
    return (
        s.energy_regen_per_hour
        * insolation_energy_multiplier(player.planet_key, s)
        * temperature_energy_multiplier(player.planet_key, s)
    )
