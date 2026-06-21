"""End-to-end HTTP tests hitting every API endpoint over the real FastAPI app.

Endpoints covered:
  GET  /health
  POST /api/v1/auth/register
  POST /api/v1/auth/login
  GET  /api/v1/catalog
  POST /api/v1/players/onboard
  GET  /api/v1/players/me
  POST /api/v1/bases/{id}/build
  POST /api/v1/bases/{id}/train
  POST /api/v1/combat/attack
  GET  /api/v1/combat/reports
  GET  /api/v1/expeditions/moons
  POST /api/v1/expeditions
  GET  /api/v1/players
  POST /api/v1/admin/tick
  GET  /api/v1/notifications
  POST /api/v1/notifications/read
  GET  /api/v1/notifications/stream   (SSE)
  GET  /                              (web client)
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import (
    AttackMission,
    Base_,
    Building,
    ExpeditionOrder,
    Player,
    ResearchOrder,
    UnitStock,
)


async def _register(http, username="alice", password="secret123") -> dict:
    r = await http.post("/api/v1/auth/register", json={"username": username, "password": password})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _onboard(http, headers, planet="mars", race="martian") -> dict:
    r = await http.post(
        "/api/v1/players/onboard",
        headers=headers,
        json={"galaxy_key": "milky_way", "planet_key": planet, "race_key": race},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _grant_units(maker, username, units: dict[str, int]) -> None:
    """Arrange: drop units straight into a player's stock (bypasses training timers)."""
    async with maker() as s:
        res = await s.execute(select(Player).where(Player.username == username))
        player = res.scalar_one()
        for unit_key, qty in units.items():
            s.add(UnitStock(player_id=player.id, unit_key=unit_key, quantity=qty))
        await s.commit()


# ---- meta / auth -----------------------------------------------------------

async def test_health(client):
    r = await client.http.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] in ("sqlite", "postgres", "other")  # which DB is in use


async def test_register_login_and_duplicate(client):
    headers = await _register(client.http)
    # duplicate username
    r = await client.http.post(
        "/api/v1/auth/register", json={"username": "alice", "password": "secret123"}
    )
    assert r.status_code == 409
    # login ok + wrong password
    r = await client.http.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "secret123"}
    )
    assert r.status_code == 200 and "access_token" in r.json()
    r = await client.http.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "nope"}
    )
    assert r.status_code == 401
    assert headers  # sanity


async def test_me_requires_auth(client):
    r = await client.http.get("/api/v1/players/me")
    assert r.status_code in (401, 403)  # missing bearer


# ---- catalog ----------------------------------------------------------------

async def test_catalog(client):
    r = await client.http.get("/api/v1/catalog")
    assert r.status_code == 200
    body = r.json()
    assert {"earth", "mars", "venus"} <= {p["key"] for p in body["planets"]}
    assert {x["key"] for x in body["races"]} == {"terran", "martian", "venusian"}
    # alliance types carry name + benefits + description so the web can explain them
    atypes = {t["key"]: t for t in body["alliance_types"]}
    assert {"nonaggression", "defensive", "full"} <= set(atypes)
    assert "trade" in atypes["full"]["benefits"] and atypes["full"]["description"]
    assert any(b["key"] == "mine" for b in body["buildings"])


# ---- onboarding / state -----------------------------------------------------

async def test_onboard_and_me(client):
    h = await _register(client.http)
    state = await _onboard(client.http, h)
    assert state["race_key"] == "martian"
    assert state["stocks"]["iron"] == 500.0
    assert state["bases"][0]["buildings"][0]["building_key"] == "headquarters"

    r = await client.http.get("/api/v1/players/me", headers=h)
    assert r.status_code == 200
    assert r.json()["energy"] <= state["energy_max"]


async def test_onboard_invalid_planet(client):
    h = await _register(client.http)
    r = await client.http.post(
        "/api/v1/players/onboard",
        headers=h,
        json={"galaxy_key": "milky_way", "planet_key": "pluto", "race_key": "martian"},
    )
    assert r.status_code == 400


# ---- build ------------------------------------------------------------------

