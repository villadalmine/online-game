"""SDD 1 — Dependency graph of resources and technologies.

Builds, purely from the data-driven content (`content/*.yaml`), the graph that ties
minerals -> mines -> buildings -> units -> technologies -> effects together, and exposes
DETERMINISTIC queries over it:

- `prerequisites(target)`   : buildings that must be active before a target (topological).
- `mineral_sources(mineral)`: how to obtain a mineral (local mine / expedition / loot / trade).
- `analyze(snapshot, target)`: given a player's state, exactly what is missing and by how much.

This is the *skill*/grounding the personal AI assistant (SDD 2) reasons over. The reasoning
itself is deterministic and works with no LLM and no DB (analyze takes a plain snapshot), so the
assistant always has a correct fallback. See docs/sdd-dependency-graph.md.
"""
from dataclasses import dataclass, field

from app.content.registry import GameContent, get_content
from app.schemas import Blocker, BlockerReport, Cost, Source

# The mineral that powers nothing else: energy is a pseudo-resource node in the graph.
ENERGY_NODE = "energy"


# --------------------------------------------------------------------------- #
# Target introspection (building | unit | tech)
# --------------------------------------------------------------------------- #
def target_kind(content: GameContent, target_key: str) -> str:
    if target_key in content.buildings:
        return "building"
    if target_key in content.units:
        return "unit"
    if target_key in content.technologies:
        return "tech"
    raise KeyError(target_key)


def target_cost(race_key: str, target_key: str) -> Cost:
    """Concrete mineral + energy cost of building/training/researching a target, for a race."""
    content = get_content()
    kind = target_kind(content, target_key)
    if kind == "building":
        minerals = content.building_cost_in_minerals(race_key, target_key)
        energy = content.buildings[target_key].get("energy_cost", 0)
    elif kind == "unit":
        minerals = content.unit_cost_in_minerals(race_key, target_key)
        energy = content.units[target_key].get("energy_cost", 0)
    else:
        minerals = content.tech_cost_in_minerals(race_key, target_key)
        energy = content.technologies[target_key].get("energy_cost", 0)
    return Cost(minerals=minerals, energy=float(energy))


def required_building(target_key: str) -> str | None:
    """The building that must be ACTIVE to train/research a target (None for buildings)."""
    content = get_content()
    kind = target_kind(content, target_key)
    if kind == "unit":
        return content.units[target_key].get("requires")
    if kind == "tech":
        return content.technologies[target_key].get("requires")
    return content.buildings[target_key].get("requires")  # buildings have none today


def prerequisites(target_key: str) -> list[str]:
    """Buildings that must be active before `target`, in topological (build-first) order.

    Transitive with a cycle guard so a future building->building requirement can't loop."""
    order: list[str] = []
    seen: set[str] = set()

    def visit(key: str) -> None:
        req = required_building(key)
        if not req or req in seen:
            return
        seen.add(req)
        visit(req)  # the prerequisite's own prerequisites first
        order.append(req)

    visit(target_key)
    return order


# --------------------------------------------------------------------------- #
# Minerals: local production vs. imports
# --------------------------------------------------------------------------- #
def mineral_is_local(planet_key: str, mineral_key: str) -> bool:
    """True iff the planet can mine this mineral (present in its abundance table, > 0).

    Premium minerals (helium3/rare_earth/water_ice) are absent from every planet's table,
    so they're never local — they come from expeditions/loot/trade."""
    content = get_content()
    abundance = content.planets.get(planet_key, {}).get("abundance", {})
    return float(abundance.get(mineral_key, 0.0)) > 0.0


def mineral_sources(race_key: str, planet_key: str, mineral_key: str) -> list[Source]:
    """Prioritised ways to obtain a mineral, given where the player lives."""
    content = get_content()
    sources: list[Source] = []

    if mineral_is_local(planet_key, mineral_key):
        abundance = float(
            content.planets[planet_key].get("abundance", {}).get(mineral_key, 0.0)
        )
        per_hour = content.buildings["mine"].get("base_output_per_hour", 0) * abundance
        sources.append(
            Source(
                kind="local_mine",
                detail=f"Construí una mina de {mineral_key} en {planet_key}.",
                estimate_per_hour=round(per_hour, 1),
            )
        )

    galaxy = content.planet_galaxy.get(planet_key)
    for moon_key, moon in content.moons.items():
        if content.moon_galaxy(moon_key) != galaxy:
            continue
        if mineral_key in (moon.get("grants") or {}):
            amount = moon["grants"][mineral_key]
            name = moon.get("name", moon_key)
            sources.append(
                Source(
                    kind="expedition",
                    detail=f"Expedición a {name} (+{amount:g} {mineral_key}).",
                )
            )

    # Always-available fallbacks (no specific target computed here).
    sources.append(Source(kind="loot", detail="Saqueá una base enemiga atacándola."))
    sources.append(
        Source(kind="alliance_trade", detail="Pedí el mineral a un aliado por comercio.")
    )
    return sources


