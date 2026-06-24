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


async def _clear_protection(maker, *usernames) -> None:
    """Arrange: lift newbie protection (SDD 11) so tests can attack a fresh player."""
    async with maker() as s:
        for username in usernames:
            p = (await s.execute(select(Player).where(Player.username == username))).scalar_one()
            p.protected_until = None
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


async def test_error_message_i18n_en(client):
    # SDD 4: el detail de errores conocidos se traduce a EN con ?lang=en (o Accept-Language).
    en = await client.http.post(
        "/api/v1/auth/login?lang=en", json={"username": "nadie", "password": "x"}
    )
    assert en.status_code == 401 and en.json()["detail"] == "Invalid credentials."
    es = await client.http.post(
        "/api/v1/auth/login", json={"username": "nadie", "password": "x"}
    )
    assert es.json()["detail"] == "Credenciales invalidas"  # default ES


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


async def test_catalog_i18n(client):
    def names(body):
        return {b["key"]: b["name"] for b in body["buildings"]}

    en = (await client.http.get("/api/v1/catalog?lang=en")).json()
    assert names(en)["mine"] == "Mine"
    assert "name_en" not in en["buildings"][0]  # helper keys stripped
    # nested planets localized too
    gx = {g["key"]: g for g in en["galaxies"]}
    assert gx["milky_way"]["planets"][0]["name"] == "Earth"

    es = (await client.http.get("/api/v1/catalog?lang=es")).json()
    assert names(es)["mine"] == "Mina"
    # invalid lang -> default español; no query also español
    bad = (await client.http.get("/api/v1/catalog?lang=zz")).json()
    assert names(bad)["mine"] == "Mina"
    # Accept-Language honored when no ?lang
    r = await client.http.get("/api/v1/catalog", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert names(r.json())["mine"] == "Mine"


async def test_catalog_has_physical_fields_and_canon(client):
    cat = (await client.http.get("/api/v1/catalog")).json()
    planets = {p["key"]: p for p in cat["planets"]}
    earth = planets["earth"]
    assert earth["gravity_g"] == 1.0 and earth["canon"] == "real"
    assert earth["atmosphere"] == "thick" and earth["has_liquid_water"] is True
    assert planets["mercury"]["atmosphere"] == "none"


async def test_ship_blocked_without_water(client):
    h = await _register(client.http, "drysailor")
    state = await _onboard(client.http, h, planet="mars", race="martian")  # Marte: sin agua
    base = state["bases"][0]["id"]
    await _add_active_building(client.session_maker, "drysailor", "factory")
    r = await client.http.post(
        f"/api/v1/bases/{base}/train", headers=h, json={"unit_key": "ship", "quantity": 1}
    )
    assert r.status_code == 400 and "agua" in r.text.lower()


async def test_catalog_graph(client):
    r = await client.http.get("/api/v1/catalog/graph?race=martian&planet=mars")
    assert r.status_code == 200
    g = r.json()
    assert g["nodes"] and g["edges"]
    assert "iron" in g["minerals_local"] and "helium3" in g["minerals_imported"]
    # unknown race/planet -> clear 404
    bad = await client.http.get("/api/v1/catalog/graph?race=nope&planet=mars")
    assert bad.status_code == 404


async def test_catalog_graph_docs_and_search(client):
    docs = await client.http.get("/api/v1/catalog/graph/docs?race=martian&planet=mars")
    assert docs.status_code == 200 and docs.json()["documents"]

    # RAG retrieve: a Spanish query ranks the right nodes (synonyms map to EN keys).
    s = await client.http.get(
        "/api/v1/catalog/graph/search?race=martian&planet=mars&q=fabrica+para+tanques&k=3"
    )
    assert s.status_code == 200
    res = s.json()["results"]
    assert 0 < len(res) <= 3
    ids = [d["id"] for d in res]
    assert "factory" in ids or "tank" in ids
    scores = [d["score"] for d in res]
    assert scores == sorted(scores, reverse=True)


# ---- personal AI assistant (SDD 2) ------------------------------------------
async def _broke(client, player_id):
    from app.models import ResourceStock

    async with client.session_maker() as s:
        for st in (
            await s.execute(select(ResourceStock).where(ResourceStock.player_id == player_id))
        ).scalars():
            st.amount = 0.0
        await s.commit()


async def test_advisor_ask_returns_blockers(client):
    h = await _register(client.http, "advisee")
    state = await _onboard(client.http, h)
    await _broke(client, state["id"])

    r = await client.http.post(
        "/api/v1/players/me/advisor/ask", headers=h, json={"message": "qué construyo ahora"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"] and body["hacks_left"] == 3
    assert body["blockers"]  # broke -> something is blocked
    # asking without auth -> 401
    assert (await client.http.post("/api/v1/players/me/advisor/ask",
                                   json={"message": "hola"})).status_code == 401


async def test_advisor_hack_grants_and_exhausts_daily_budget(client):
    h = await _register(client.http, "hacker2")
    state = await _onboard(client.http, h)

    # spend the 3 daily hacks on three different blocked targets
    for target in ("mine", "barracks", "research_lab"):
        await _broke(client, state["id"])
        r = await client.http.post(
            "/api/v1/players/me/advisor/hack", headers=h, json={"target": target}
        )
        assert r.status_code == 200, r.text
        assert r.json()["granted"]

    # 4th hack today -> 429
    await _broke(client, state["id"])
    r = await client.http.post(
        "/api/v1/players/me/advisor/hack", headers=h, json={"target": "factory"}
    )
    assert r.status_code == 429, r.text


# ---- métricas + showcase público (SDD 12) -----------------------------------
async def test_public_endpoints_no_auth_and_no_email(client):
    h = await _register(client.http, "famous")
    await _onboard(client.http, h)
    # ponele un email para verificar que NO se filtra en el perfil público
    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "famous"))).scalar_one()
        p.email = "private@b.com"
        await s.commit()

    # sin headers (público)
    g = await client.http.get("/api/v1/public/stats")
    assert g.status_code == 200 and g.json()["players"] >= 1

    lb = await client.http.get("/api/v1/public/leaderboard")
    assert lb.status_code == 200 and any(e["username"] == "famous" for e in lb.json())

    prof = await client.http.get("/api/v1/public/players/famous")
    assert prof.status_code == 200
    assert prof.json()["username"] == "famous" and "battles_won" in prof.json()["stats"]
    assert "private@b.com" not in prof.text and "email" not in prof.text

    assert (await client.http.get("/api/v1/public/players/ghost")).status_code == 404
    assert (await client.http.get("/api/v1/public/hall-of-fame")).status_code == 200