async def test_build_mine(client):
    h = await _register(client.http)
    state = await _onboard(client.http, h)
    base_id = state["bases"][0]["id"]
    r = await client.http.post(
        f"/api/v1/bases/{base_id}/build",
        headers=h,
        json={"building_key": "mine", "target_mineral": "iron"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "building"


async def test_build_on_foreign_base_404(client):
    h1 = await _register(client.http, "alice")
    s1 = await _onboard(client.http, h1)
    h2 = await _register(client.http, "bob")
    await _onboard(client.http, h2)
    foreign_base = s1["bases"][0]["id"]
    r = await client.http.post(
        f"/api/v1/bases/{foreign_base}/build",
        headers=h2,
        json={"building_key": "mine", "target_mineral": "iron"},
    )
    assert r.status_code == 404


# ---- train ------------------------------------------------------------------

async def test_train_worker(client):
    h = await _register(client.http)
    state = await _onboard(client.http, h)
    base_id = state["bases"][0]["id"]
    r = await client.http.post(
        f"/api/v1/bases/{base_id}/train", headers=h, json={"unit_key": "worker", "quantity": 2}
    )
    assert r.status_code == 201, r.text
    assert r.json()["quantity"] == 2


async def test_train_requires_building(client):
    h = await _register(client.http)
    state = await _onboard(client.http, h)
    base_id = state["bases"][0]["id"]
    r = await client.http.post(
        f"/api/v1/bases/{base_id}/train", headers=h, json={"unit_key": "soldier", "quantity": 1}
    )
    assert r.status_code == 400  # no barracks


# ---- combat (deferred: travel + resolve + return) ---------------------------

async def _fast_forward_arrivals(maker):
    async with maker() as s:
        for m in (await s.execute(select(AttackMission))).scalars():
            m.arrives_at = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()


async def _fast_forward_returns(maker):
    async with maker() as s:
        for m in (await s.execute(select(AttackMission))).scalars():
            if m.returns_at is not None:
                m.returns_at = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()


async def test_attack_dispatches_a_traveling_fleet(client):
    ha = await _register(client.http, "attacker")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hd = await _register(client.http, "defender")
    dstate = await _onboard(client.http, hd, planet="venus", race="venusian")
    target_base = dstate["bases"][0]["id"]
    await _grant_units(client.session_maker, "attacker", {"tank": 5})

    r = await client.http.post(
        "/api/v1/combat/attack",
        headers=ha,
        json={"target_base_id": target_base, "force": {"tank": 5}},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "outbound"

    # units are locked in transit; attacker shows an outgoing mission
    me = (await client.http.get("/api/v1/players/me", headers=ha)).json()
    assert me["units"].get("tank", 0) == 0
    assert len(me["missions_outgoing"]) == 1
    # defender sees an inbound attack (fog of war: no force shown)
    dme = (await client.http.get("/api/v1/players/me", headers=hd)).json()
    assert len(dme["missions_incoming"]) == 1


async def test_full_battle_resolves_on_arrival_and_fleet_returns(client):
    ha = await _register(client.http, "attacker")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hd = await _register(client.http, "defender")
    dstate = await _onboard(client.http, hd, planet="venus", race="venusian")
    target_base = dstate["bases"][0]["id"]
    await _grant_units(client.session_maker, "attacker", {"tank": 5})
    await _grant_units(client.session_maker, "defender", {"soldier": 3})

    await client.http.post(
        "/api/v1/combat/attack",
        headers=ha,
        json={"target_base_id": target_base, "force": {"tank": 5}},
    )

    # arrival -> battle resolves
    await _fast_forward_arrivals(client.session_maker)
    await client.http.post("/api/v1/admin/tick", headers=ha)
    reports = (await client.http.get("/api/v1/combat/reports", headers=ha)).json()
    assert len(reports) == 1 and reports[0]["outcome"] == "attacker"

    # return -> survivors + loot come home
    await _fast_forward_returns(client.session_maker)
    await client.http.post("/api/v1/admin/tick", headers=ha)
    me = (await client.http.get("/api/v1/players/me", headers=ha)).json()
    assert me["units"].get("tank", 0) > 0           # survivors returned
    assert me["stocks"].get("basalt", 0) > 0        # looted venusian mineral
    assert me["missions_outgoing"] == []            # mission completed


async def _add_active_building(maker, username, key, qty=1):
    async with maker() as s:
        p = (await s.execute(select(Player).where(Player.username == username))).scalar_one()
        base = (await s.execute(select(Base_).where(Base_.player_id == p.id))).scalars().first()
        for _ in range(qty):
            s.add(Building(base_id=base.id, building_key=key, status="active"))
        await s.commit()


async def test_base_turrets_help_the_defender_hold(client):
    ha = await _register(client.http, "attacker")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hd = await _register(client.http, "defender")
    dstate = await _onboard(client.http, hd, planet="venus", race="venusian")
    target_base = dstate["bases"][0]["id"]

    await _grant_units(client.session_maker, "attacker", {"soldier": 3})  # weak force
    await _add_active_building(client.session_maker, "defender", "turret", qty=2)

    await client.http.post(
        "/api/v1/combat/attack",
        headers=ha,
        json={"target_base_id": target_base, "force": {"soldier": 3}},
    )
    await _fast_forward_arrivals(client.session_maker)
    await client.http.post("/api/v1/admin/tick", headers=ha)

    reports = (await client.http.get("/api/v1/combat/reports", headers=ha)).json()
    assert reports[0]["outcome"] == "defender"  # turrets held the base


async def test_recall_brings_fleet_home_without_battle(client):
    ha = await _register(client.http, "attacker")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hd = await _register(client.http, "defender")
    dstate = await _onboard(client.http, hd, planet="venus", race="venusian")
    target_base = dstate["bases"][0]["id"]
    await _grant_units(client.session_maker, "attacker", {"tank": 5})

    r = await client.http.post(
        "/api/v1/combat/attack",
        headers=ha,
        json={"target_base_id": target_base, "force": {"tank": 5}},
    )
    mission_id = r.json()["id"]

    rc = await client.http.post(f"/api/v1/combat/missions/{mission_id}/recall", headers=ha)
    assert rc.status_code == 200 and rc.json()["status"] == "returning"

    await _fast_forward_returns(client.session_maker)
    await client.http.post("/api/v1/admin/tick", headers=ha)

    me = (await client.http.get("/api/v1/players/me", headers=ha)).json()
    assert me["units"].get("tank", 0) == 5          # full fleet back
    reports = (await client.http.get("/api/v1/combat/reports", headers=ha)).json()
    assert reports == []                            # no battle happened


# ---- notifications ----------------------------------------------------------

async def test_incoming_attack_notifies_defender(client):
    ha = await _register(client.http, "attacker")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hd = await _register(client.http, "defender")
    dstate = await _onboard(client.http, hd, planet="venus", race="venusian")
    await _grant_units(client.session_maker, "attacker", {"tank": 3})

    await client.http.post(
        "/api/v1/combat/attack",
        headers=ha,
        json={"target_base_id": dstate["bases"][0]["id"], "force": {"tank": 3}},
    )

    notes = (await client.http.get("/api/v1/notifications", headers=hd)).json()
    assert any(n["type"] == "incoming_attack" for n in notes)
    # /me surfaces an unread counter
    dme = (await client.http.get("/api/v1/players/me", headers=hd)).json()
    assert dme["unread_notifications"] >= 1


async def test_building_completion_notifies_and_mark_read(client):
    h = await _register(client.http, "builder")
    state = await _onboard(client.http, h)
    base_id = state["bases"][0]["id"]
    await client.http.post(
        f"/api/v1/bases/{base_id}/build",
        headers=h,
        json={"building_key": "mine", "target_mineral": "iron"},
    )
    # fast-forward the build, then a read of /me finalizes it (lazy) and notifies
    async with client.session_maker() as s:
        for b in (await s.execute(select(Building))).scalars():
            b.completes_at = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()
    await client.http.get("/api/v1/players/me", headers=h)

    notes = (await client.http.get("/api/v1/notifications", headers=h)).json()
    assert any(n["type"] == "building_done" for n in notes)

    # mark all read
    r = await client.http.post("/api/v1/notifications/read", headers=h, json={})
    assert r.status_code == 200 and r.json()["marked_read"] >= 1
    unread = (await client.http.get("/api/v1/notifications?unread=true", headers=h)).json()
    assert unread == []


async def test_sse_stream_emits_notifications(client):
    # Test the SSE generator directly (httpx ASGITransport buffers infinite streams).
    import json as _json

    from app.services.notifications import notify, stream_events

    h = await _register(client.http, "streamer")
    state = await _onboard(client.http, h)
    async with client.session_maker() as s:
        await notify(s, state["id"], "test_event", "hola en vivo", {"x": 1})
        await s.commit()

    chunks = [
        c async for c in stream_events(client.session_maker, state["id"], once=True)
    ]
    assert len(chunks) == 1
    assert chunks[0].startswith("data:")
    payload = _json.loads(chunks[0][5:].strip())
    assert payload["type"] == "test_event" and payload["message"] == "hola en vivo"


async def test_web_client_served(client):
    r = await client.http.get("/")
    assert r.status_code == 200
    assert "Online Galaxy War" in r.text
    # the web exposes the depth features (research / ranking / alliances panels)
    for section in ("Investigación", "Ranking", "Alianzas", "Galaxia", "Guía"):
        assert section in r.text
    # and the cost/affordability UI hooks exist (guards against silent UI regressions)
    for hook in ('id="buildcost"', 'id="traincost"', 'id="expinfo"', 'id="guide"'):
        assert hook in r.text


# ---- research / ranking / more worlds ---------------------------------------

async def test_more_planets_and_galaxies(client):
    h = await _register(client.http, "explorer")
    cat = (await client.http.get("/api/v1/catalog")).json()
    planet_keys = {p["key"] for p in cat["planets"]}
    galaxy_keys = {g["key"] for g in cat["galaxies"]}
    assert {"mercury", "vega_prime", "nyx"} <= planet_keys
    assert {"milky_way", "andromeda"} <= galaxy_keys
    assert any(t["key"] == "mining_efficiency" for t in cat["technologies"])
    # can settle a planet in the new galaxy
    r = await client.http.post(
        "/api/v1/players/onboard",
        headers=h,
        json={"galaxy_key": "andromeda", "planet_key": "vega_prime", "race_key": "terran"},
    )
    assert r.status_code == 201 and r.json()["planet_key"] == "vega_prime"


async def test_research_flow(client):
    h = await _register(client.http, "scientist")
    await _onboard(client.http, h)
    await _add_active_building(client.session_maker, "scientist", "research_lab")

    r = await client.http.post(
        "/api/v1/research", headers=h, json={"tech_key": "mining_efficiency"}
    )
    assert r.status_code == 201, r.text

    async with client.session_maker() as s:
        for o in (await s.execute(select(ResearchOrder))).scalars():
            o.completes_at = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()

    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert "mining_efficiency" in me["technologies"]


async def test_research_requires_lab_over_http(client):
    h = await _register(client.http, "nolab")
    await _onboard(client.http, h)
    r = await client.http.post("/api/v1/research", headers=h, json={"tech_key": "weapons"})
    assert r.status_code == 400


async def test_ranking(client):
    h = await _register(client.http, "champ")
    await _onboard(client.http, h)
    r = await client.http.get("/api/v1/players/ranking", headers=h)
    assert r.status_code == 200
    rows = r.json()
    assert any(e["username"] == "champ" for e in rows)
    scores = [e["score"] for e in rows]
    assert scores == sorted(scores, reverse=True)  # ranked high→low
    assert rows[0]["rank"] == 1


# ---- world events -----------------------------------------------------------

async def test_world_events_feed(client):
    # Forming an alliance and resolving a battle both surface in the public feed.
    ha = await _register(client.http, "warlord")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hd = await _register(client.http, "victim")
    dstate = await _onboard(client.http, hd, planet="venus", race="venusian")
    await client.http.post(
        "/api/v1/alliances", headers=ha, json={"name": "Conquistadores", "tag": "CNQ"}
    )

    await _grant_units(client.session_maker, "warlord", {"tank": 5})
    await client.http.post(
        "/api/v1/combat/attack",
        headers=ha,
        json={"target_base_id": dstate["bases"][0]["id"], "force": {"tank": 5}},
    )
    await _fast_forward_arrivals(client.session_maker)
    await client.http.post("/api/v1/admin/tick", headers=ha)

    feed = (await client.http.get("/api/v1/world/events", headers=hd)).json()
    msgs = " ".join(e["message"] for e in feed)
    assert "Conquistadores" in msgs           # alliance event
    assert "warlord" in msgs and "victim" in msgs  # battle event with both players
    types = {e["type"] for e in feed}
    assert {"battle", "alliance"} <= types


async def test_world_events_requires_auth(client):
    r = await client.http.get("/api/v1/world/events")
    assert r.status_code == 401


# ---- alliances --------------------------------------------------------------

async def test_alliance_create_join_and_list(client):
    h1 = await _register(client.http, "leader")
    await _onboard(client.http, h1)
    r = await client.http.post(
        "/api/v1/alliances", headers=h1, json={"name": "Los Halcones", "tag": "HALC"}
    )
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    me1 = (await client.http.get("/api/v1/players/me", headers=h1)).json()
    assert me1["alliance_id"] == aid and me1["alliance_name"] == "Los Halcones"

    h2 = await _register(client.http, "wingman")
    await _onboard(client.http, h2)
    rj = await client.http.post(f"/api/v1/alliances/{aid}/join", headers=h2)
    assert rj.status_code == 200 and rj.json()["member_count"] == 2

    listing = (await client.http.get("/api/v1/alliances", headers=h1)).json()
    assert any(a["id"] == aid and a["member_count"] == 2 for a in listing)


async def test_alliance_chat(client):
    # Two members of the same alliance can chat and both read the thread, oldest-first.
    h1 = await _register(client.http, "talker")
    await _onboard(client.http, h1)
    aid = (
        await client.http.post(
            "/api/v1/alliances", headers=h1, json={"name": "Charlatanes", "tag": "CHAT"}
        )
    ).json()["id"]
    h2 = await _register(client.http, "listener")
    await _onboard(client.http, h2)
    await client.http.post(f"/api/v1/alliances/{aid}/join", headers=h2)

    r = await client.http.post(
        "/api/v1/alliances/messages", headers=h1, json={"body": "hola aliados"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["sender_username"] == "talker"
    await client.http.post(
        "/api/v1/alliances/messages", headers=h2, json={"body": "buenas!"}
    )

    thread = (await client.http.get("/api/v1/alliances/messages", headers=h2)).json()
    assert [m["body"] for m in thread] == ["hola aliados", "buenas!"]
    assert thread[0]["sender_username"] == "talker"


async def test_alliance_chat_requires_membership(client):
    # A player without an alliance can neither read nor post.
    h = await _register(client.http, "outsider")
    await _onboard(client.http, h)
    r = await client.http.get("/api/v1/alliances/messages", headers=h)
    assert r.status_code == 400
    assert "alianza" in r.json()["detail"].lower()
    rp = await client.http.post(
        "/api/v1/alliances/messages", headers=h, json={"body": "déjenme entrar"}
    )
    assert rp.status_code == 400


async def test_cannot_attack_an_ally(client):
    h1 = await _register(client.http, "ally1")
    await _onboard(client.http, h1, planet="mars", race="martian")
    h2 = await _register(client.http, "ally2")
    s2 = await _onboard(client.http, h2, planet="venus", race="venusian")
    r = await client.http.post(
        "/api/v1/alliances", headers=h1, json={"name": "Pacto Estelar", "tag": "PE"}
    )
    aid = r.json()["id"]
    await client.http.post(f"/api/v1/alliances/{aid}/join", headers=h2)

    await _grant_units(client.session_maker, "ally1", {"tank": 5})
    r = await client.http.post(
        "/api/v1/combat/attack",
        headers=h1,
        json={"target_base_id": s2["bases"][0]["id"], "force": {"tank": 5}},
    )
    assert r.status_code == 400
    assert "aliado" in r.json()["detail"].lower()


async def test_alliance_leave(client):
    h = await _register(client.http, "loner")
    await _onboard(client.http, h)
    r = await client.http.post(
        "/api/v1/alliances", headers=h, json={"name": "Solitarios", "tag": "SOL"}
    )
    assert r.status_code == 201
    rl = await client.http.post("/api/v1/alliances/leave", headers=h)
    assert rl.status_code == 200 and rl.json()["left"] is True
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert me["alliance_id"] is None


async def test_alliance_ranking(client):
    h = await _register(client.http, "boss")
    await _onboard(client.http, h)
    await client.http.post(
        "/api/v1/alliances", headers=h, json={"name": "Imperio Azul", "tag": "IMP"}
    )
    r = await client.http.get("/api/v1/alliances/ranking", headers=h)
    assert r.status_code == 200
    rows = r.json()
    assert any(a["name"] == "Imperio Azul" for a in rows)
    scores = [a["score"] for a in rows]
    assert scores == sorted(scores, reverse=True)
    assert rows[0]["rank"] == 1


async def test_alliance_type_and_trade(client):
    h1 = await _register(client.http, "trader1")
    await _onboard(client.http, h1, planet="earth", race="terran")
    h2 = await _register(client.http, "trader2")
    s2 = await _onboard(client.http, h2, planet="mars", race="martian")
    r = await client.http.post(
        "/api/v1/alliances", headers=h1, json={"name": "Mercaderes", "tag": "MRC", "type": "full"}
    )
    assert r.status_code == 201 and r.json()["type"] == "full"
    aid = r.json()["id"]
    await client.http.post(f"/api/v1/alliances/{aid}/join", headers=h2)

    me1 = (await client.http.get("/api/v1/players/me", headers=h1)).json()
    assert me1["alliance_type"] == "full"

    # full alliances allow trade
    rt = await client.http.post(
        "/api/v1/alliances/transfer",
        headers=h1,
        json={"to_player_id": s2["id"], "mineral": "iron", "amount": 50},
    )
    assert rt.status_code == 200, rt.text
    me2 = (await client.http.get("/api/v1/players/me", headers=h2)).json()
    assert me2["stocks"].get("iron", 0) >= 50  # received the transfer


async def test_shared_vision_shows_ally_incoming(client):
    h1 = await _register(client.http, "watcher")
    await _onboard(client.http, h1, planet="earth", race="terran")
    h2 = await _register(client.http, "frontline")
    s2 = await _onboard(client.http, h2, planet="mars", race="martian")
    r = await client.http.post(
        "/api/v1/alliances", headers=h1, json={"name": "Vigias", "tag": "VIG", "type": "defensive"}
    )
    aid = r.json()["id"]
    await client.http.post(f"/api/v1/alliances/{aid}/join", headers=h2)

    # a non-allied attacker hits frontline (h2)
    ha = await _register(client.http, "raider")
    await _onboard(client.http, ha, planet="venus", race="venusian")
    await _grant_units(client.session_maker, "raider", {"tank": 3})
    await client.http.post(
        "/api/v1/combat/attack",
        headers=ha,
        json={"target_base_id": s2["bases"][0]["id"], "force": {"tank": 3}},
    )
    # the ally (h1) sees it via shared vision
    me1 = (await client.http.get("/api/v1/players/me", headers=h1)).json()
    assert len(me1["alliance_incoming"]) >= 1


async def test_npcs_share_an_alliance(client):
    h = await _register(client.http, "observer")
    await _onboard(client.http, h)
    await client.http.post("/api/v1/admin/tick", headers=h)  # spawns + allies NPCs

    alliances = (await client.http.get("/api/v1/alliances", headers=h)).json()
    npc_alliance = next((a for a in alliances if a["tag"] == "AI"), None)
    assert npc_alliance is not None and npc_alliance["member_count"] == 3
    # all NPC players carry that alliance_id
    players = (await client.http.get("/api/v1/players", headers=h)).json()
    npc_ids = {p["alliance_id"] for p in players if p["is_npc"]}
    assert npc_ids == {npc_alliance["id"]}

    # a human cannot infiltrate the NPC alliance (would grant immunity + benefits)
    rj = await client.http.post(f"/api/v1/alliances/{npc_alliance['id']}/join", headers=h)
    assert rj.status_code == 400


async def test_attack_self_rejected(client):
    h = await _register(client.http, "solo")
    state = await _onboard(client.http, h)
    own_base = state["bases"][0]["id"]
    await _grant_units(client.session_maker, "solo", {"tank": 1})
    r = await client.http.post(
        "/api/v1/combat/attack", headers=h, json={"target_base_id": own_base, "force": {"tank": 1}}
    )
    assert r.status_code == 400


async def test_attack_insufficient_units(client):
    ha = await _register(client.http, "attacker")
    await _onboard(client.http, ha)
    hd = await _register(client.http, "defender")
    dstate = await _onboard(client.http, hd)
    r = await client.http.post(
        "/api/v1/combat/attack",
        headers=ha,
        json={"target_base_id": dstate["bases"][0]["id"], "force": {"tank": 99}},
    )
    assert r.status_code == 400


# ---- expeditions ------------------------------------------------------------

async def test_reachable_moons(client):
    h = await _register(client.http, "earthling")
    await _onboard(client.http, h, planet="earth", race="terran")
    r = await client.http.get("/api/v1/expeditions/moons", headers=h)
    assert r.status_code == 200
    assert "luna" in {m["key"] for m in r.json()}


async def test_expedition_requires_shuttle(client):
    h = await _register(client.http, "earthling")
    await _onboard(client.http, h, planet="earth", race="terran")
    r = await client.http.post("/api/v1/expeditions", headers=h, json={"moon_key": "luna"})
    assert r.status_code == 400  # no shuttle


async def test_expedition_flow_delivers_grants_and_boon(client):
    h = await _register(client.http, "earthling")
    state = await _onboard(client.http, h, planet="earth", race="terran")
    player_id = state["id"]
    await _grant_units(client.session_maker, "earthling", {"shuttle": 1})

    r = await client.http.post("/api/v1/expeditions", headers=h, json={"moon_key": "luna"})
    assert r.status_code == 201, r.text

    # Fast-forward the mission via DB, then GET /me triggers lazy finalization.
    async with client.session_maker() as s:
        res = await s.execute(select(ExpeditionOrder).where(ExpeditionOrder.player_id == player_id))
        order = res.scalar_one()
        order.completes_at = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()

    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert me["stocks"].get("helium3", 0) == 100
    assert me["stocks"].get("rare_earth", 0) == 50
    assert any(b["effect"] == "production" for b in me["boons"])


# ---- NPCs (scoreboard + world tick) -----------------------------------------

async def test_tick_creates_npcs_and_they_act(client):
    h = await _register(client.http, "human")
    await _onboard(client.http, h)

    r = await client.http.post("/api/v1/admin/tick", headers=h)
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["npcs"] == 3  # one per race
    assert summary["npc_actions"] >= 1  # rules brain built something

    # scoreboard lists the NPCs with a base to target
    players = (await client.http.get("/api/v1/players", headers=h)).json()
    npcs = [p for p in players if p["is_npc"]]
    assert len(npcs) == 3
    assert all(p["home_base_id"] for p in npcs)


# ---- Redis-backed features (cache + rate limit) -----------------------------

async def test_catalog_cached_in_redis(client):
    import fakeredis.aioredis

    from app.core.redis import get_redis
    from app.main import app

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.dependency_overrides[get_redis] = lambda: fake
    try:
        r = await client.http.get("/api/v1/catalog")
        assert r.status_code == 200
        # first call populated the cache
        assert await fake.get("catalog:v1") is not None
    finally:
        app.dependency_overrides.pop(get_redis, None)


async def test_attack_rate_limited(client, monkeypatch):
    import fakeredis.aioredis

    from app.core.config import get_settings
    from app.core.redis import get_redis
    from app.main import app

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.dependency_overrides[get_redis] = lambda: fake
    monkeypatch.setattr(get_settings(), "attack_rate_limit_per_min", 2)
    try:
        h = await _register(client.http, "spammer")
        await _onboard(client.http, h)
        codes = []
        for _ in range(3):
            r = await client.http.post(
                "/api/v1/combat/attack",
                headers=h,
                json={"target_base_id": 99999, "force": {"tank": 1}},
            )
            codes.append(r.status_code)
        # first two pass the limiter (then 400 for bad target); third is blocked
        assert codes[-1] == 429
    finally:
        app.dependency_overrides.pop(get_redis, None)


async def test_human_can_attack_an_npc(client):
    h = await _register(client.http, "human")
    await _onboard(client.http, h, planet="mars", race="martian")
    await client.http.post("/api/v1/admin/tick", headers=h)  # spawn NPCs

    players = (await client.http.get("/api/v1/players", headers=h)).json()
    npc_base = next(p["home_base_id"] for p in players if p["is_npc"])

    await _grant_units(client.session_maker, "human", {"tank": 10})
    r = await client.http.post(
        "/api/v1/combat/attack",
        headers=h,
        json={"target_base_id": npc_base, "force": {"tank": 10}},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "outbound"  # fleet en route to the NPC
