"""Presencia "quién está online" (SDD 21).

Heartbeat: cada `/players/me` (el cliente lo pollea cada ~4s) marca al jugador. Online = visto
dentro de `presence_window_seconds`. Backend: ZSET de Redis (global entre réplicas) con
`member=player_id, score=last_seen_unix`; sin Redis (dev/tests) cae a un dict en memoria.
"""
import time

from app.core.config import get_settings

_mem: dict[int, float] = {}  # fallback sin Redis (1 proceso)
_KEY = "presence:online"


async def touch(redis, player_id: int) -> None:
    now = time.time()
    if redis is not None:
        try:
            await redis.zadd(_KEY, {str(player_id): now})
            return
        except Exception:
            pass
    _mem[player_id] = now


async def online_ids(redis, window: int | None = None) -> list[int]:
    window = window or get_settings().presence_window_seconds
    cutoff = time.time() - window
    if redis is not None:
        try:
            await redis.zremrangebyscore(_KEY, 0, cutoff)  # limpia los viejos
            ids = await redis.zrangebyscore(_KEY, cutoff, "+inf")
            return [int(x) for x in ids]
        except Exception:
            pass
    return [pid for pid, ts in _mem.items() if ts >= cutoff]


async def online_count(redis, window: int | None = None) -> int:
    return len(await online_ids(redis, window))