# ---- galaxy instances / shards (SDD 8) --------------------------------------
async def _move_to_new_instance(maker, username):
    """Arrange: poné a un jugador en una instancia distinta (simula otra galaxia)."""
    from app.models import GalaxyInstance

    async with maker() as s:
        p = (await s.execute(select(Player).where(Player.username == username))).scalar_one()
        inst = GalaxyInstance(
            template_key="milky_way", seq=999, name="Otra #999",
            capacity=50, player_count=1, status="open",
        )
        s.add(inst)
        await s.flush()
        p.galaxy_instance_id = inst.id
        await s.commit()


async def test_me_exposes_galaxy_instance_and_list_galaxies(client):
    h = await _register(client.http, "galaxan")
    await _onboard(client.http, h)
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert me["galaxy_instance"] and me["galaxy_instance"]["player_count"] >= 1
    gx = (await client.http.get("/api/v1/galaxies", headers=h)).json()
    assert any(g["id"] == me["galaxy_instance"]["id"] for g in gx)


async def test_cannot_attack_other_galaxy_and_scoreboard_filtered(client):
    ha = await _register(client.http, "shardA")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hb = await _register(client.http, "shardB")
    sb = await _onboard(client.http, hb, planet="venus", race="venusian")
    base_b = sb["bases"][0]["id"]

    await _grant_units(client.session_maker, "shardA", {"tank": 3})
    await _clear_protection(client.session_maker, "shardA", "shardB")
    await _move_to_new_instance(client.session_maker, "shardB")  # otra galaxia

    r = await client.http.post(
        "/api/v1/combat/attack", headers=ha,
        json={"target_base_id": base_b, "force": {"tank": 3}},
    )
    assert r.status_code == 400 and "galaxia" in r.text.lower()
    # el scoreboard de A no muestra a B (otra instancia)
    listed = (await client.http.get("/api/v1/players", headers=ha)).json()
    assert all(p["username"] != "shardB" for p in listed)


