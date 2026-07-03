"""Colonización: grafo raza × planeta (SDD 37, v1 read-only).

`compat()` es puro/determinista: a partir de los atributos del planeta (gravedad, temperatura,
atmósfera, agua — ya existen, SDD 13) y las `tolerances` de la raza, calcula la **habitabilidad**,
si se **puede colonizar** y los **modifiers** (prod/energía/costo) que tendría esa colonia. Alimenta
el "grafo de opciones" (`options`) que el jugador explora. NO funda colonias ni aplica los
multiplicadores todavía (eso es el follow-up estructural)."""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.models import Base_, Player

MIN_HABITABILITY = 0.15


class ColonizeError(Exception):
    pass


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _colonize_factors(techs) -> dict:
    """De las tecnologías de colonización investigadas, cuánto relaja cada eje (SDD 37)."""
    c = get_content()
    f = {"gravity": 1.0, "temp": 1.0, "atmosphere": False}
    for key in techs or ():
        t = c.technologies.get(key, {})
        if t.get("effect") != "colonize":
            continue
        spec = t.get("colonize", {})
        axis = spec.get("axis")
        if axis == "gravity":
            f["gravity"] *= float(spec.get("factor", 1.0))
        elif axis == "temp":
            f["temp"] *= float(spec.get("factor", 1.0))
        elif axis == "atmosphere":
            f["atmosphere"] = True   # hábitat sellado: cualquier atmósfera sirve
    return f


def compat(race_key: str, planet_key: str, techs=()) -> dict:
    """Compatibilidad raza×planeta, considerando las tecnologías de colonización investigadas
    (`techs`): antigravedad/blindaje/cúpulas relajan los límites. Determinista."""
    c = get_content()
    race = c.races.get(race_key, {})
    planet = c.planets.get(planet_key, {})
    tol = race.get("tolerances", {})
    reasons: list[str] = []
    relax = _colonize_factors(techs)

    ideal_g = tol.get("ideal_gravity_g", 1.0)
    ideal_t = tol.get("ideal_temp_c", 15)
    g_tol = (tol.get("gravity_tol", 0.5) or 0.5) * relax["gravity"]
    t_tol = (tol.get("temp_tol", 60) or 60) * relax["temp"]
    atmospheres = tol.get("atmospheres", ["thin", "thick"])
    needs_water = tol.get("needs_water", False)
    hostile_penalty = tol.get("hostile_penalty", 0.6)

    g = planet.get("gravity_g", ideal_g)
    t = planet.get("mean_temp_c", ideal_t)
    atmo = planet.get("atmosphere", "thin")
    water = planet.get("has_liquid_water", False)

    g_pen = _clamp01(1 - abs(g - ideal_g) / g_tol)
    t_pen = _clamp01(1 - abs(t - ideal_t) / t_tol)
    if g_pen < 0.6:
        reasons.append("gravedad incómoda" if g < ideal_g else "gravedad alta")
    if t_pen < 0.6:
        reasons.append("frío extremo" if t < ideal_t else "calor extremo")

    lethal = False
    atmo_factor = 1.0
    if atmo not in atmospheres and not relax["atmosphere"]:
        if atmo == "none":
            lethal = True
            reasons.append("sin atmósfera (letal)")
        else:
            atmo_factor = hostile_penalty
            reasons.append("atmósfera incompatible")
    water_factor = 1.0
    if needs_water and not water:
        water_factor = 0.5
        reasons.append("sin agua líquida")

    habitability = round(g_pen * t_pen * atmo_factor * water_factor, 3)
    can = (not lethal) and habitability >= MIN_HABITABILITY

    if lethal or habitability < MIN_HABITABILITY:
        verdict = "impossible"
    elif habitability >= 0.8:
        verdict = "great"
    elif habitability >= 0.5:
        verdict = "ok"
    else:
        verdict = "poor"

    # modifiers que TENDRÍA la colonia (aún no se aplican; informativos para el grafo)
    modifiers = {
        "production": round(0.4 + 0.6 * habitability, 2),
        "energy_regen": round(0.5 + 0.5 * habitability, 2),
        "build_cost": round(1.0 + (1.0 - habitability) * 0.5, 2),
    }
    return {
        "planet": planet_key,
        "habitability": habitability,
        "can_colonize": can,
        "verdict": verdict,
        "modifiers": modifiers,
        "reasons": reasons,
    }


def options(race_key: str, galaxy_key: str | None, techs=()) -> list[dict]:
    """Grafo de opciones: para `race_key`, el veredicto de cada planeta (de su galaxia si se da),
    considerando las tecnologías de colonización investigadas (`techs`)."""
    c = get_content()
    home = c.races.get(race_key, {}).get("home_planet")
    out = []
    for key in c.planets:
        if galaxy_key and c.planet_galaxy.get(key) != galaxy_key:
            continue
        row = compat(race_key, key, techs)
        p = c.planets.get(key, {})
        row["name"] = p.get("name", key)
        row["is_home"] = key == home
        # destacar abundancias altas (qué conviene minar ahí)
        ab = p.get("abundance", {})
        row["abundance_highlights"] = sorted(
            (k for k, v in ab.items() if v >= 1.2), key=lambda k: -ab[k]
        )[:3]
        out.append(row)
    out.sort(key=lambda r: (-r["habitability"], r["planet"]))
    return out