# --------------------------------------------------------------------------- #
# State-aware analysis (pure: takes a snapshot, never touches the DB)
# --------------------------------------------------------------------------- #
@dataclass
class PlayerSnapshot:
    race_key: str
    planet_key: str
    minerals: dict[str, float] = field(default_factory=dict)
    energy: float = 0.0
    active_buildings: set[str] = field(default_factory=set)
    queued_buildings: set[str] = field(default_factory=set)
    mines: set[str] = field(default_factory=set)  # minerals already being mined


def analyze(snap: PlayerSnapshot, target_key: str) -> BlockerReport:
    """What blocks `snap` from building/training/researching `target_key`, and by how much.

    The per-mineral shortfall (`need - have`) is exactly what SDD 2's emergency "hack" grants."""
    cost = target_cost(snap.race_key, target_key)
    blockers: list[Blocker] = []

    # 1) Required building must be active (else flag it; queued = just wait).
    req = required_building(target_key)
    if req and req not in snap.active_buildings:
        building_have = 1.0 if req in snap.queued_buildings else 0.0
        blockers.append(
            Blocker(kind="building", key=req, have=building_have, need=1.0)
        )

    # 2) Minerals.
    for mineral, need in cost.minerals.items():
        have = float(snap.minerals.get(mineral, 0.0))
        if have < need:
            local = mineral_is_local(snap.planet_key, mineral) or mineral in snap.mines
            blockers.append(
                Blocker(
                    kind="mineral" if local else "not_producible",
                    key=mineral,
                    have=round(have, 1),
                    need=float(need),
                    sources=mineral_sources(snap.race_key, snap.planet_key, mineral),
                )
            )

    # 3) Energy.
    if snap.energy < cost.energy:
        blockers.append(
            Blocker(
                kind="energy",
                key=ENERGY_NODE,
                have=round(snap.energy, 1),
                need=cost.energy,
            )
        )

    return BlockerReport(
        target=target_key,
        buildable=not blockers,
        blockers=blockers,
        prerequisites=prerequisites(target_key),
    )


# --------------------------------------------------------------------------- #
# Static graph (for GET /catalog/graph; per race+planet, cacheable)
# --------------------------------------------------------------------------- #
def build_graph(race_key: str, planet_key: str) -> dict:
    """Nodes + edges of the full dependency graph for a (race, planet), built from content."""
    content = get_content()
    nodes: list[dict] = []
    edges: list[dict] = []

    minerals_local: list[str] = []
    minerals_imported: list[str] = []
    for key, m in content.minerals.items():
        local = mineral_is_local(planet_key, key)
        (minerals_local if local else minerals_imported).append(key)
        nodes.append({"id": key, "type": "mineral", "name": m.get("name", key), "local": local})
    nodes.append({"id": ENERGY_NODE, "type": "energy", "name": "Energía"})

    for effect in ("production", "attack", "defense"):
        nodes.append({"id": f"effect:{effect}", "type": "effect", "name": effect})

    def add_cost_edges(src: str, cost: Cost) -> None:
        for mineral, amount in cost.minerals.items():
            edges.append({"from": src, "to": mineral, "type": "costs", "amount": amount})
        if cost.energy:
            edges.append({"from": src, "to": ENERGY_NODE, "type": "costs", "amount": cost.energy})

    for key, b in content.buildings.items():
        if key == "headquarters":
            continue
        nodes.append(
            {"id": key, "type": "building", "name": b.get("name", key), "category": b["category"]}
        )
        add_cost_edges(key, target_cost(race_key, key))
    # The mine produces any mineral the planet supports.
    for mineral in minerals_local:
        edges.append({"from": "mine", "to": mineral, "type": "produces"})

    for key, u in content.units.items():
        nodes.append({"id": key, "type": "unit", "name": u.get("name", key)})
        add_cost_edges(key, target_cost(race_key, key))
        req = u.get("requires")
        if req:
            edges.append({"from": key, "to": req, "type": "requires"})
            edges.append({"from": req, "to": key, "type": "unlocks"})

    for key, t in content.technologies.items():
        nodes.append(
            {"id": key, "type": "tech", "name": t.get("name", key),
             "effect": t.get("effect"), "magnitude": t.get("magnitude")}
        )
        add_cost_edges(key, target_cost(race_key, key))
        req = t.get("requires")
        if req:
            edges.append({"from": key, "to": req, "type": "requires"})
            edges.append({"from": req, "to": key, "type": "unlocks"})
        if t.get("effect"):
            edges.append({"from": key, "to": f"effect:{t['effect']}", "type": "boosts"})

    return {
        "race": race_key,
        "planet": planet_key,
        "nodes": nodes,
        "edges": edges,
        "minerals_local": minerals_local,
        "minerals_imported": minerals_imported,
    }