# ---- temporadas + Hall of Fame + newbie protection (SDD 11) -----------------
async def test_seasons_endpoints_and_close(client):
    h = await _register(client.http, "seasonal")
    await _onboard(client.http, h)

    s = await client.http.get("/api/v1/seasons", headers=h)
    assert s.status_code == 200 and s.json()["current"]["seq"] >= 1

    r = await client.http.get("/api/v1/seasons/current/ranking", headers=h)
    assert r.status_code == 200 and isinstance(r.json(), list)

    # cerrar la temporada -> Hall of Fame poblado y nueva temporada activa
    c = await client.http.post("/api/v1/admin/season/close", headers=h)
    assert c.status_code == 200 and c.json()["closed"] == 1
    hof = (await client.http.get("/api/v1/seasons/hall-of-fame", headers=h)).json()
    assert any(e["username"] == "seasonal" for e in hof)
    nxt = (await client.http.get("/api/v1/seasons", headers=h)).json()["current"]
    assert nxt["seq"] >= 2

    # /me reporta protección de novato y temporada
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert me["protected_until"] is not None and me["season"]["seq"] >= 2


async def test_newbie_protection_blocks_attack(client):
    ha = await _register(client.http, "atkr")
    await _onboard(client.http, ha)
    hb = await _register(client.http, "prey2")
    sb = await _onboard(client.http, hb)
    base_b = sb["bases"][0]["id"]

    # atacar a un jugador protegido -> 400 con mensaje claro (antes de pedir unidades)
    r = await client.http.post(
        "/api/v1/combat/attack", headers=ha,
        json={"target_base_id": base_b, "force": {"tank": 1}},
    )
    assert r.status_code == 400 and "protec" in r.text.lower()


