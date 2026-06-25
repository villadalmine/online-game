from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import hash_password
from app.models import Player
from app.services.economy import player_stocks
from app.services.onboarding import onboard_player
from app.services.training import (
    TrainingError,
    finalize_due_training,
    player_units,
    start_training,
)


async def _onboarded(session, planet="mars", race="martian") -> tuple[Player, object]:
    p = Player(username="bob", password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    base = await onboard_player(session, p, "milky_way", planet, race)
    await session.commit()
    return p, base


async def test_train_worker_charges_and_enqueues(session):
    p, base = await _onboarded(session)
    energy_before = p.energy
    order = await start_training(session, p, base, "worker", 2)
    await session.commit()

    assert order.unit_key == "worker"
    assert order.quantity == 2
    assert p.energy == pytest.approx(energy_before - 2 * 2, abs=0.1)  # energy_cost 2 * qty 2
    stocks = await player_stocks(session, p.id)
    # worker cost structural(10)->iron, energetic(5)->sulfur, x2
    assert stocks["iron"] == 500.0 - 20.0
    assert stocks["sulfur"] == 500.0 - 10.0


async def test_train_requires_building(session):
    p, base = await _onboarded(session)
    # tank needs an active factory (SDD 1 árbol), which doesn't exist yet.
    with pytest.raises(TrainingError):
        await start_training(session, p, base, "tank", 1)


async def test_training_delivers_units_after_timer(session):
    p, base = await _onboarded(session)
    order = await start_training(session, p, base, "worker", 3)
    await session.commit()

    order.completes_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    delivered = await finalize_due_training(session, p)
    await session.commit()

    assert delivered == 3
    units = await player_units(session, p.id)
    assert units["worker"] == 3