# --------------------------------------------------------------------------- #
# RAG: the graph as a retrievable document corpus (for the LLM)
# --------------------------------------------------------------------------- #
# Lightweight ES/EN synonyms so a Spanish question hits English content keys.
SYNONYMS: dict[str, str] = {
    "fabrica": "factory", "taller": "factory", "tanque": "tank", "tanques": "tank",
    "cuartel": "barracks", "mina": "mine", "laboratorio": "research_lab", "lab": "research_lab",
    "torreta": "turret", "defensa": "defense", "energia": "energy",
    "planta": "power_plant", "barco": "ship", "avion": "aircraft",
    "transbordador": "shuttle", "nave": "shuttle", "soldado": "soldier", "militar": "soldier",
    "trabajador": "worker", "cientifico": "scientist", "ciencia": "science",
    "hierro": "iron", "silicio": "silicon", "aluminio": "aluminum", "titanio": "titanium",
    "azufre": "sulfur", "magnesio": "magnesium", "basalto": "basalt",
    "investigar": "tech", "tecnologia": "tech", "edificio": "building", "unidad": "unit",
}


def _cost_text(cost: Cost) -> str:
    parts = [f"{m} {a:g}" for m, a in cost.minerals.items()]
    if cost.energy:
        parts.append(f"energía {cost.energy:g}")
    return ", ".join(parts) or "sin costo"


def graph_documents(race_key: str, planet_key: str) -> list[dict]:
    """Serialize the graph into short, self-contained docs (one per node) for retrieval."""
    content = get_content()
    docs: list[dict] = []

    # which units/techs each building unlocks (inverse of `requires`)
    unlocks: dict[str, list[str]] = {}
    for key, u in content.units.items():
        if u.get("requires"):
            unlocks.setdefault(u["requires"], []).append(key)
    for key, t in content.technologies.items():
        if t.get("requires"):
            unlocks.setdefault(t["requires"], []).append(key)

    for key, m in content.minerals.items():
        srcs = mineral_sources(race_key, planet_key, key)
        local = mineral_is_local(planet_key, key)
        how = "; ".join(s.detail for s in srcs)
        avail = (
            f"Se mina localmente en {planet_key}." if local
            else f"NO se produce en {planet_key} (importar)."
        )
        docs.append({
            "id": key, "type": "mineral",
            "text": f"{m.get('name', key)} ({m.get('real','')}): {m.get('description','')} "
                    f"{avail} Cómo conseguirlo: {how}",
            "keywords": [key, *m.get("name", "").lower().split(), "mineral",
                         "local" if local else "imported"],
        })

    for key, b in content.buildings.items():
        if key == "headquarters":
            continue
        unl = unlocks.get(key, [])
        docs.append({
            "id": key, "type": "building",
            "text": f"{b.get('name', key)} (edificio, {b['category']}): {b.get('description','')} "
                    f"Cuesta: {_cost_text(target_cost(race_key, key))}. "
                    f"Tarda {b.get('build_seconds',0)}s."
                    + (f" Habilita: {', '.join(unl)}." if unl else ""),
            "keywords": [key, *b.get("name", "").lower().split(), "building", b["category"], *unl],
        })

    for key, u in content.units.items():
        req = u.get("requires")
        stats = u.get("stats", {})
        docs.append({
            "id": key, "type": "unit",
            "text": f"{u.get('name', key)} (unidad): {u.get('description','')} "
                    f"Requiere: {req} activo. Cuesta: {_cost_text(target_cost(race_key, key))}. "
                    f"Stats atk {stats.get('attack',0)} / def {stats.get('defense',0)} / "
                    f"hp {stats.get('hp',0)}.",
            "keywords": [key, *u.get("name", "").lower().split(), "unit", req or "", "train",
                         "entrenar"],
        })

    for key, t in content.technologies.items():
        docs.append({
            "id": key, "type": "tech",
            "text": f"{t.get('name', key)} (tecnología): {t.get('description','')} "
                    f"Requiere: {t.get('requires')} activo. "
                    f"Cuesta: {_cost_text(target_cost(race_key, key))}. "
                    f"Efecto: {t.get('effect')} ×{t.get('magnitude')}.",
            "keywords": [key, *t.get("name", "").lower().split(), "tech", "research",
                         "investigar", t.get("effect") or ""],
        })

    return docs


def _tokens(text: str) -> list[str]:
    cur, out = [], []
    for ch in text.lower():
        if ch.isalnum() or ch == "_":
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    # map ES tokens to canonical EN content keys, keeping the original too
    return [SYNONYMS.get(tok, tok) for tok in out]


def retrieve(race_key: str, planet_key: str, query: str, k: int = 6) -> list[dict]:
    """Top-k graph documents most relevant to `query` (deterministic lexical scoring).

    Score = keyword hits (×3) + body hits (×1), with a strong boost when the doc id appears.
    This is the dependency-free default; an embeddings backend can replace it later behind the
    same signature, falling back here on any failure."""
    q = set(_tokens(query))
    if not q:
        return []
    scored: list[tuple[float, dict]] = []
    for doc in graph_documents(race_key, planet_key):
        kw = set(t for k_ in doc["keywords"] for t in _tokens(k_))
        body = _tokens(doc["text"])
        score = 3.0 * len(q & kw) + sum(1 for t in body if t in q)
        if doc["id"] in q:
            score += 5.0
        if score > 0:
            scored.append((score, {**doc, "score": round(score, 1)}))
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    return [d for _s, d in scored[:k]]
