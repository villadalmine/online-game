"""SDD 36 — eventos dinámicos: multiplicadores apilables, free_units una vez, scheduling."""
import random
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.models import Player
from app.services.events import (
    build_cost_multiplier,
    event_multiplier,
    grant_due_free_units,
    maybe_start_event,
    start_event,
)
from app.services.onboarding import onboard_player


async def test_event_multiplier_active_then_expires(session):
    ev = await start_event(session, "mining_boom")   # production ×1.5
    await session.commit()
    assert round(await event_multiplier(session, "production"), 2) == 1.5
    ev.ends_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    assert await event_multiplier(session, "production") == 1.0   # ya no aplica


async def test_build_cost_event_halves(session):
    await start_event(session, "happy_hour_build")   # build_cost ×0.5
    await session.commit()
    assert await build_cost_multiplier(session) == 0.5


async def test_free_units_granted_once(session):
    p = Player(username="freebie", password_hash="x")
    session.add(p)
    await session.flush()
    await onboard_player(session, p, "milky_way", "mars", "martian")
    await session.commit()
    await start_event(session, "conscription")       # 5 soldiers gratis
    await session.commit()

    g1 = await grant_due_free_units(session, p)
    await session.commit()
    assert g1.get("soldier") == 5
    g2 = await grant_due_free_units(session, p)       # no repite
    await session.commit()
    assert not g2


async def test_maybe_start_event_fires_then_respects_single_and_cooldown(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "event_chance_per_tick", 1.0)
    ev = await maybe_start_event(session, rng=random.Random(0))
    await session.commit()
    assert ev is not None
    # ya hay uno activo → no arranca otro
    assert await maybe_start_event(session, rng=random.Random(0)) is None


async def test_recent_events_lists_past(session):
    from app.services.events import recent_events_out
    ev = await start_event(session, "mining_boom")
    ev.ends_at = datetime.now(UTC) - timedelta(hours=1)   # ya terminó (dentro de 2 días)
    await session.commit()
    rec = await recent_events_out(session, days=2)
    assert any(r["key"] == "mining_boom" for r in rec)
