from fastapi import APIRouter, Depends, Header, HTTPException, status
from redis.asyncio import Redis

from app.content.registry import get_content, localize_catalog, normalize_lang
from app.core.config import get_settings
from app.core.redis import cached_json, get_redis
from app.services import depgraph

router = APIRouter()


def _validate_race_planet(race: str, planet: str) -> None:
    c = get_content()
    if race not in c.races:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Raza desconocida: {race}")
    if planet not in c.planets:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Planeta desconocido: {planet}")


def build_catalog() -> dict:
    c = get_content()
    s = get_settings()
    return {
        "galaxies": list(c.galaxies.values()),
        "planets": list(c.planets.values()),
        "races": list(c.races.values()),
        "minerals": list(c.minerals.values()),
        "buildings": list(c.buildings.values()),
        "personnel": list(c.personnel.values()),
        "heavy_units": list(c.heavy.values()),
        "ordnance": list(c.ordnance.values()),   # SDD 49: misiles
        "drones": list(c.drones.values()),       # SDD 50: drones
        "satellites": list(c.satellites.values()),  # SDD 61: satélites
        "rooms": list(c.rooms.values()),             # SDD 64: habitaciones del búnker
        "repop_sets": list(c.repop_sets.values()),   # SDD 64 v2: sets de repoblación
        "ai_skills": list(c.ai_skills),              # SDD 78: grafo de habilidades de la IA robot
        "ai_levels": list(c.ai_levels),              # SDD 78: niveles (qué skill abre cada uno)
        "moons": list(c.moons.values()),
        "technologies": list(c.technologies.values()),
        "alliance_types": list(c.alliance_types.values()),
        # action energy costs so clients can show "cuesta ⚡X" sin hardcodear (SDD 34/35)
        "costs": {
            "attack_energy": s.attack_energy_cost, "spy_energy": s.spy_energy_cost,
            # SDD 49/50: para las calculadoras del cliente (intercepción, duración de drones).
            "turret_intercept_power": c.buildings.get("turret", {}).get("intercept_power", 30),
            "turret_antiair_power": c.buildings.get("turret", {}).get("antiair_power", 30),
            "drone_tick_seconds": s.drone_tick_seconds,
            "energy_regen_per_hour": s.energy_regen_per_hour,
            # SDD 64: para el panel del búnker (tamaño del mapa + gate de intel del sabotaje).
            "bunker_grid": s.bunker_grid,
            "bunker_raid_min_map_pct": s.bunker_raid_min_map_pct,
        },
        # Flags de features (SDD 49/50/61/62): el cliente muestra/oculta paneles según el flag.
        "features": {
            "strike": s.strike_enabled, "drones": s.drones_enabled,
            "satellites": s.satellites_enabled, "garrison": s.garrison_enabled,
            "bunkers": s.bunkers_enabled,
            "bunker_expansion": s.bunker_expansion_enabled,   # SDD 69 Fase 1
            "artificial_life": s.artificial_life_enabled,     # SDD 69 Fase 4
            "bunker_autonomy": s.bunker_autonomy_enabled,     # SDD 69 Fase 4
            "space_jump": s.space_jump_enabled,               # SDD 63: salto instantáneo de tropas
            "ai_brain": s.ai_autopilot_brain_enabled,         # SDD 81: cerebro LLM del autopiloto
        },
    }


@router.get("")
async def catalog(
    lang: str | None = None,
    accept_language: str | None = Header(default=None),
    redis: Redis | None = Depends(get_redis),
):
    """Full data-driven catalog so any client can render the game without hardcoding.

    Localized by `?lang=` (wins) or `Accept-Language`, default `es`. Cached per language."""
    chosen = normalize_lang(lang or accept_language)
    return await cached_json(
        redis, f"catalog:v1:{chosen}", get_settings().catalog_cache_ttl,
        lambda: localize_catalog(build_catalog(), chosen),
    )


@router.get("/graph")
async def catalog_graph(race: str, planet: str, redis: Redis | None = Depends(get_redis)):
    """Dependency graph (nodes/edges) for a (race, planet). Static → cacheable.

    Lets any client draw the tech tree and the NPC/assistant LLM ground its reasoning."""
    _validate_race_planet(race, planet)
    return await cached_json(
        redis, f"graph:{race}:{planet}", get_settings().catalog_cache_ttl,
        lambda: depgraph.build_graph(race, planet),
    )


@router.get("/tree")
async def catalog_tree(race: str, planet: str, redis: Redis | None = Depends(get_redis)):
    """Árbol calculado (skill tree + tablas de edificios/unidades) con costos YA resueltos para la
    raza y dependencias explícitas. Determinista → cacheable. Lo consume el modal web y la IA."""
    _validate_race_planet(race, planet)
    return await cached_json(
        redis, f"tree:{race}:{planet}", get_settings().catalog_cache_ttl,
        lambda: depgraph.build_tree(race, planet),
    )


@router.get("/graph/docs")
async def catalog_graph_docs(race: str, planet: str, redis: Redis | None = Depends(get_redis)):
    """RAG corpus: the graph serialized as short retrievable documents."""
    _validate_race_planet(race, planet)
    return await cached_json(
        redis, f"graphdocs:{race}:{planet}", get_settings().catalog_cache_ttl,
        lambda: {"documents": depgraph.graph_documents(race, planet)},
    )


@router.get("/graph/search")
async def catalog_graph_search(race: str, planet: str, q: str, k: int = 6):
    """RAG retrieve: top-k graph documents most relevant to `q` (deterministic, no LLM)."""
    _validate_race_planet(race, planet)
    k = min(max(k, 1), 20)
    return {"query": q, "results": depgraph.retrieve(race, planet, q, k)}
