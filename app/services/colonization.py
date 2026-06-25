"""Colonización: grafo raza × planeta (SDD 37, v1 read-only).

`compat()` es puro/determinista: a partir de los atributos del planeta (gravedad, temperatura,
atmósfera, agua — ya existen, SDD 13) y las `tolerances` de la raza, calcula la **habitabilidad**,
si se **puede colonizar** y los **modifiers** (prod/energía/costo) que tendría esa colonia. Alimenta
el "grafo de opciones" (`options`) que el jugador explora. NO funda colonias ni aplica los
multiplicadores todavía (eso es el follow-up estructural)."""
from app.content.registry import get_content

MIN_HABITABILITY = 0.15


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def compat(race_key: str, planet_key: str) -> dict:
    """Compatibilidad raza×planeta. Determinista. Devuelve habitability/can_colonize/verdict/
    modifiers/reasons."""
    c = get_content()
    race = c.races.get(race_key, {})
    planet = c.planets.get(planet_key, {})
    tol = race.get("tolerances", {})
    reasons: list[str] = []

    ideal_g = tol.get("ideal_gravity_g", 1.0)
    ideal_t = tol.get("ideal_temp_c", 15)
    g_tol = tol.get("gravity_tol", 0.5) or 0.5
    t_tol = tol.get("temp_tol", 60) or 60
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
    if atmo not in atmospheres:
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


def options(race_key: str, galaxy_key: str | None) -> list[dict]:
    """Grafo de opciones: para `race_key`, el veredicto de cada planeta (de su galaxia si se da)."""
    c = get_content()
    home = c.races.get(race_key, {}).get("home_planet")
    out = []
    for key in c.planets:
        if galaxy_key and c.planet_galaxy.get(key) != galaxy_key:
            continue
        row = compat(race_key, key)
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
