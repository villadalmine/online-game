from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import hash_password
from app.models import ActiveBoon, Player, UnitStock
from app.services.boons import boon_multiplier
from app.services.economy import player_stocks
from app.services.expedition import (
    ExpeditionError,
    finalize_due_expeditions,
    start_expedition,
)
from app.services.onboarding import onboard_player


async def _onboarded(session, planet="earth", race="terran") -> Player:
    p = Player(username="ann", password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    await onboard_player(session, p, "milky_way", planet, race)
    await session.commit()
    return p


async def test_expedition_requires_shuttle(session):
    p = await _onboarded(session)
    with pytest.raises(ExpeditionError):
        await start_expedition(session, p, "luna")


async def test_expedition_charges_energy_and_enqueues(session):
    p = await _onboarded(session)
    session.add(UnitStock(player_id=p.id, unit_key="shuttle", quantity=1))
    await session.commit()
    energy_before = p.energy
    order = await start_expedition(session, p, "luna")
    await session.commit()
    assert order.moon_key == "luna"
    assert p.energy == pytest.approx(energy_before - 30, abs=0.1)  # luna energy_cost


async def test_expedition_unknown_moon(session):
    p = await _onboarded(session)
    session.add(UnitStock(player_id=p.id, unit_key="shuttle", quantity=1))
    await session.commit()
    with pytest.raises(ExpeditionError):
        await start_expedition(session, p, "death_star")


async def test_expedition_delivers_grants_and_boon(session):
    p = await _onboarded(session)
    session.add(UnitStock(player_id=p.id, unit_key="shuttle", quantity=1))
    await session.commit()
    order = await start_expedition(session, p, "luna")
    await session.commit()

    order.completes_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    finished = await finalize_due_expeditions(session, p)
    await session.commit()

    assert finished == 1
    stocks = await player_stocks(session, p.id)
    assert stocks["helium3"] == 100  # luna grants
    assert stocks["rare_earth"] == 50
    # luna grants a production boon
    mult = await boon_multiplier(session, p.id, "production")
    assert mult == pytest.approx(1.25)


async def test_expired_boon_not_applied(session):
    p = await _onboarded(session)
    session.add(
        ActiveBoon(
            player_id=p.id,
            source_moon="luna",
            effect="production",
            magnitude=1.5,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    await session.commit()
    assert await boon_multiplier(session, p.id, "production") == 1.0
