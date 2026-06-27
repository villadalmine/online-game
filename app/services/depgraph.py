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
from functools import lru_cache

from app.content.registry import GameContent, get_content
from app.core.config import get_settings
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
    # SDD 47: los trabajadores operan las minas (staffing); el silo almacena un mineral.
    if "worker" in content.units and "mine" in content.buildings:
        edges.append({"from": "worker", "to": "mine", "type": "operates"})
    if "silo" in content.buildings:
        for mineral in (*minerals_local, *minerals_imported):
            edges.append({"from": "silo", "to": mineral, "type": "stores"})

    from app.services.housing import houses_for_domain, unit_domain
    for key, u in content.units.items():
        nodes.append({"id": key, "type": "unit", "name": u.get("name", key)})
        add_cost_edges(key, target_cost(race_key, key))
        req = u.get("requires")
        if req:
            edges.append({"from": key, "to": req, "type": "requires"})
            edges.append({"from": req, "to": key, "type": "unlocks"})
        # SDD 46: alojamiento — la unidad se guarda en el/los edificio(s) de su dominio.
        for hb in houses_for_domain(unit_domain(key)):
            edges.append({"from": key, "to": hb, "type": "housed_in"})
            edges.append({"from": hb, "to": key, "type": "houses"})

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
# Computed "tree" view (GET /catalog/tree): skill tree + unit/building tables with
# costs ALREADY resolved per race and dependencies spelled out. Deterministic, derived
# 100% from content → the single source the web modal renders AND the AI grounds on.
# --------------------------------------------------------------------------- #
def build_tree(race_key: str, planet_key: str) -> dict:
    """Structured, race-resolved tree: buildings, technologies and units with concrete mineral
    costs + dependencies (requires building / requires_tech / prerequisites). Pure."""
    content = get_content()

    # inverse of `requires`: what each building unlocks (units + techs)
    unlocks: dict[str, list[str]] = {}
    for key, u in content.units.items():
        if u.get("requires"):
            unlocks.setdefault(u["requires"], []).append(key)
    for key, t in content.technologies.items():
        if t.get("requires"):
            unlocks.setdefault(t["requires"], []).append(key)

    buildings = []
    for key, b in content.buildings.items():
        cost = target_cost(race_key, key)
        buildings.append({
            "key": key, "name": b.get("name", key), "category": b.get("category"),
            "cost": cost.minerals, "energy": cost.energy,
            "build_seconds": b.get("build_seconds", 0),
            "requires": b.get("requires"), "requires_tech": b.get("requires_tech"),
            "houses": b.get("houses", {}), "unlocks": unlocks.get(key, []),
        })

    technologies = []
    for key, t in content.technologies.items():
        cost = target_cost(race_key, key)
        technologies.append({
            "key": key, "name": t.get("name", key), "category": t.get("category"),
            "effect": t.get("effect"), "magnitude": t.get("magnitude"),
            "cost": cost.minerals, "energy": cost.energy,
            "research_seconds": t.get("research_seconds", 0),
            "requires_building": t.get("requires"), "requires_tech": t.get("requires_tech"),
        })

    units = []
    for key, u in content.units.items():
        cost = target_cost(race_key, key)
        units.append({
            "key": key, "name": u.get("name", key),
            "domain": u.get("domain", "personnel"), "housing_size": u.get("housing_size", 1),
            "cost": cost.minerals, "energy": cost.energy,
            "train_seconds": u.get("train_seconds", 0), "stats": u.get("stats", {}),
            "requires": u.get("requires"), "requires_tech": u.get("requires_tech"),
            "prerequisites": prerequisites(key),
        })

    return {
        "race": race_key, "planet": planet_key,
        "buildings": buildings, "technologies": technologies, "units": units,
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

# Alias extra por objeto: términos del jugador (ES, sinónimos, errores comunes) que deben
# encontrar ese nodo aunque no coincidan con su nombre. Clave = id del objeto del contenido.
# Resuelve casos como "edificio contra inteligencia" → counter_intel (cuyo nombre es
# "Contraespionaje"), o "espías" → spy.
ALIASES: dict[str, list[str]] = {
    "counter_intel": ["contraespionaje", "contrainteligencia", "contra", "inteligencia",
                      "espionaje", "espias", "espía", "espías", "intel", "proteccion",
                      "antiespia", "antiespias"],
    "spy": ["espia", "espía", "espias", "espías", "espionaje", "espionage", "inteligencia",
            "intel", "infiltrar"],
    "espionage": ["espionaje", "espias", "espía", "intel"],
    "counter_espionage": ["contraespionaje", "contrainteligencia", "contraespias"],
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

    docs.extend(mechanics_documents())

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

    # alias por objeto (sinónimos/errores comunes ES) para que el retrieval encuentre el nodo
    for d in docs:
        extra = ALIASES.get(d["id"])
        if extra:
            d["keywords"] = list(d["keywords"]) + extra

    return docs


def mechanics_documents() -> list[dict]:
    """Reglas/mecánicas del juego como docs recuperables (no solo objetos): así el asistente
    entiende CÓMO funciona el juego (combate, flotas, expediciones, espionaje, energía), con
    números reales de la config/contenido. Antes el corpus era solo objetos → la IA no podía
    responder 'cómo funciona X'."""
    s = get_settings()
    c = get_content()
    turret = c.buildings.get("turret", {}).get("defense_power", 40)
    same, cross = s.travel_seconds_same_planet, s.travel_seconds_cross_planet
    return [
        {
            "id": "mech_combat", "type": "mechanic",
            "text": (
                "COMBATE: atacás una base enemiga mandando una flota de unidades "
                "{unidad: cantidad}. NO hay límite de capacidad ni transporte: mandás las "
                "unidades que quieras directamente (los transbordadores NO transportan tropas; "
                "son para expediciones). Resultado: attack_score = suma de ataque de tus unidades "
                "× tus multiplicadores; defense_score = (defensa de las unidades del defensor + "
                f"torretas×{turret} fijas) × sus multiplicadores. Gana quien tiene más score; las "
                "pérdidas de cada lado son proporcionales a la cuota del rival. Ganar saquea "
                f"~{int(s.loot_fraction*100)}% de los minerales. La flota viaja {same}s mismo "
                f"planeta / {cross}s entre planetas, resuelve al llegar y vuelve. Cuesta "
                f"⚡{int(s.attack_energy_cost)} de energía."
            ),
            "keywords": ["combate", "combat", "atacar", "ataque", "attack", "flota", "fleet",
                         "unidades", "militar", "soldado", "tank", "capacidad", "transporte",
                         "transbordador", "shuttle", "cuantos", "cuántos", "entran", "caben",
                         "llevar", "mandar", "viaje", "torreta", "defensa", "saqueo", "botin"],
        },
        {
            "id": "mech_combat_planning", "type": "mechanic",
            "text": (
                "PLANIFICAR UN ATAQUE (SDD 34): NO calcules pérdidas de memoria — usá las "
                "herramientas deterministas del server. 'POST /combat/plan "
                "{target_base_id, margin}' estima la defensa DESDE TU INTEL (espiá primero) y "
                "dice cuánto poder de ataque y qué mezcla de unidades llevar. 'POST "
                "/combat/simulate {attacker_force, defender_force}' prueba fuerzas exactas (la "
                "Calculadora de la web usa esto). Regla práctica: llevá 2-3× la defensa del "
                "objetivo para ganar con pérdidas razonables (~25-33%); apenas por encima = "
                "victoria pírrica (perdés casi la mitad). Las torretas suman defensa fija que "
                "NO se pierde: defensa barata. Da números reales de esas herramientas, nunca "
                "inventados."
            ),
            "keywords": ["planear", "plan", "cuanto necesito", "cuánto necesito", "para ganar",
                         "calcular", "calculadora", "simular", "margen", "pérdidas", "perdidas",
                         "cuantos tanques", "cuántos tanques", "winrate", "conviene atacar"],
        },
        {
            "id": "mech_expedition", "type": "mechanic",
            "text": (
                "EXPEDICIONES: mandás un transbordador (shuttle) a una luna; vuelve con recursos "
                "premium y un boon temporal (multiplicador). Requiere tener al menos 1 "
                "transbordador. El transbordador es para esto, NO para llevar tropas a un ataque."
            ),
            "keywords": ["expedicion", "expedición", "expedition", "luna", "moon", "transbordador",
                         "shuttle", "boon", "dios", "premium"],
        },
        {
            "id": "mech_espionage", "type": "mechanic",
            "text": (
                "ESPIONAJE: mandás espías a un objetivo para conseguir inteligencia "
                "(profundidad = espías / (espías + contraespionaje del rival)). Más profundidad = "
                "datos más exactos; poca = solo rangos. El rival con contraespías o el edificio "
                "counter_intel te detecta y te baja espías. La intel se guarda por objetivo y se "
                "desactualiza con el tiempo (hay que re-espiar). "
                f"Cuesta ⚡{int(s.spy_energy_cost)}."
            ),
            "keywords": ["espia", "espía", "espias", "espionaje", "spy", "intel", "inteligencia",
                         "contraespionaje", "counter", "detectar", "ofuscar"],
        },
        {
            "id": "mech_energy", "type": "mechanic",
            "text": (
                f"ENERGÍA: se regenera ~{int(s.energy_regen_per_hour)}/hora hasta un tope de "
                f"{int(s.energy_max)} (ajustado por física del planeta). Cada acción cuesta "
                "energía (construir, entrenar, atacar, investigar, expedición, espiar). Se calcula "
                "sola por timestamp; no hay que reclamarla."
            ),
            "keywords": ["energia", "energía", "energy", "regenera", "tope", "costo", "acciones"],
        },
        {
            "id": "mech_energy_assist", "type": "mechanic",
            "text": (
                "AYUDA DE ENERGÍA / NIVELADO (botón ⚡ Nivelar): el servidor te REGALA energía "
                "proporcional a qué tan lejos estás del PROMEDIO del ranking — "
                "deficit = (promedio − tu_score) / promedio; energía = deficit × tope. Los "
                "rezagados reciben hasta llenar el pool; quien está en o sobre el promedio no "
                "recibe nada (no hay ventaja ni saltos de ranking). Hasta 3 veces/día y es "
                "transitoria "
                "(regenera). Para pedirla, usá el botón ⚡ Nivelar (no la calcula el modelo, la "
                "calcula el server)."
            ),
            "keywords": ["energia", "energía", "ayuda", "ayudame", "ayúdame", "nivelar", "nivelado",
                         "regala", "regalar", "dame", "necesito", "ranking", "promedio", "rezagado",
                         "energy", "help", "level"],
        },
        {
            "id": "mech_mining", "type": "mechanic",
            "text": (
                "MINERÍA (SDD 47): una mina produce por hora = "
                f"{int(c.buildings.get('mine', {}).get('base_output_per_hour', 60))} × abundancia "
                "del mineral en el planeta × tus multiplicadores (boons/tech/alianza) × STAFFING. "
                "STAFFING = trabajadores·mining_power / Σ worker_slots de tus minas (cada mina "
                f"pide {int(c.buildings.get('mine', {}).get('worker_slots', 5))} obreros para "
                "rendir al 100%). Más minas con los mismos obreros ⇒ cada una rinde MENOS "
                "(la mano de obra se reparte); entrená obreros para subir el staffing (techo 1.0, "
                "sobre-contratar no ayuda). ALMACENAMIENTO: cada mineral tiene un tope por planeta "
                f"(base {int(s.base_storage_per_mineral)} + la HQ + lo que aporta cada mina). Si "
                "se llena, lo que sigue produciendo se DESPERDICIA: construí un SILO (guarda UN "
                f"mineral, +{int(c.buildings.get('silo', {}).get('storage_capacity', 10000))}) o "
                "gastá/vendé el stock."
            ),
            "keywords": ["mina", "minas", "mineria", "minería", "produccion", "producción",
                         "produce", "por hora", "trabajador", "trabajadores", "obrero", "obreros",
                         "worker", "staffing", "rinde", "rendimiento", "silo", "silos", "almacen",
                         "almacén", "almacenamiento", "storage", "tope", "capacidad", "lleno",
                         "rebalsa", "desperdicia", "overflow", "abundancia"],
        },
        {
            "id": "mech_housing", "type": "mechanic",
            "text": (
                "ALOJAMIENTO DE UNIDADES (SDD 46): cada unidad ocupa una PLAZA de su dominio y "
                "cada edificio provee plazas. Dominios y dónde se alojan: personnel (gente civil) "
                "→ base central + laboratorio; infantry → cuartel; ground (pesadas de tierra) → "
                "el taller; air y space → hangar; naval → puerto. Capacidad de un dominio = Σ "
                "plazas de tus edificios activos; si no hay plazas libres NO podés entrenar esa "
                "unidad → construí/ampliá el edificio que la aloja (más infantería ⇒ otro cuartel; "
                "unidades navales ⇒ un puerto). Las unidades en cola ya reservan plaza; una unidad "
                "pesada ocupa más de 1 plaza (housing_size)."
            ),
            "keywords": ["alojamiento", "plaza", "plazas", "capacidad", "dominio", "housing",
                         "cuartel", "barracks", "hangar", "puerto", "port", "alojar", "alojo",
                         "guardar", "guarda", "donde", "dónde", "entran", "caben", "limite",
                         "límite", "cuantas unidades", "cuántas unidades", "lleno", "infanteria",
                         "infantería", "naval"],
        },
        {
            "id": "mech_research", "type": "mechanic",
            "text": (
                "INVESTIGACIÓN: requiere un laboratorio activo. Cada tecnología da un "
                "multiplicador "
                "permanente (producción, ataque, defensa, espionaje o contraespionaje) que apila "
                "con boons y beneficios de alianza."
            ),
            "keywords": ["investigar", "investigacion", "research", "tecnologia", "tech",
                         "laboratorio", "multiplicador", "permanente"],
        },
    ]


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


@lru_cache(maxsize=64)
def _graph_index(race_key: str, planet_key: str) -> tuple[tuple[dict, frozenset, tuple], ...]:
    """Índice invertido-liviano del grafo (objetos + mecánicas) por (raza, planeta): para cada doc,
    pre-tokeniza keywords y body UNA vez. Cacheado → `retrieve` no re-tokeniza el corpus por query
    (el contenido es estático). graph_documents ya trae objetos + mecánicas ('cómo funciona X')."""
    docs = graph_documents(race_key, planet_key)
    index = []
    for doc in docs:
        kw = frozenset(t for k_ in doc["keywords"] for t in _tokens(k_))
        body = tuple(_tokens(doc["text"]))
        index.append((doc, kw, body))
    return tuple(index)


def retrieve(race_key: str, planet_key: str, query: str, k: int = 6) -> list[dict]:
    """Top-k graph documents most relevant to `query` (deterministic lexical scoring).

    Score = keyword hits (×3) + body hits (×1), with a strong boost when the doc id appears.
    Lee del índice cacheado (`_graph_index`). Dependency-free; un backend de embeddings puede
    reemplazarlo detrás de la misma firma, cayendo acá ante cualquier fallo."""
    q = set(_tokens(query))
    if not q:
        return []
    scored: list[tuple[float, dict]] = []
    for doc, kw, body in _graph_index(race_key, planet_key):
        score = 3.0 * len(q & kw) + sum(1 for t in body if t in q)
        if doc["id"] in q:
            score += 5.0
        if score > 0:
            scored.append((score, {**doc, "score": round(score, 1)}))
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    return [d for _s, d in scored[:k]]