async def found_colony(
    session: AsyncSession, player: Player, planet_key: str, mode: str = "surface",
    vehicle: str = "shuttle",
) -> Base_:
    """Funda una colonia en `planet_key` (SDD 37). `mode`:
    - "surface": base terrestre, requiere que el mundo sea colonizable (compat, con tus techs).
    - "orbital": estación con robots (SDD 37 v2), requiere `orbital_robotics`; sirve en CUALQUIER
      mundo (los robots no viven ahí) pero rinde menos y cuesta más.
    `vehicle` = nave que consume (shuttle por default; `colony_ship` en la evacuación SDD 69 F3).
    Consume 1 nave + energía (escala con nº de colonias). Instantáneo en v1 (sin viaje)."""
    from datetime import UTC, datetime

    from app.core.config import get_settings
    from app.services.energy import energy_shortfall_msg, spend_energy
    from app.services.physics import effective_energy_max, effective_energy_regen
    from app.services.research import researched_techs
    from app.services.training import get_or_create_unit_stock, player_units

    c = get_content()
    s = get_settings()
    now = datetime.now(UTC)
    techs = await researched_techs(session, player.id)

    if player.race_key is None:
        raise ColonizeError("Primero completá el onboarding.")

    if mode == "lunar":
        moon = c.moons.get(planet_key)
        if moon is None:
            raise ColonizeError(f"Luna desconocida: {planet_key}")
        if player.galaxy_key and c.planet_galaxy.get(moon.get("planet")) != player.galaxy_key:
            raise ColonizeError("Esa luna está en otra galaxia.")
        if "orbital_robotics" not in techs:
            raise ColonizeError("Necesitás investigar Robótica orbital para una base lunar.")
        # los robots minan la luna sin habitabilidad
    else:
        if planet_key not in c.planets:
            raise ColonizeError(f"Planeta desconocido: {planet_key}")
        if player.galaxy_key and c.planet_galaxy.get(planet_key) != player.galaxy_key:
            raise ColonizeError("Ese planeta está en otra galaxia.")
        if planet_key == player.planet_key:
            raise ColonizeError("Ya tenés tu base ahí.")
        if mode == "orbital":
            if "orbital_robotics" not in techs:
                raise ColonizeError("Necesitás investigar Robótica orbital para una base orbital.")
        else:
            verdict = compat(player.race_key, planet_key, techs)
            if not verdict["can_colonize"]:
                why = ", ".join(verdict["reasons"]) or "ambiente incompatible"
                raise ColonizeError(
                    f"No podés colonizar {planet_key} en superficie: {why}. "
                    "Probá una base orbital (robótica orbital)."
                )

    # ¿ya tenés una base en ese planeta?
    existing = (await session.execute(
        select(Base_).where(Base_.player_id == player.id, Base_.planet_key == planet_key)
    )).scalar_one_or_none()
    if existing is not None:
        raise ColonizeError("Ya tenés una colonia en ese planeta.")

    n_bases = (await session.execute(
        select(func.count()).select_from(Base_).where(Base_.player_id == player.id)
    )).scalar_one()
    colonies = n_bases - 1  # sin contar el mundo natal
    if colonies >= s.max_colonies:
        raise ColonizeError(f"Llegaste al máximo de colonias ({s.max_colonies}).")

    if (await player_units(session, player.id)).get(vehicle, 0) < 1:
        veh_name = c.units.get(vehicle, {}).get("name", vehicle)
        raise ColonizeError(f"Necesitás un {veh_name} para colonizar.")

    energy_cost = s.colonize_energy_cost * (1 + colonies)   # expansión decreciente
    if mode in ("orbital", "lunar"):
        energy_cost *= s.orbital_cost_mult
    regen = effective_energy_regen(player, s)
    if not spend_energy(player, energy_cost, now, regen, effective_energy_max(player, s)):
        raise ColonizeError(
            energy_shortfall_msg(energy_cost, player.energy, regen).replace(
                "Energía insuficiente", "Energía insuficiente para colonizar"
            )
        )

    stock = await get_or_create_unit_stock(session, player.id, vehicle)
    stock.quantity -= 1   # la nave se consume en el viaje de colonización

    if mode == "lunar":
        name = f"Base lunar {c.moons[planet_key].get('name', planet_key)}"
    else:
        pname = c.planets[planet_key].get("name", planet_key)
        name = f"Estación orbital {pname}" if mode == "orbital" else f"Colonia {pname}"
    base = Base_(player_id=player.id, planet_key=planet_key, base_type=mode, name=name)
    session.add(base)
    await session.flush()
    from app.services.journal import record
    await record(session, "colonize", player.id, planet=planet_key, base_id=base.id, mode=mode)
    return base
