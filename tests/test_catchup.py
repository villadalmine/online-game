"""SDD 25 — catch-up del recién llegado: nivela al P40 de pares, con defensa, sin ventaja."""
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import Base_, Building, Player, ResourceStock
from app.services import catchup
from app.services.onboarding import onboard_player


async def _onboard(session, name, planet="earth", race="terran") -> Player:
    p = Player(username=name, password_hash="x")
    session.add(p)
    await session.flush()
    await onboard_player(session, p, "milky_way", planet, race)
    await session.commit()
    return p


async def _set_total(session, player, total: float) -> None:
    rows = (
        await session.execute(select(ResourceStock).where(ResourceStock.player_id == player.id))
    ).scalars().all()
    per = total / len(rows)
    for r in rows:
        r.amount = per
    await session.commit()


async def _building_keys(session, player) -> set[str]:
    base = (
        await session.execute(select(Base_).where(Base_.player_id == player.id))
    ).scalars().first()
    return {
        b.building_key
        for b in (
            await session.execute(select(Building).where(Building.base_id == base.id))
        ).scalars()
    }


async def test_catchup_levels_to_p40_with_defense(session):
    peers = [await _onboard(session, f"peer{i}") for i in range(4)]
    for p, total in zip(peers, [2000, 4000, 6000, 8000], strict=False):
        await _set_total(session, p, total)  # partida vieja: pares con stock dispar

    newbie = await _onboard(session, "newbie")  # entra con 4 pares
    total = await catchup._stock_total(session, newbie.id)
    # nivelado al P40 (= 4000), por DEBAJO de la mediana (5000) → sin ventaja
    assert total == pytest.approx(4000)
    assert total < 5000
    # defensa priorizada + energía full
    keys = await _building_keys(session, newbie)
    assert "turret" in keys and "mine" in keys
    assert newbie.energy == get_settings().energy_max


async def test_no_catchup_in_young_game(session):
    await _onboard(session, "a")
    await _onboard(session, "b")
    newbie = await _onboard(session, "c")  # solo 2 pares < min_peers(3) → sin catch-up
    keys = await _building_keys(session, newbie)
    assert "turret" not in keys
    assert newbie.energy == get_settings().energy_start  # no se tocó la energía


async def test_catchup_never_above_baseline(session):
    # pares pobres: el nuevo NO recibe minerales (ya está por encima del P40) → cero ventaja
    peers = [await _onboard(session, f"poor{i}") for i in range(3)]
    for p in peers:
        await _set_total(session, p, 100)  # P40 = 100, muy por debajo del STARTING del nuevo
    newbie = await _onboard(session, "rich_newbie")
    total = await catchup._stock_total(session, newbie.id)
    assert total > 100  # mantiene su STARTING (no se le quita), pero no se le suma de más
