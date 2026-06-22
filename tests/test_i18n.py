"""SDD 4 — i18n: registry localization helpers (pure)."""
from app.content.registry import localize, localize_catalog, normalize_lang


def test_normalize_lang():
    assert normalize_lang("en") == "en"
    assert normalize_lang("en-US,en;q=0.9") == "en"
    assert normalize_lang("es-AR") == "es"
    assert normalize_lang("fr") == "es"   # unsupported -> default
    assert normalize_lang(None) == "es"


def test_localize_swaps_en_and_strips_helper_keys():
    obj = {"key": "mine", "name": "Mina", "name_en": "Mine", "description": "Extrae"}
    en = localize(obj, "en")
    assert en["name"] == "Mine" and "name_en" not in en
    es = localize(obj, "es")
    assert es["name"] == "Mina" and "name_en" not in es


def test_localize_falls_back_to_base_when_no_translation():
    obj = {"key": "x", "name": "Solo ES"}  # no name_en
    assert localize(obj, "en")["name"] == "Solo ES"


def test_localize_catalog_handles_nested_planets():
    cat = {
        "galaxies": [
            {"key": "g", "name": "Galaxia", "name_en": "Galaxy",
             "planets": [{"key": "p", "name": "Planeta", "name_en": "Planet"}]}
        ],
        "minerals": [{"key": "iron", "name": "Hierro", "name_en": "Iron"}],
        "count": 3,  # non-list passthrough
    }
    en = localize_catalog(cat, "en")
    assert en["galaxies"][0]["name"] == "Galaxy"
    assert en["galaxies"][0]["planets"][0]["name"] == "Planet"
    assert en["minerals"][0]["name"] == "Iron"
    assert en["count"] == 3
