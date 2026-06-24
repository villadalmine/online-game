"""SDD 4 (i18n server) — re-render EN de notificaciones desde type+data."""
from app.services.notifications import localize


def test_localize_en_known_types():
    assert localize("building_done", {"building": "mine"}, "Edificio listo: mine", "en") == \
        "Building ready: mine"
    assert localize("training_done", {"quantity": 3, "unit": "tank"}, "x", "en") == "3 tank trained"
    assert localize("research_done", {"tech": "armor"}, "x", "en") == "Research completed: armor"
    assert localize("expedition_returned", {"moon": "lu"}, "x", "en") == "Expedition to lu returned"


def test_localize_es_and_unknown_keep_original():
    assert localize("building_done", {"building": "mine"}, "Edificio listo: mine", "es") == \
        "Edificio listo: mine"  # ES = original
    assert localize("npc_taunt", {}, "«frase»", "en") == "«frase»"  # sin template -> original
    assert localize("desconocido", {}, "orig", "en") == "orig"


def test_localize_missing_param_falls_back_gracefully():
    # falta 'building' -> usa '?' (no rompe)
    assert "?" in localize("building_done", {}, "orig", "en")
