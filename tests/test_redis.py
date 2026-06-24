"""Unit tests for the Redis helpers (cache + rate limit), using fakeredis.
Also verifies graceful degradation when Redis is absent (None)."""
import fakeredis.aioredis

from app.core.redis import cached_json, player_lock, rate_limited


def _fake():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


async def test_cached_json_computes_once_then_serves_cache():
    r = _fake()
    calls = {"n": 0}

    def producer():
        calls["n"] += 1
        return {"v": 1}

    a = await cached_json(r, "k", 60, producer)
    b = await cached_json(r, "k", 60, producer)
    assert a == b == {"v": 1}
    assert calls["n"] == 1  # second call hit the cache


async def test_cached_json_without_redis_is_passthrough():
    calls = {"n": 0}

    def producer():
        calls["n"] += 1
        return {"v": 2}

    await cached_json(None, "k", 60, producer)
    await cached_json(None, "k", 60, producer)
    assert calls["n"] == 2  # no cache -> recomputed each time


async def test_rate_limited_trips_after_limit():
    r = _fake()
    assert await rate_limited(r, "k", 2, 60) is False
    assert await rate_limited(r, "k", 2, 60) is False
    assert await rate_limited(r, "k", 2, 60) is True


async def test_rate_limited_without_redis_always_allows():
    assert await rate_limited(None, "k", 1, 60) is False
    assert await rate_limited(None, "k", 1, 60) is False


async def test_player_lock_is_mutually_exclusive():
    r = _fake()
    async with player_lock(r, 1) as first:
        assert first is True
        async with player_lock(r, 1) as second:  # mismo jugador, lock tomado
            assert second is False
        async with player_lock(r, 2) as other:  # otro jugador, libre
            assert other is True
    # liberado al salir → se puede volver a tomar
    async with player_lock(r, 1) as again:
        assert again is True


async def test_player_lock_without_redis_is_noop():
    async with player_lock(None, 1) as a, player_lock(None, 1) as b:
        assert a is True and b is True  # sin Redis no bloquea (dev/tests)


async def test_player_lock_release_only_own_token():
    # tras liberar, la clave no queda → otro la toma; no borramos el lock ajeno
    r = _fake()
    async with player_lock(r, 7):
        pass
    assert await r.get("lock:player:7") is None
