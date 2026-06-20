from fastapi import APIRouter, Depends
from redis.asyncio import Redis

from app.content.registry import get_content
from app.core.config import get_settings
from app.core.redis import cached_json, get_redis

router = APIRouter()


def build_catalog() -> dict:
    c = get_content()
    return {
        "galaxies": list(c.galaxies.values()),
        "planets": list(c.planets.values()),
        "races": list(c.races.values()),
        "minerals": list(c.minerals.values()),
        "buildings": list(c.buildings.values()),
        "personnel": list(c.personnel.values()),
        "heavy_units": list(c.heavy.values()),
        "moons": list(c.moons.values()),
        "technologies": list(c.technologies.values()),
        "alliance_types": list(c.alliance_types.values()),
    }


@router.get("")
async def catalog(redis: Redis | None = Depends(get_redis)):
    """Full data-driven catalog so any client can render the game without hardcoding.

    Static per deploy → cached in Redis when available (TTL configurable)."""
    return await cached_json(redis, "catalog:v1", get_settings().catalog_cache_ttl, build_catalog)
