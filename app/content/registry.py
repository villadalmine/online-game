"""Loads the data-driven game content (content/*.yaml) into an in-memory registry.

This is the single source of game rules. To rebalance or extend the game,
edit the YAML files — no code changes needed.
"""
from functools import lru_cache
from pathlib import Path

import yaml

from app.core.config import CONTENT_DIR


def _load(name: str) -> dict:
    path = Path(CONTENT_DIR) / name
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class GameContent:
    def __init__(self) -> None:
        self.minerals: dict[str, dict] = {m["key"]: m for m in _load("minerals.yaml")["minerals"]}

        planets_raw = _load("planets.yaml")["galaxies"]
        self.galaxies: dict[str, dict] = {g["key"]: g for g in planets_raw}
        self.planets: dict[str, dict] = {}
        self.planet_galaxy: dict[str, str] = {}
        for g in planets_raw:
            for p in g["planets"]:
                self.planets[p["key"]] = p
                self.planet_galaxy[p["key"]] = g["key"]

        self.races: dict[str, dict] = {r["key"]: r for r in _load("races.yaml")["races"]}
        buildings_raw = _load("buildings.yaml")["buildings"]
        self.buildings: dict[str, dict] = {b["key"]: b for b in buildings_raw}

        units = _load("units.yaml")
        self.personnel: dict[str, dict] = {u["key"]: u for u in units.get("personnel", [])}
        self.heavy: dict[str, dict] = {u["key"]: u for u in units.get("heavy", [])}
        # Combined lookup for any trainable unit (personnel or heavy).
        self.units: dict[str, dict] = {**self.personnel, **self.heavy}

        self.moons: dict[str, dict] = {m["key"]: m for m in _load("gods.yaml")["moons"]}
        self.technologies: dict[str, dict] = {
            t["key"]: t for t in _load("technologies.yaml")["technologies"]
        }
        self.alliance_types: dict[str, dict] = {
            t["key"]: t for t in _load("alliances.yaml")["types"]
        }
        self.events: dict[str, dict] = {e["key"]: e for e in _load("events.yaml")["events"]}
        self.announcements: list[dict] = _load("announcements.yaml")["announcements"]  # SDD 27

    def resolve_role(self, race_key: str, role: str) -> str | None:
        """Map an abstract resource role (structural/energetic/advanced) to a mineral key."""
        race = self.races.get(race_key)
        if not race:
            return None
        return race["resource_roles"].get(role)

    def resolve_cost(self, race_key: str, role_cost: dict) -> dict[str, float]:
        """Translate a role-based cost ({structural: N, ...}) into concrete minerals."""
        result: dict[str, float] = {}
        for role, amount in role_cost.items():
            mineral = self.resolve_role(race_key, role)
            if mineral is None or amount == 0:
                continue
            result[mineral] = result.get(mineral, 0.0) + float(amount)
        return result

    def building_cost_in_minerals(self, race_key: str, building_key: str) -> dict[str, float]:
        """Translate a building's role-based cost into concrete mineral amounts for a race."""
        return self.resolve_cost(race_key, self.buildings[building_key].get("cost", {}))

    def unit_cost_in_minerals(self, race_key: str, unit_key: str) -> dict[str, float]:
        """Translate a unit's role-based cost into concrete mineral amounts for a race."""
        return self.resolve_cost(race_key, self.units[unit_key].get("cost", {}))

    def tech_cost_in_minerals(self, race_key: str, tech_key: str) -> dict[str, float]:
        """Translate a technology's role-based cost into concrete mineral amounts."""
        return self.resolve_cost(race_key, self.technologies[tech_key].get("cost", {}))

    def planet_abundance(self, planet_key: str, mineral_key: str) -> float:
        planet = self.planets.get(planet_key, {})
        return float(planet.get("abundance", {}).get(mineral_key, 1.0))

    def moon_galaxy(self, moon_key: str) -> str | None:
        """Which galaxy a moon belongs to (via its parent planet)."""
        moon = self.moons.get(moon_key)
        if not moon:
            return None
        return self.planet_galaxy.get(moon["planet"])


@lru_cache
def get_content() -> GameContent:
    return GameContent()


# --------------------------------------------------------------------------- #
# i18n: localize data-driven content (SDD 4). Base fields are ES (default); a
# `<field>_en` sibling holds the English variant. Adding a language = editing YAML.
# --------------------------------------------------------------------------- #
SUPPORTED_LANGS = ("es", "en")
LOCALIZED_FIELDS = ("name", "description", "real", "system", "rationale",
                    "title", "summary", "standard_baseline", "differences")  # +SDD 13, +SDD 27


def normalize_lang(lang: str | None) -> str:
    """Map any input (incl. Accept-Language like 'en-US,en;q=0.9') to a supported lang."""
    if not lang:
        return "es"
    head = lang.split(",")[0].strip().lower()[:2]
    return head if head in SUPPORTED_LANGS else "es"


def localize(obj: dict, lang: str) -> dict:
    """Shallow copy of `obj` with localized fields swapped in; drops the `*_en` helper keys."""
    out = {k: v for k, v in obj.items() if not k.endswith("_en")}
    if lang == "en":
        for field in LOCALIZED_FIELDS:
            en = obj.get(f"{field}_en")
            if en is not None:
                out[field] = en
    return out


def localize_catalog(catalog: dict, lang: str) -> dict:
    """Localize every item of every collection in a /catalog payload (planets included)."""
    if lang == "es":
        # still strip helper keys so the payload is clean/consistent across langs
        pass
    out: dict = {}
    for coll, items in catalog.items():
        if not isinstance(items, list):
            out[coll] = items
            continue
        loc = []
        for item in items:
            li = localize(item, lang) if isinstance(item, dict) else item
            if isinstance(li, dict) and isinstance(li.get("planets"), list):
                li["planets"] = [localize(p, lang) for p in li["planets"]]
            loc.append(li)
        out[coll] = loc
    return out
