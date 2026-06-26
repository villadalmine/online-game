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


async def test_physical_restriction_checks_colony_planet_not_home(session):
    # Bug: las restricciones físicas (agua/atmósfera) se evaluaban en el planeta de ORIGEN, no en
    # el de la BASE donde se entrena. Hogar=Tierra (con agua), colonia=Marte (sin agua): entrenar
    # un barco (requiere agua) en Marte DEBE fallar mencionando Marte, aunque la Tierra tenga agua.
    from sqlalchemy import select

    from app.content.registry import get_content
    from app.models import Base_, Building, PlayerTech, UnitStock
    from app.services.colonization import found_colony
    from app.services.economy import get_or_create_stock

    p = Player(username="navy", password_hash="x")
    session.add(p)
    await session.flush()
    await onboard_player(session, p, "milky_way", "earth", "terran")
    p.energy = 99999.0
    session.add(PlayerTech(player_id=p.id, tech_key="antigravity"))
    session.add(PlayerTech(player_id=p.id, tech_key="thermal_shielding"))
    session.add(UnitStock(player_id=p.id, unit_key="shuttle", quantity=1))
    await session.commit()

    mars = await found_colony(session, p, "mars")
    # fábrica activa en Marte + minerales en Marte para que el ÚNICO bloqueo sea el agua
    session.add(Building(base_id=mars.id, building_key="factory", status="active"))
    for m in get_content().minerals:
        (await get_or_create_stock(session, p.id, m, "mars")).amount = 100000.0
    await session.commit()

    with pytest.raises(TrainingError) as ei:
        await start_training(session, p, mars, "ship", 1)
    assert "mars" in str(ei.value).lower()

    # control: en casa (Tierra, con agua) el mismo barco se entrena bien
    home = (await session.execute(
        select(Base_).where(Base_.player_id == p.id, Base_.planet_key == "earth")
    )).scalars().first()
    session.add(Building(base_id=home.id, building_key="factory", status="active"))
    await session.commit()
    order = await start_training(session, p, home, "ship", 1)
    assert order.unit_key == "ship"


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
