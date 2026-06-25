"""SDD 42 Fase 1 — mercado: precios por planeta + comprar/vender con energía."""
from datetime import UTC, datetime

from sqlalchemy import select

from app.models import Base_, Building, Player
from app.services.economy import get_or_create_stock
from app.services.market import MarketError, buy, mineral_price, sell
from app.services.onboarding import onboard_player


async def _player(session, name, planet="earth", race="terran") -> Player:
    p = Player(username=name, password_hash="x")
    session.add(p)
    await session.flush()
    await onboard_player(session, p, "milky_way", planet, race)
    await session.commit()
    return p


async def _add_market(session, player) -> None:
    base = (await session.execute(
        select(Base_).where(Base_.player_id == player.id)
    )).scalars().first()
    session.add(Building(base_id=base.id, building_key="market", status="active",
                         completes_at=datetime.now(UTC)))
    await session.commit()


def test_price_cheaper_where_abundant():
    # Tierra: hierro abunda (1.4) → barato; azufre escaso (0.4) → caro; premium He-3 → el más caro.
    assert mineral_price("earth", "iron") < mineral_price("earth", "sulfur")
    assert mineral_price("earth", "helium3") >= mineral_price("earth", "sulfur")


async def test_buy_requires_market_then_spends_energy(session):
    p = await _player(session, "trader")
    p.energy = 99999.0
    await session.commit()
    try:
        await buy(session, p, "earth", "iron", 10)
        raise AssertionError("debía requerir mercado")
    except MarketError:
        pass
    await _add_market(session, p)
    e0 = p.energy
    base0 = (await get_or_create_stock(session, p.id, "iron")).amount
    r = await buy(session, p, "earth", "iron", 10)
    await session.commit()
    assert r["bought"] == 10 and p.energy < e0
    assert (await get_or_create_stock(session, p.id, "iron")).amount == base0 + 10


async def test_sell_credits_energy(session):
    p = await _player(session, "seller")
    p.energy = 0.0
    await _add_market(session, p)
    (await get_or_create_stock(session, p.id, "iron")).amount = 100.0
    await session.commit()
    r = await sell(session, p, "earth", "iron", 10)
    await session.commit()
    assert r["sold"] == 10 and p.energy > 0
