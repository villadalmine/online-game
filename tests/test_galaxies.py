"""SDD 8 — galaxy instances / shards: tests de servicio."""
from sqlalchemy import select

from app.core.security import hash_password
from app.models import Base_, GalaxyInstance, Player
from app.services import galaxies as svc
from app.services.combat import CombatError, start_attack
from app.services.onboarding import onboard_player
from app.services.training import get_or_create_unit_stock


async def _human(session, name, planet="earth", race="terran") -> Player:
    p = Player(username=name, password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    await onboard_player(session, p, "milky_way", planet, race)
    await session.commit()
    return p


async def _base_of(session, player) -> Base_:
    return (
        await session.execute(select(Base_).where(Base_.player_id == player.id))
    ).scalars().first()


async def test_onboarding_assigns_instance_and_overflows(session, monkeypatch):
    monkeypatch.setattr(svc.get_settings(), "galaxy_capacity", 2, raising=False)
    # capacity=2 → el 3er jugador cae en una instancia nueva
    p1 = await _human(session, "g1")
    p2 = await _human(session, "g2")
    p3 = await _human(session, "g3")
    assert p1.galaxy_instance_id == p2.galaxy_instance_id        # misma instancia (cupo 2)
    assert p3.galaxy_instance_id != p1.galaxy_instance_id        # overflow → otra
    instances = await svc.list_instances(session)
    assert len(instances) == 2
    first = await session.get(GalaxyInstance, p1.galaxy_instance_id)
    assert first.player_count == 2 and first.status == "full"


async def test_cannot_attack_player_in_another_galaxy(session, monkeypatch):
    monkeypatch.setattr(svc.get_settings(), "galaxy_capacity", 1, raising=False)
    atk = await _human(session, "ga")     # instancia A (cupo 1 → llena)
    victim = await _human(session, "gv")  # instancia B
    assert atk.galaxy_instance_id != victim.galaxy_instance_id
    victim.protected_until = None
    (await get_or_create_unit_stock(session, atk.id, "tank")).quantity = 5
    atk.energy = 999
    await session.commit()

    vbase = await _base_of(session, victim)
    try:
        await start_attack(session, atk, vbase.id, {"tank": 1})
        raise AssertionError("debería bloquear: otra galaxia")
    except CombatError as e:
        assert "galaxia" in str(e).lower()


async def test_same_instance_attack_allowed(session, monkeypatch):
    monkeypatch.setattr(svc.get_settings(), "galaxy_capacity", 50, raising=False)
    atk = await _human(session, "sa")
    victim = await _human(session, "sv")
    assert atk.galaxy_instance_id == victim.galaxy_instance_id
    victim.protected_until = None
    (await get_or_create_unit_stock(session, atk.id, "tank")).quantity = 5
    atk.energy = 999
    await session.commit()
    vbase = await _base_of(session, victim)
    mission = await start_attack(session, atk, vbase.id, {"tank": 1})  # no levanta
    assert mission.status == "outbound"


async def test_npcs_have_no_instance_and_are_attackable(session, monkeypatch):
    from app.services.npc import ensure_npcs

    monkeypatch.setattr(svc.get_settings(), "galaxy_capacity", 50, raising=False)
    await ensure_npcs(session)
    npc = (await session.execute(select(Player).where(Player.is_npc.is_(True)))).scalars().first()
    assert npc.galaxy_instance_id is None  # NPCs son ambientales (sin instancia)

    atk = await _human(session, "hn")
    (await get_or_create_unit_stock(session, atk.id, "tank")).quantity = 5
    atk.energy = 999
    await session.commit()
    npc_base = await _base_of(session, npc)
    mission = await start_attack(session, atk, npc_base.id, {"tank": 1})  # se puede atacar NPCs
    assert mission.status == "outbound"
