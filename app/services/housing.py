"""SDD 46 — Alojamiento/capacidad de unidades (grafo unidad ↔ dominio ↔ edificio).

Cada unidad pertenece a un DOMINIO (`domain`) y ocupa `housing_size` plazas; cada edificio
provee plazas por dominio (`houses: {dominio: plazas}`). La capacidad de un dominio = suma de
`houses[dominio]` de los edificios ACTIVOS; la ocupación = Σ unidades·housing_size (+ las en cola
de entrenamiento, que reservan plaza). Todo se deriva del contenido data-driven → la misma matriz
la leen humanos, la web y la IA (asistente + NPC). Funciones puras, testeables sin DB.

Ver docs/sdd-unit-housing-capacity.md.
"""
from app.content.registry import get_content
from app.core.config import get_settings

DEFAULT_DOMAIN = "personnel"


def unit_domain(unit_key: str) -> str:
    """Dominio de una unidad (default `personnel` si el YAML no lo declara)."""
    return get_content().units.get(unit_key, {}).get("domain", DEFAULT_DOMAIN)


def unit_size(unit_key: str) -> int:
    """Plazas que ocupa UNA unidad (default 1)."""
    return int(get_content().units.get(unit_key, {}).get("housing_size", 1) or 1)


def all_domains() -> list[str]:
    """Todos los dominios que aparecen en el contenido (unidades + edificios que alojan)."""
    content = get_content()
    domains: set[str] = set()
    for u in content.units.values():
        domains.add(u.get("domain", DEFAULT_DOMAIN))
    for b in content.buildings.values():
        for d in (b.get("houses") or {}):
            domains.add(d)
    return sorted(domains)


def housing_capacity(active_building_keys) -> dict[str, int]:
    """Plazas por dominio = Σ houses[dominio] de cada edificio ACTIVO (cuenta repetidos).

    `active_building_keys` es un iterable de building_key (una entrada por edificio activo).
    Suma el colchón de gracia `base_housing_per_domain` para todo dominio conocido."""
    content = get_content()
    base = get_settings().base_housing_per_domain
    cap: dict[str, int] = {d: base for d in all_domains()}
    for key in active_building_keys:
        for domain, slots in (content.buildings.get(key, {}).get("houses") or {}).items():
            cap[domain] = cap.get(domain, base) + int(slots)
    return cap


def housing_occupancy(
    units: dict[str, int], queued: dict[str, int] | None = None
) -> dict[str, int]:
    """Ocupación por dominio = Σ cantidad·size (stock + cola de entrenamiento)."""
    occ: dict[str, int] = {}
    for src in (units, queued or {}):
        for unit_key, qty in src.items():
            if not qty:
                continue
            d = unit_domain(unit_key)
            occ[d] = occ.get(d, 0) + qty * unit_size(unit_key)
    return occ


def housing_report(
    active_building_keys, units: dict[str, int], queued: dict[str, int] | None = None
) -> dict[str, dict[str, int]]:
    """{dominio: {capacity, occupancy, free}} — lo que ve el cliente y la IA en /players/me."""
    cap = housing_capacity(active_building_keys)
    occ = housing_occupancy(units, queued)
    domains = set(cap) | set(occ)
    out: dict[str, dict[str, int]] = {}
    for d in sorted(domains):
        c, o = cap.get(d, 0), occ.get(d, 0)
        out[d] = {"capacity": c, "occupancy": o, "free": c - o}
    return out


def can_train(unit_key: str, n: int, free_in_domain: int) -> bool:
    """¿Caben N unidades nuevas? (n·housing_size ≤ plazas libres del dominio)."""
    return n * unit_size(unit_key) <= free_in_domain


def houses_for_domain(domain: str) -> list[str]:
    """Qué edificios alojan un dominio (para el mensaje accionable 'construí X')."""
    content = get_content()
    return [k for k, b in content.buildings.items() if domain in (b.get("houses") or {})]


def housing_matrix() -> dict[str, dict]:
    """Grafo serializable {dominio: {units:[...], houses_by_building:{edificio: plazas}}} para
    inyectar en el prompt de la IA y para tests. Fuente de verdad compartida IA ↔ juego."""
    content = get_content()
    matrix: dict[str, dict] = {
        d: {"units": [], "houses_by_building": {}} for d in all_domains()
    }
    for key, u in content.units.items():
        matrix.setdefault(u.get("domain", DEFAULT_DOMAIN),
                          {"units": [], "houses_by_building": {}})["units"].append(key)
    for key, b in content.buildings.items():
        for domain, slots in (b.get("houses") or {}).items():
            matrix.setdefault(domain, {"units": [], "houses_by_building": {}})[
                "houses_by_building"][key] = int(slots)
    return matrix