# ---- passwordless login: email + código OTP (SDD 6) -------------------------
async def test_otp_login_happy_path(client, monkeypatch):
    from app.services import auth_otp

    monkeypatch.setattr(auth_otp, "generate_code", lambda n: "424242")
    r = await client.http.post("/api/v1/auth/request-code", json={"email": "otp@b.com"})
    assert r.status_code == 200 and r.json()["sent"] is True

    r = await client.http.post(
        "/api/v1/auth/verify-code", json={"email": "otp@b.com", "code": "424242"}
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    # el JWT abre /players/me (cuenta creada en el verify)
    me = await client.http.get("/api/v1/players/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200


async def test_otp_request_uniform_and_invalid_email(client):
    # email con cuenta o sin cuenta: misma respuesta (anti-enumeración)
    r = await client.http.post("/api/v1/auth/request-code", json={"email": "whoever@b.com"})
    assert r.status_code == 200 and r.json()["sent"] is True
    # email inválido -> 422
    bad = await client.http.post("/api/v1/auth/request-code", json={"email": "nope"})
    assert bad.status_code == 422


async def test_otp_verify_wrong_code_401(client, monkeypatch):
    from app.services import auth_otp

    monkeypatch.setattr(auth_otp, "generate_code", lambda n: "111222")
    await client.http.post("/api/v1/auth/request-code", json={"email": "otp2@b.com"})
    r = await client.http.post(
        "/api/v1/auth/verify-code", json={"email": "otp2@b.com", "code": "000000"}
    )
    assert r.status_code == 401


async def test_register_gated_by_allowlist(client, monkeypatch):
    # SDD 14: con allowlist activa, el registro usuario+contraseña TAMBIÉN queda gateado por email.
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "allowed_emails", "vip@b.com")

    # sin email -> 403 (registro por invitación)
    r = await client.http.post(
        "/api/v1/auth/register", json={"username": "intruso", "password": "secret123"}
    )
    assert r.status_code == 403, r.text
    # email no autorizado -> 403
    r = await client.http.post(
        "/api/v1/auth/register",
        json={"username": "intruso2", "password": "secret123", "email": "otro@b.com"},
    )
    assert r.status_code == 403, r.text
    # email autorizado -> 201
    r = await client.http.post(
        "/api/v1/auth/register",
        json={"username": "vip", "password": "secret123", "email": "vip@b.com"},
    )
    assert r.status_code == 201, r.text


async def test_admin_endpoints_gated(client, monkeypatch):
    # SDD 14 v2: con ADMIN_EMAIL configurado, /admin/* exige ser admin.
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "allowed_emails", "boss@b.com,rando@b.com")
    monkeypatch.setattr(get_settings(), "admin_email", "boss@b.com")

    # jugador no-admin (email permitido pero no admin) -> 403
    r = await client.http.post(
        "/api/v1/auth/register",
        json={"username": "rando2", "password": "secret123", "email": "rando@b.com"},
    )
    tok = r.json()["access_token"]
    nonadmin = {"Authorization": f"Bearer {tok}"}
    assert (await client.http.post("/api/v1/admin/tick", headers=nonadmin)).status_code == 403

    # el admin (email configurado) -> 200
    r = await client.http.post(
        "/api/v1/auth/register",
        json={"username": "boss", "password": "secret123", "email": "boss@b.com"},
    )
    admintok = r.json()["access_token"]
    rr = await client.http.post(
        "/api/v1/admin/tick", headers={"Authorization": f"Bearer {admintok}"}
    )
    assert rr.status_code == 200, rr.text


async def test_otp_request_rate_limited(client, monkeypatch):
    # SDD 6/14: rate-limit por IP del request-code (anti-abuso del endpoint).
    import fakeredis.aioredis

    from app.core.config import get_settings
    from app.core.redis import get_redis
    from app.main import app

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.dependency_overrides[get_redis] = lambda: fake
    monkeypatch.setattr(get_settings(), "otp_rate_limit_per_min", 2)
    try:
        codes = []
        for _ in range(3):
            r = await client.http.post(
                "/api/v1/auth/request-code", json={"email": "x@b.com"}
            )
            codes.append(r.status_code)
        assert codes[-1] == 429, codes
    finally:
        app.dependency_overrides.pop(get_redis, None)


async def test_register_open_without_allowlist(client):
    # Sin allowlist (default), el registro sigue abierto (no rompe dev/CLI/tests).
    r = await client.http.post(
        "/api/v1/auth/register", json={"username": "libre", "password": "secret123"}
    )
    assert r.status_code == 201, r.text


async def test_otp_allowlist_gates_signup(client, monkeypatch):
    # SDD 14: con allowlist, solo emails autorizados pueden darse de alta. La respuesta de
    # request-code es uniforme (200/sent), pero al no-autorizado nunca se le generó código → 401.
    from app.services import auth_otp

    monkeypatch.setattr(auth_otp.get_settings(), "allowed_emails", "vip@b.com")
    monkeypatch.setattr(auth_otp, "generate_code", lambda n: "555000")

    # no autorizado: request-code responde igual (uniforme) pero verify falla
    r = await client.http.post("/api/v1/auth/request-code", json={"email": "outsider@b.com"})
    assert r.status_code == 200 and r.json()["sent"] is True
    blocked = await client.http.post(
        "/api/v1/auth/verify-code", json={"email": "outsider@b.com", "code": "555000"}
    )
    assert blocked.status_code == 401

    # autorizado: flujo completo
    await client.http.post("/api/v1/auth/request-code", json={"email": "vip@b.com"})
    ok = await client.http.post(
        "/api/v1/auth/verify-code", json={"email": "vip@b.com", "code": "555000"}
    )
    assert ok.status_code == 200, ok.text


