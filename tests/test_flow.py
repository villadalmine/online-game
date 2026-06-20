from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import hash_password
from app.models import Player
from app.services.build import BuildError, start_build
from app.services.economy import collect_mines, finalize_due_builds, player_stocks
from app.services.onboarding import onboard_player


async def _new_player(session, username="alice") -> Player:
    p = Player(username=username, password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    return p


async def test_onboard_creates_base_and_stock(session):
    p = await _new_player(session)
    base = await onboard_player(session, p, "milky_way", "mars", "martian")
    await session.commit()

    assert p.race_key == "martian"
    assert base.planet_key == "mars"
    stocks = await player_stocks(session, p.id)
    # Martian roles: structural=iron, energetic=sulfur, advanced=magnesium
    assert stocks["iron"] == 500.0
    assert stocks["sulfur"] == 500.0


async def test_build_charges_resources_and_enqueues(session):
    p = await _new_player(session)
    base = await onboard_player(session, p, "milky_way", "mars", "martian")
    await session.commit()

    energy_before = p.energy
    b = await start_build(session, p, base, "mine", target_mineral="iron")
    await session.commit()

    assert b.status == "building"
    assert b.production_mineral == "iron"
    # ~10 spent; a sliver of lazy regen may accrue between onboard and build.
    assert p.energy == pytest.approx(energy_before - 10, abs=0.1)
    stocks = await player_stocks(session, p.id)
    assert stocks["iron"] == 500.0 - 100.0  # structural cost
    assert stocks["sulfur"] == 500.0 - 40.0  # energetic cost


async def test_build_rejects_insufficient_energy(session):
    p = await _new_player(session)
    base = await onboard_player(session, p, "milky_way", "earth", "terran")
    p.energy = 0
    await session.commit()
    with pytest.raises(BuildError):
        await start_build(session, p, base, "mine", target_mineral="iron")


async def test_mine_produces_after_completion(session):
    p = await _new_player(session)
    base = await onboard_player(session, p, "milky_way", "mars", "martian")
    await session.commit()
    b = await start_build(session, p, base, "mine", target_mineral="iron")
    await session.commit()

    # Force completion in the past, then advance an hour.
    b.completes_at = datetime.now(UTC) - timedelta(hours=1)
    await session.commit()
    await finalize_due_builds(session, p)
    gained = await collect_mines(session, p)
    await session.commit()

    # mine base_output 60/h * mars iron abundance 1.5 ~= 90/h
    assert gained["iron"] == pytest.approx(90, rel=0.05)
