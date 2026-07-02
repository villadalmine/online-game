"""SDD 47 — funciones puras de minería: staffing (trabajadores) y almacenamiento (silos)."""
from app.content.registry import get_content
from app.services.economy import storage_caps_by_planet
from app.services.production import apply_overflow, staffing_ratio


def test_staffing_ratio_clamps_and_scales():
    assert staffing_ratio(0, 0) == 1.0      # sin minas: no penaliza
    assert staffing_ratio(5, 5) == 1.0      # justo lleno de personal
    assert staffing_ratio(10, 5) == 1.0     # techo: sobre-contratar no rinde más
    assert staffing_ratio(0, 5) == 0.0      # sin obreros: no produce
    assert staffing_ratio(5, 10) == 0.5     # 2 minas, mismos obreros → cada una rinde menos


def test_mining_floor_is_low_so_workers_matter():
    # SDD 54: sin obreros la mina casi no rinde (los trabajadores SÍ importan), pero no zerea del
    # todo a un novato. Bajamos de 0.34 a un piso simbólico (≤0.15).
    from app.core.config import get_settings
    floor = get_settings().mining_staffing_floor
    assert 0.0 < floor <= 0.15


def test_apply_overflow_caps_and_wastes():
    assert apply_overflow(100, None) == (100, 0.0)   # sin tope: almacena todo
    assert apply_overflow(100, 30) == (30, 70)       # rebalsa: 30 entra, 70 se pierde
    assert apply_overflow(100, 0) == (0.0, 100)      # almacén lleno
    assert apply_overflow(100, -5) == (0.0, 100)     # ya por encima del tope: nunca negativo


class _B:
    def __init__(self, key, base_id=1, status="active", mineral=None):
        self.building_key = key
        self.base_id = base_id
        self.status = status
        self.production_mineral = mineral


def test_storage_caps_aggregate_per_planet_and_mineral():
    c = get_content()
    base_info = {1: ("earth", "surface")}
    buildings = [
        _B("headquarters"),                                 # +5000 a TODOS los minerales
        _B("mine", mineral="iron"),                         # +2000 al hierro
        _B("silo", mineral="iron"),                         # +10000 al hierro
        _B("silo", mineral="silicon", status="building"),   # en obra: NO cuenta
    ]
    caps = storage_caps_by_planet(c, buildings, base_info, 1000, c.minerals.keys())["earth"]
    assert caps["iron"] == 1000 + 5000 + 2000 + 10000   # base + HQ + mina + silo
    assert caps["silicon"] == 1000 + 5000               # base + HQ (silo en obra ignorado)


async def test_damaged_mine_produces_less(session, monkeypatch):
    """SDD 66: una mina averiada (condición baja) rinde a fracción cuando el flag está ON."""
    from datetime import UTC, datetime, timedelta

    from app.core.config import get_settings
    from app.core.security import hash_password
    from app.models import Building, Player
    from app.services.economy import collect_mines, player_stocks
    from app.services.onboarding import onboard_player
    monkeypatch.setattr(get_settings(), "building_condition_enabled", True)
    monkeypatch.setattr(get_settings(), "mining_staffing_enabled", False)  # aislar la condición
    p = Player(username="mineop", password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    base = await onboard_player(session, p, "milky_way", "mars", "martian")
    struct = get_content().resolve_role(p.race_key, "structural")
    mine = Building(base_id=base.id, building_key="mine", status="active",
                    production_mineral=struct)
    session.add(mine)
    await session.flush()
    past = datetime.now(UTC) - timedelta(hours=5)
    # sana (100)
    mine.condition = 100.0
    mine.last_collected_at = past
    await session.commit()
    before = (await player_stocks(session, p.id)).get(mine.production_mineral, 0)
    await collect_mines(session, p)
    await session.commit()
    full = (await player_stocks(session, p.id)).get(mine.production_mineral, 0) - before
    # averiada (40) por el mismo tiempo → rinde menos
    mine.condition = 40.0
    mine.last_collected_at = past
    await session.commit()
    before2 = (await player_stocks(session, p.id)).get(mine.production_mineral, 0)
    await collect_mines(session, p)
    await session.commit()
    hurt = (await player_stocks(session, p.id)).get(mine.production_mineral, 0) - before2
    assert full > 0 and hurt < full * 0.6, (full, hurt)
