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
    assert prerequisites("tank") == ["factory"]
    assert "research_lab" in prerequisites("mining_efficiency")
    assert prerequisites("mine") == []  # buildings have no prerequisite today


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


def test_graph_documents_cover_every_node_type():
    docs = graph_documents("terran", "earth")
    types = {d["type"] for d in docs}
    assert {"mineral", "building", "unit", "tech"} <= types
