import pytest

from app.core.security import hash_password
from app.models import Player, UnitStock
from app.services.alliances import (
    AllianceError,
    create_alliance,
    join_alliance,
    mutual_defense_flat,
    shared_bonus_mult,
    shared_unit_tech_mult,
    transfer,
)
from app.services.economy import player_stocks
from app.services.onboarding import onboard_player


async def _ally_pair(session, type_="full"):
    a = Player(username="a", password_hash=hash_password("secret123"))
    b = Player(username="b", password_hash=hash_password("secret123"))
    session.add_all([a, b])
    await session.flush()
    await onboard_player(session, a, "milky_way", "earth", "terran")
    await onboard_player(session, b, "milky_way", "mars", "martian")
    await session.commit()
    al = await create_alliance(session, a, "Aliados", "ALY", type_)
    await join_alliance(session, b, al.id)
    await session.commit()
    return a, b


async def test_shared_bonus_only_for_full(session):
    a, _ = await _ally_pair(session, "full")
    assert await shared_bonus_mult(session, a.id, "production") == pytest.approx(1.10)
    a2 = Player(username="c", password_hash=hash_password("secret123"))
    session.add(a2)
    await session.flush()
    await onboard_player(session, a2, "milky_way", "venus", "venusian")
    al = await create_alliance(session, a2, "Pacto", "PAX", "nonaggression")  # noqa: F841
    await session.commit()
    assert await shared_bonus_mult(session, a2.id, "production") == 1.0


async def test_shared_unit_tech_combines_member_races(session):
    a, _ = await _ally_pair(session, "full")  # terran + martian
    # martian unit_perk attack 1.10 shared to everyone; terran has no attack perk
    assert await shared_unit_tech_mult(session, a.id, "attack") == pytest.approx(1.10)
    assert await shared_unit_tech_mult(session, a.id, "production") == pytest.approx(1.10)  # terran


async def test_mutual_defense_sums_ally_units(session):
    a, b = await _ally_pair(session, "defensive")
    session.add(UnitStock(player_id=b.id, unit_key="soldier", quantity=10))  # ally has an army
    await session.commit()
    flat = await mutual_defense_flat(session, a)
    assert flat > 0  # allies lend defense
    # a non-aggression pact gives no mutual defense
    c, d = await _make_pair(session, "nonaggression", "e", "f")
    session.add(UnitStock(player_id=d.id, unit_key="soldier", quantity=10))
    await session.commit()
    assert await mutual_defense_flat(session, c) == 0.0


async def _make_pair(session, type_, u1, u2):
    a = Player(username=u1, password_hash=hash_password("secret123"))
    b = Player(username=u2, password_hash=hash_password("secret123"))
    session.add_all([a, b])
    await session.flush()
    await onboard_player(session, a, "milky_way", "earth", "terran")
    await onboard_player(session, b, "milky_way", "mars", "martian")
    await session.commit()
    al = await create_alliance(session, a, f"Alianza-{u1}{u2}", "T", type_)
    await join_alliance(session, b, al.id)
    await session.commit()
    return a, b


async def test_transfer_moves_minerals_between_allies(session):
    a, b = await _ally_pair(session, "full")  # both start with iron (onboarding)
    before = (await player_stocks(session, b.id)).get("iron", 0)
    await transfer(session, a, b.id, "iron", 100)
    await session.commit()
    assert (await player_stocks(session, b.id)).get("iron", 0) == before + 100
    assert (await player_stocks(session, a.id)).get("iron", 0) == 400  # 500 - 100


async def test_transfer_blocked_without_trade_benefit(session):
    a, b = await _ally_pair(session, "nonaggression")
    with pytest.raises(AllianceError):
        await transfer(session, a, b.id, "iron", 100)
