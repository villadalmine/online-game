"""SDD 62: mover tropas entre bases propias (guarnición)."""
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import Base_, Player, UnitStock
from app.services.onboarding import onboard_player
from app.services.training import units_at_base
from app.services.troops import TroopError, process_moves, start_move


async def _two_bases(session):
    p = Player(username="mover", password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    natal = await onboard_player(session, p, "milky_way", "mars", "martian")
    colony = Base_(player_id=p.id, name="Colonia", planet_key="venus", base_type="surface")
    session.add(colony)
    await session.flush()
    await session.commit()
    return p, natal, colony


async def test_move_troops_blocks_at_source_then_arrives(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "garrison_enabled", True)
    p, natal, colony = await _two_bases(session)
    session.add(UnitStock(player_id=p.id, unit_key="tank", quantity=5, base_id=natal.id))
    await session.commit()

    move = await start_move(session, p, natal.id, colony.id, {"tank": 3})
    await session.commit()
    # salieron del origen, todavía no llegaron al destino
    assert (await units_at_base(session, p.id, natal.id)).get("tank") == 2
    assert not (await units_at_base(session, p.id, colony.id))

    # forzar la llegada y procesar
    move.arrives_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    await process_moves(session, player_id=p.id)
    await session.commit()
    assert (await units_at_base(session, p.id, colony.id)).get("tank") == 3


async def test_move_troops_requires_units_and_distinct_bases(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "garrison_enabled", True)
    p, natal, colony = await _two_bases(session)
    # sin tropas en el origen
    try:
        await start_move(session, p, natal.id, colony.id, {"tank": 1})
        raise AssertionError("debería fallar sin tropas en origen")
    except TroopError:
        pass
    # misma base
    try:
        await start_move(session, p, natal.id, natal.id, {"tank": 1})
        raise AssertionError("debería rechazar mover a la misma base")
    except TroopError:
        pass


async def test_move_troops_off_is_disabled(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "garrison_enabled", False)
    p, natal, colony = await _two_bases(session)
    try:
        await start_move(session, p, natal.id, colony.id, {"tank": 1})
        raise AssertionError("con garrison OFF no se mueven tropas")
    except TroopError:
        pass
