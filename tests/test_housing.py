"""SDD 46 — funciones puras de alojamiento (grafo unidad ↔ dominio ↔ edificio)."""
from app.services.housing import (
    can_train,
    housing_capacity,
    housing_matrix,
    housing_occupancy,
    unit_domain,
    unit_size,
)


def test_unit_domain_and_size_from_content():
    assert unit_domain("worker") == "personnel"
    assert unit_domain("soldier") == "infantry"
    assert unit_domain("ship") == "naval"
    assert unit_domain("tank") == "ground"
    assert unit_domain("aircraft") == "air"
    assert unit_domain("shuttle") == "space"
    assert unit_size("worker") == 1
    assert unit_size("shuttle") == 3      # pesada: ocupa más plazas


def test_capacity_sums_active_buildings():
    from app.core.config import get_settings
    base = get_settings().base_housing_per_domain   # gracia por dominio (SDD 46)
    cap = housing_capacity(["headquarters", "research_lab", "barracks", "barracks"])
    assert cap["personnel"] == base + 20 + 10   # gracia + HQ + laboratorio
    assert cap["infantry"] == base + 30 + 30    # gracia + dos cuarteles


def test_occupancy_counts_stock_and_queue_by_size():
    occ = housing_occupancy({"soldier": 5, "tank": 2}, queued={"soldier": 3})
    assert occ["infantry"] == 8           # 5 en stock + 3 en cola
    assert occ["ground"] == 2 * 2         # tank ocupa housing_size 2


def test_can_train_respects_unit_size():
    assert can_train("tank", 3, free_in_domain=6) is True    # 3·2 = 6 ≤ 6
    assert can_train("tank", 4, free_in_domain=6) is False   # 4·2 = 8 > 6


def test_housing_matrix_links_units_and_buildings():
    m = housing_matrix()
    assert "soldier" in m["infantry"]["units"]
    assert m["infantry"]["houses_by_building"].get("barracks") == 30
    assert "port" in m["naval"]["houses_by_building"]        # edificio nuevo (SDD 46)
    assert "ship" in m["naval"]["units"]
