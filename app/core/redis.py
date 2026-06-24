"""Redis access + graceful-degradation helpers.

Redis is optional: if it's disabled (default) or unreachable, every helper degrades
to a safe no-op (cache misses, rate limit always allows). This keeps the game running
identically on a laptop with just SQLite, and lets it use Redis when deployed.
"""
import contextlib
import json
import secrets
from collections.abc import AsyncIterator, Callable

from redis.asyncio import Redis

from app.core.config import get_settings

_client: Redis | None = None


async def get_redis() -> Redis | None:
    """FastAPI dependency: a shared Redis client, or None when disabled."""
    settings = get_settings()
    if not settings.redis_enabled:
        return None
    global _client
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def cached_json(redis: Redis | None, key: str, ttl: int, producer: Callable[[], object]):
    """Return cached JSON for `key`, else compute via `producer()` and cache it."""
    if redis is not None:
        try:
            hit = await redis.get(key)
            if hit is not None:
                return json.loads(hit)
        except Exception:
            pass
    data = producer()
    if redis is not None:
        try:
            await redis.set(key, json.dumps(data), ex=ttl)
        except Exception:
            pass
    return data


@contextlib.asynccontextmanager
async def player_lock(
    redis: Redis | None, player_id: int, ttl_ms: int = 10_000
) -> AsyncIterator[bool]:
    """Lock distribuido por jugador para serializar acciones mutantes (evita doble-gasto por
    requests concurrentes del mismo jugador). `yield True` = lo tenemos (o Redis no está → no-op
    seguro); `yield False` = otro request lo tiene ahora (el caller debe devolver 409). Degrada a
    no-op si Redis está deshabilitado o falla, para no bloquear el juego."""
    if redis is None:
        yield True
        return
    key = f"lock:player:{player_id}"
    token = secrets.token_hex(16)
    try:
        acquired = await redis.set(key, token, nx=True, px=ttl_ms)
    except Exception:
        yield True  # Redis caído → no bloqueamos el juego
        return
    if not acquired:
        yield False
        return
    try:
        yield True
    finally:
        # Liberar solo si seguimos siendo el dueño (token) → no borramos el lock de otro. El TTL
        # acota el peor caso si el proceso muere antes de llegar acá.
        with contextlib.suppress(Exception):
            if await redis.get(key) == token:
                await redis.delete(key)


async def rate_limited(redis: Redis | None, key: str, limit: int, window: int) -> bool:
    """True if `key` exceeded `limit` hits within `window` seconds (fixed window)."""
    if redis is None:
        return False
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window)
        return count > limit
    except Exception:
        return False
