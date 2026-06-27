"""SDD 1 — dependency graph: pure unit tests (no DB, no LLM, no network)."""
from app.services.depgraph import (
    PlayerSnapshot,
    analyze,
    build_graph,
    graph_documents,
    mineral_is_local,
    mineral_sources,
    prerequisites,
    retrieve,
    target_cost,
)


def test_prerequisites_follow_requires():
    assert prerequisites("tank") == ["research_lab", "factory"]   # SDD 1: lab antes que fábrica
    assert "research_lab" in prerequisites("mining_efficiency")
    assert prerequisites("mine") == []  # los básicos no tienen prerequisito (HQ siempre presente)


def test_cost_resolves_roles_per_race():
    # mine cost roles: structural=100, energetic=40 -> resolved to each race's minerals.
    martian = target_cost("martian", "mine").minerals
    terran = target_cost("terran", "mine").minerals
    assert martian == {"iron": 100, "sulfur": 40}     # martian energetic = sulfur
    assert terran == {"iron": 100, "silicon": 40}     # terran energetic = silicon


def test_premium_mineral_is_imported_not_local():
    assert mineral_is_local("earth", "iron") is True
    assert mineral_is_local("earth", "helium3") is False  # not in any abundance table
    srcs = mineral_sources("terran", "earth", "helium3")
    kinds = {s.kind for s in srcs}
    assert "local_mine" not in kinds
    assert "expedition" in kinds  # the Moon (luna) grants helium3 in the milky way


def test_local_mineral_offers_a_mine_with_estimate():
    srcs = mineral_sources("martian", "mars", "iron")
    mine = next(s for s in srcs if s.kind == "local_mine")
    assert mine.estimate_per_hour and mine.estimate_per_hour > 0


def test_analyze_reports_exact_shortfall():
    snap = PlayerSnapshot(
        race_key="martian", planet_key="mars",
        minerals={"iron": 50, "sulfur": 40}, energy=999,
        active_buildings={"headquarters"},
    )
    rep = analyze(snap, "mine")  # needs iron 100, sulfur 40, energy 10
    assert rep.buildable is False
    iron = next(b for b in rep.blockers if b.key == "iron")
    assert iron.kind == "mineral" and iron.have == 50 and iron.need == 100
    # sulfur is covered -> not a blocker
    assert all(b.key != "sulfur" for b in rep.blockers)


def test_analyze_buildable_when_everything_covered():
    snap = PlayerSnapshot(
        race_key="martian", planet_key="mars",
        minerals={"iron": 1000, "sulfur": 1000, "magnesium": 1000}, energy=999,
        active_buildings={"headquarters", "factory"},
    )
    rep = analyze(snap, "tank")  # requires factory active (covered)
    assert rep.buildable is True and rep.blockers == []


def test_analyze_flags_missing_required_building():
    snap = PlayerSnapshot(
        race_key="martian", planet_key="mars",
        minerals={"iron": 1000, "sulfur": 1000, "magnesium": 1000}, energy=999,
        active_buildings={"headquarters"},  # no factory
    )
    rep = analyze(snap, "tank")
    assert any(b.kind == "building" and b.key == "factory" for b in rep.blockers)


def test_build_graph_separates_local_and_imported():
    g = build_graph("martian", "mars")
    assert g["nodes"] and g["edges"]
    assert "iron" in g["minerals_local"]
    assert "helium3" in g["minerals_imported"]
    # the mine produces a local mineral
    assert any(e["type"] == "produces" and e["to"] == "iron" for e in g["edges"])
    # a unit requires its building
    assert any(e["type"] == "requires" and e["from"] == "tank" for e in g["edges"])


def test_retrieve_ranks_relevant_docs_with_es_synonyms():
    # Spanish query should still hit English content keys via the synonym map.
    res = retrieve("martian", "mars", "necesito una fábrica para mis tanques", k=4)
    ids = [d["id"] for d in res]
    assert "factory" in ids and "tank" in ids
    assert len(res) <= 4
    # scores are sorted descending
    scores = [d["score"] for d in res]
    assert scores == sorted(scores, reverse=True)


def test_retrieve_finds_counter_intel_by_alias():
    # "edificio contra inteligencia" debe encontrar counter_intel (nombre "Contraespionaje")
    res = retrieve("martian", "mars", "necesito construir un edificio contra inteligencia", k=4)
    assert "counter_intel" in [d["id"] for d in res]
    # "espías" encuentra la unidad spy
    res2 = retrieve("martian", "mars", "quiero entrenar espías", k=4)
    assert "spy" in [d["id"] for d in res2]


def test_graph_documents_include_mechanics_rules():
    # el corpus incluye las MECÁNICAS (no solo objetos) → la IA sabe cómo funciona el juego
    ids = {d["id"] for d in graph_documents("martian", "mars")}
    assert {"mech_combat", "mech_espionage", "mech_energy"} <= ids


def test_graph_documents_cover_every_node_type():
    docs = graph_documents("terran", "earth")
    types = {d["type"] for d in docs}
    assert {"mineral", "building", "unit", "tech"} <= types


def test_retrieve_finds_energy_assist_mechanic():
    # SDD 41: "ayudame con energía" debe encontrar la mecánica de nivelado (no delirar)
    res = retrieve("martian", "mars", "ayudame con energía", k=4)
    assert "mech_energy_assist" in [d["id"] for d in res]


def test_graph_exposes_housing_and_mining_for_ai():
    # SDD 46/47: el grafo (fuente de verdad de la IA) trae aristas de alojamiento (unidad→edificio)
    # y de minería (worker→mina, silo→mineral), y el corpus las explica como mecánicas.
    g = build_graph("terran", "earth")
    etypes = {(e["from"], e["to"], e["type"]) for e in g["edges"]}
    assert ("soldier", "barracks", "housed_in") in etypes      # el militar va al cuartel
    assert ("ship", "port", "housed_in") in etypes             # el barco al puerto (edificio nuevo)
    assert ("worker", "mine", "operates") in etypes            # los obreros operan las minas
    assert ("silo", "iron", "stores") in etypes                # el silo guarda un mineral
    ids = {d["id"] for d in graph_documents("terran", "earth")}
    assert {"mech_housing", "mech_mining"} <= ids
    # consultas en español encuentran las mecánicas nuevas
    house_q = retrieve("terran", "earth", "dónde guardo mis unidades plazas", k=4)
    mine_q = retrieve("terran", "earth", "cuántos trabajadores para las minas", k=4)
    assert "mech_housing" in [d["id"] for d in house_q]
    assert "mech_mining" in [d["id"] for d in mine_q]
