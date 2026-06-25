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
    base0 = (await get_or_create_stock(session, p.id, "iron", p.planet_key)).amount
    r = await buy(session, p, "earth", "iron", 10)
    await session.commit()
    assert r["bought"] == 10 and p.energy < e0
    assert (await get_or_create_stock(session, p.id, "iron", p.planet_key)).amount == base0 + 10


async def test_sell_credits_energy(session):
    p = await _player(session, "seller")
    p.energy = 0.0
    await _add_market(session, p)
    (await get_or_create_stock(session, p.id, "iron", p.planet_key)).amount = 100.0
    await session.commit()
    r = await sell(session, p, "earth", "iron", 10)
    await session.commit()
    assert r["sold"] == 10 and p.energy > 0


async def test_transport_moves_minerals_between_planets(session):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.models import UnitStock
    from app.services.economy import planet_stocks
    from app.services.market import process_transport_missions, start_transport

    p = await _player(session, "hauler")
    # carga en la Tierra + una nave de carga
    (await get_or_create_stock(session, p.id, "iron", "earth")).amount = 1000.0
    session.add(UnitStock(player_id=p.id, unit_key="cargo_ship", quantity=1))
    await session.commit()

    m = await start_transport(session, p, "earth", "mars", {"iron": 300})
    await session.commit()
    # salió del origen; nave consumida
    assert (await planet_stocks(session, p.id, "earth")).get("iron") == 700.0
    sh = (await session.execute(select(UnitStock.quantity).where(
        UnitStock.player_id == p.id, UnitStock.unit_key == "cargo_ship"))).scalar_one()
    assert sh == 0

    # adelantar llegada → entrega en destino + vuelve la nave
    m.arrives_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    await process_transport_missions(session, datetime.now(UTC), player_id=p.id)
    await session.commit()
    assert (await planet_stocks(session, p.id, "mars")).get("iron") == 300.0
    sh2 = (await session.execute(select(UnitStock.quantity).where(
        UnitStock.player_id == p.id, UnitStock.unit_key == "cargo_ship"))).scalar_one()
    assert sh2 == 1


async def test_transport_needs_cargo_ship_and_material(session):
    from app.services.market import MarketError, start_transport
    p = await _player(session, "hauler2")
    (await get_or_create_stock(session, p.id, "iron", "earth")).amount = 100.0
    await session.commit()
    try:
        await start_transport(session, p, "earth", "mars", {"iron": 50})
        raise AssertionError("debía faltar nave de carga")
    except MarketError as e:
        assert "carga" in str(e).lower()