async def test_metrics_endpoint_and_no_pii(client):
    # SDD 19: /metrics expone series clave y NO filtra PII (sin emails en labels).
    await client.http.get("/api/v1/catalog")
    await client.http.post(
        "/api/v1/auth/register",
        json={"username": "metricuser", "password": "secret123"},
    )
    r = await client.http.get("/metrics")
    assert r.status_code == 200
    body = r.text
    assert "http_requests_total" in body
    assert "game_sse_connections" in body
    assert 'game_signups_total{method="password"}' in body
    assert "@" not in body  # ninguna serie con email/PII


async def test_presence_online_endpoints(client, monkeypatch):
    # SDD 21: /players/me marca presencia → /public/online cuenta; /admin/online lista (admin).
    from app.core.config import get_settings
    from app.services import presence

    presence._mem.clear()
    monkeypatch.setattr(get_settings(), "admin_email", "boss@b.com")
    monkeypatch.setattr(get_settings(), "allowed_emails", "boss@b.com,p1@b.com")

    # registrar con email permitido (allowlist activa)
    r = await client.http.post(
        "/api/v1/auth/register",
        json={"username": "p1user", "password": "secret123", "email": "p1@b.com"},
    )
    assert r.status_code == 201, r.text
    htok = {"Authorization": f"Bearer {r.json()['access_token']}"}
    await client.http.get("/api/v1/players/me", headers=htok)  # heartbeat

    pub = await client.http.get("/api/v1/public/online")
    assert pub.status_code == 200 and pub.json()["count"] >= 1

    # /admin/online: no-admin -> 403
    assert (await client.http.get("/api/v1/admin/online", headers=htok)).status_code == 403
    # admin -> lista
    ra = await client.http.post(
        "/api/v1/auth/register",
        json={"username": "boss", "password": "secret123", "email": "boss@b.com"},
    )
    atok = {"Authorization": f"Bearer {ra.json()['access_token']}"}
    adm = await client.http.get("/api/v1/admin/online", headers=atok)
    assert adm.status_code == 200 and "p1user" in adm.json()["players"]


async def test_metrics_token_guard(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "metrics_token", "sekret-token")
    r = await client.http.get("/metrics")
    assert r.status_code == 401
    ok = await client.http.get("/metrics", headers={"Authorization": "Bearer sekret-token"})
    assert ok.status_code == 200


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
    await _clear_protection(client.session_maker, "attacker", "defender")
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
    await _clear_protection(client.session_maker, "attacker", "defender")
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
    await _clear_protection(client.session_maker, "attacker", "defender")

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
    await _clear_protection(client.session_maker, "attacker", "defender")
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
    await _clear_protection(client.session_maker, "attacker", "defender")

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
    await _clear_protection(client.session_maker, "warlord", "victim")
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
    await _clear_protection(client.session_maker, "raider", "frontline")
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
        # first call populated the cache (keyed per language; default es)
        assert await fake.get("catalog:v1:es") is not None
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


async def test_advisor_rate_limited(client, monkeypatch):
    # SDD 9: el asistente está rate-limitado por jugador (la IA es serial, una GPU = una cola).
    import fakeredis.aioredis

    from app.core.config import get_settings
    from app.core.redis import get_redis
    from app.main import app

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.dependency_overrides[get_redis] = lambda: fake
    monkeypatch.setattr(get_settings(), "advisor_rate_limit_per_min", 2)
    try:
        h = await _register(client.http, "advisor_spammer")
        await _onboard(client.http, h)
        codes = []
        for _ in range(3):
            r = await client.http.post(
                "/api/v1/players/me/advisor/ask",
                headers=h,
                json={"message": "que construyo?"},
            )
            codes.append(r.status_code)
        # las dos primeras pasan el limiter (200); la tercera queda bloqueada
        assert codes[0] == 200, codes
        assert codes[-1] == 429, codes
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
