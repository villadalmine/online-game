from app.content.registry import get_content


def test_role_resolution_differs_per_race():
    c = get_content()
    # Same abstract role 'structural' maps to different minerals per race.
    assert c.resolve_role("terran", "structural") == "iron"
    assert c.resolve_role("venusian", "structural") == "basalt"


def test_building_cost_resolved_to_minerals():
    c = get_content()
    cost = c.building_cost_in_minerals("venusian", "mine")
    # mine costs structural(100)->basalt, energetic(40)->sulfur for venusians
    assert cost == {"basalt": 100.0, "sulfur": 40.0}


def test_planet_abundance_lookup():
    c = get_content()
    assert c.planet_abundance("mars", "iron") == 1.5
    assert c.planet_abundance("earth", "unknown") == 1.0
