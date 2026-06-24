"""SDD 21 — presencia (quién está online): test de servicio (fallback en memoria, sin Redis)."""
from app.services import presence


async def test_touch_and_online_inmemory():
    presence._mem.clear()
    await presence.touch(None, 1)
    await presence.touch(None, 2)
    assert await presence.online_count(None) == 2
    assert set(await presence.online_ids(None)) == {1, 2}


async def test_online_window_excludes_stale(monkeypatch):
    import time as _t

    presence._mem.clear()
    presence._mem[7] = _t.time() - 10_000  # visto hace rato → fuera de la ventana
    presence._mem[8] = _t.time()           # recién visto
    ids = await presence.online_ids(None, window=90)
    assert ids == [8]
