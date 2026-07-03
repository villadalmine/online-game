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


async def _grant_units(maker, username, units: dict[str, int], base_id=None) -> None:
    """Arrange: drop units straight into a player's stock (bypasses training timers). SDD 62:
    `base_id` los estaciona en una base (guarnición); None = pool global (histórico)."""
    async with maker() as s:
        res = await s.execute(select(Player).where(Player.username == username))
        player = res.scalar_one()
        for unit_key, qty in units.items():
            s.add(UnitStock(player_id=player.id, unit_key=unit_key, quantity=qty, base_id=base_id))
        await s.commit()


async def _clear_protection(maker, *usernames) -> None:
    """Arrange: lift newbie protection (SDD 11) so tests can attack a fresh player."""
    async with maker() as s:
        for username in usernames:
            p = (await s.execute(select(Player).where(Player.username == username))).scalar_one()
            p.protected_until = None
        await s.commit()


# ---- meta / auth -----------------------------------------------------------

async def test_landing_page_and_og(client):
    # SDD 24: landing pública /game bilingüe con Open Graph + imagen social.
    r = await client.http.get("/game")
    assert r.status_code == 200
    b = r.text
    assert 'property="og:title"' in b and 'name="twitter:card"' in b
    assert "Conquistá la galaxia" in b and "Conquer the galaxy" in b  # ES + EN
    assert "BYOD" in b
    assert '/tech' in b   # enlace a la página técnica
    img = await client.http.get("/og-image.png")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"


async def test_html_served_with_no_cache(client):
    # HTML con Cache-Control: no-cache → tras un deploy se ve lo nuevo sin hard-refresh.
    for path in ("/", "/game", "/tech"):
        r = await client.http.get(path)
        assert r.status_code == 200, path
        assert "no-cache" in r.headers.get("cache-control", ""), path


async def test_tech_page(client):
    # Página técnica pública /tech: stack self-hosted + flujo de tráfico (HAProxy SNI → Gateway).
    r = await client.http.get("/tech")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    b = r.text
    assert "self-hosted" in b and "HAProxy" in b and "SNI passthrough" in b
    assert "Cilium" in b and "k3s" in b and "Gateway" in b
    # sección "cómo usa la IA": GPU local + subgrafo + gemma-4 pago (no free)
    assert "subgrafo" in b and "gemma-4" in b
    # no debe filtrar direccionamiento privado exacto
    assert "192.168." not in b


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


async def test_all_keys_no_server_error(client):
    """SDD 45: barre TODOS los keys (minerales en hub buy/sell, edificios en build, unidades en
    train) y falla si ALGUNO devuelve 500. Atrapa errores key-específicos (p.ej. el de 'iron')."""
    from app.models import ResourceStock
    h = await _register(client.http, "sweeper")
    state = await _onboard(client.http, h, planet="earth", race="terran")
    base_id = state["bases"][0]["id"]
    planet = "earth"
    cat = (await client.http.get("/api/v1/catalog")).json()
    minerals = [m["key"] for m in cat["minerals"]]
    buildings = [b["key"] for b in cat["buildings"] if b["key"] != "headquarters"]
    units = [u["key"] for u in (cat["personnel"] + cat["heavy_units"])]
    # sembrar sin límites: energía enorme, naves de carga, y stock de TODOS los minerales en casa
    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "sweeper"))).scalar_one()
        p.energy = 10_000_000
        s.add(UnitStock(player_id=p.id, unit_key="cargo_ship", quantity=50))
        for m in minerals:
            row = (await s.execute(select(ResourceStock).where(
                ResourceStock.player_id == p.id, ResourceStock.mineral_key == m,
                ResourceStock.planet_key == planet))).scalar_one_or_none()
            if row:
                row.amount = 10_000_000
            else:
                s.add(ResourceStock(player_id=p.id, mineral_key=m, amount=10_000_000,
                                    planet_key=planet))
        await s.commit()

    fails = []
    for m in minerals:
        for side in ("buy", "sell"):
            r = await client.http.post(f"/api/v1/market/hub/{side}", headers=h,
                                       json={"mineral_key": m, "qty": 1})
            if r.status_code >= 500:
                fails.append(f"hub {side} {m}: {r.status_code} {r.text[:120]}")
    for b in buildings:
        body = {"building_key": b}
        if b == "mine":
            body["target_mineral"] = "iron"
        r = await client.http.post(f"/api/v1/bases/{base_id}/build", headers=h, json=body)
        if r.status_code >= 500:
            fails.append(f"build {b}: {r.status_code} {r.text[:120]}")
    for u in units:
        r = await client.http.post(f"/api/v1/bases/{base_id}/train", headers=h,
                                   json={"unit_key": u, "quantity": 1})
        if r.status_code >= 500:
            fails.append(f"train {u}: {r.status_code} {r.text[:120]}")
    assert not fails, "errores 500 por key:\n" + "\n".join(fails)


async def test_defense_never_locked_by_single_mineral_e2e(client):
    """SDD 53: con SOLO el mineral estructural (iron, sin el energético) un terran igual entrena
    infantería (defensa) pero NO algo que pida el energético → la defensa nunca queda gateada."""
    from app.models import ResourceStock
    h = await _register(client.http, "lockout")
    state = await _onboard(client.http, h, planet="earth", race="terran")
    base_id = state["bases"][0]["id"]
    # terran: structural=iron, energetic=silicon, advanced=aluminum. Dejamos SOLO iron.
    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "lockout"))).scalar_one()
        p.energy = 10_000
        for m, amt in (("iron", 10_000), ("silicon", 0), ("aluminum", 0)):
            row = (await s.execute(select(ResourceStock).where(
                ResourceStock.player_id == p.id, ResourceStock.mineral_key == m,
                ResourceStock.planet_key == "earth"))).scalar_one_or_none()
            if row:
                row.amount = amt
            else:
                s.add(ResourceStock(player_id=p.id, mineral_key=m, amount=amt,
                                    planet_key="earth"))
        await s.commit()
    # Defensa (soldier, solo requiere headquarters): se entrena con SOLO iron → OK.
    ok = await client.http.post(f"/api/v1/bases/{base_id}/train", headers=h,
                                json={"unit_key": "soldier", "quantity": 1})
    assert ok.status_code in (200, 201), ok.text
    # En cambio el worker pide el energético (silicon=0) → bloquea (no es defensa, es economía).
    blocked = await client.http.post(f"/api/v1/bases/{base_id}/train", headers=h,
                                     json={"unit_key": "worker", "quantity": 1})
    assert blocked.status_code >= 400 and blocked.status_code < 500, blocked.text


async def test_training_capacity_headroom_e2e(client):
    """SDD 56: /players/me expone plazas libres por dominio y entrenar MÁS de lo que entra se
    bloquea por plazas (no por material) → el front muestra el headroom y topea la cantidad."""
    from app.models import ResourceStock
    h = await _register(client.http, "capper")
    state = await _onboard(client.http, h, planet="earth", race="terran")
    base_id = state["bases"][0]["id"]
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert "housing" in me and "infantry" in me["housing"]
    inf_free = me["housing"]["infantry"]["free"]
    assert inf_free >= 0
    # energía + iron de sobra → el único límite son las plazas (soldier = structural=iron, SDD 53)
    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "capper"))).scalar_one()
        p.energy = 1_000_000
        row = (await s.execute(select(ResourceStock).where(
            ResourceStock.player_id == p.id, ResourceStock.mineral_key == "iron",
            ResourceStock.planet_key == "earth"))).scalar_one_or_none()
        if row:
            row.amount = 1_000_000
        else:
            s.add(ResourceStock(player_id=p.id, mineral_key="iron", amount=1_000_000,
                                planet_key="earth"))
        await s.commit()
    r = await client.http.post(f"/api/v1/bases/{base_id}/train", headers=h,
                               json={"unit_key": "soldier", "quantity": inf_free + 5})
    assert r.status_code >= 400 and "plaza" in r.text.lower(), r.text


async def test_stocks_exposed_per_planet_e2e(client):
    """SDD 59: el stock es POR planeta (SDD 42); `/players/me` expone `stocks_by_planet` → la UI
    muestra el material de cada colonia (comprar en un planeta y construir en otro daba 'falta')."""
    h = await _register(client.http, "perplanet")
    await _onboard(client.http, h, planet="earth", race="terran")
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert "stocks_by_planet" in me and "earth" in me["stocks_by_planet"]
    agg, byp = me["stocks"], me["stocks_by_planet"]["earth"]
    for m, v in byp.items():
        assert agg.get(m, 0) >= v          # el agregado contiene lo de cada planeta


async def test_catalog_tree_computed(client):
    """/catalog/tree: skill tree + tablas con costos resueltos por raza y dependencias
    (lo consume el modal web y la IA)."""
    r = await client.http.get("/api/v1/catalog/tree", params={"race": "terran", "planet": "earth"})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["race"] == "terran" and {"buildings", "technologies", "units"} <= set(t)
    units = {u["key"]: u for u in t["units"]}
    # terrícola: estructural→hierro; el tanque cuesta hierro y depende de fábrica + tech weapons
    tank = units["tank"]
    assert tank["cost"].get("iron", 0) > 0
    assert tank["requires"] == "factory" and tank["requires_tech"] == "weapons"
    assert tank["domain"] == "ground" and "research_lab" in tank["prerequisites"]
    techs = {t_["key"]: t_ for t_ in t["technologies"]}
    assert techs["deep_core_mining"]["requires_tech"] == "mining_efficiency"  # árbol/prereq
    # raza desconocida → 404
    bad = await client.http.get("/api/v1/catalog/tree", params={"race": "zzz", "planet": "earth"})
    assert bad.status_code == 404


async def test_catalog_pictographic_icons(client):
    # SDD 43 F1: el catálogo expone icon (universal) en minerales/unidades/edificios y symbol en
    # minerales (la "letra"), para el modo pictográfico. No se localiza.
    body = (await client.http.get("/api/v1/catalog")).json()
    minerals = {m["key"]: m for m in body["minerals"]}
    assert minerals["iron"]["icon"] and minerals["iron"]["symbol"] == "Fe"
    builds = {b["key"]: b for b in body["buildings"]}
    assert builds["mine"]["icon"]
    units = {u["key"]: u for u in (body["personnel"] + body["heavy_units"])}
    assert units["worker"]["icon"] and units["tank"]["icon"]
    # SDD 43 (mercado/hub/transitos): planetas y lunas traen icon para selectores/tránsitos
    planets = {p["key"]: p for p in body["planets"]}
    assert planets["earth"]["icon"] and planets["mars"]["icon"]
    moons = {m["key"]: m for m in body["moons"]}
    assert moons["luna"]["icon"]
    # universal: el icon es igual en inglés (no se traduce)
    en = (await client.http.get("/api/v1/catalog?lang=en")).json()
    en_iron = {m["key"]: m for m in en["minerals"]}["iron"]
    assert en_iron["icon"] == minerals["iron"]["icon"]
    assert en_iron["symbol"] == "Fe"
    en_earth = {p["key"]: p for p in en["planets"]}["earth"]
    assert en_earth["icon"] == planets["earth"]["icon"]   # ícono universal, no se traduce


async def test_tts_server_fallback(client):
    # SDD 43: TTS de servidor (espeak-ng) para navegadores sin voces. Texto vacío -> 400; con texto,
    # devuelve audio/wav (o 503 si el binario no está en este entorno — sin romper la suite).
    import shutil
    bad = await client.http.get("/api/v1/tts?text=")
    assert bad.status_code == 400
    r = await client.http.get("/api/v1/tts", params={"text": "hierro", "lang": "es"})
    if shutil.which("espeak-ng"):
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "audio/wav"
        assert r.content[:4] == b"RIFF"   # cabecera WAV
    else:
        assert r.status_code == 503


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


async def test_catalog_buildings_units_have_real_localized(client):
    # SDD 13: edificios y unidades exponen su contraparte real + sources, localizable a EN.
    es = (await client.http.get("/api/v1/catalog?lang=es")).json()
    mine = {b["key"]: b for b in es["buildings"]}["mine"]
    assert "ISRU" in mine["real"] and mine["sources"]
    tank = {u["key"]: u for u in es["heavy_units"]}["tank"]
    assert tank["real"] and tank["sources"]

    en = (await client.http.get("/api/v1/catalog?lang=en")).json()
    mine_en = {b["key"]: b for b in en["buildings"]}["mine"]
    assert "in-situ" in mine_en["real"].lower()  # real localizado a inglés
    assert "real_en" not in mine_en  # helper key removido
    worker_en = {u["key"]: u for u in en["personnel"]}["worker"]
    assert "labour" in worker_en["real"].lower()


async def test_ship_blocked_without_water(client):
    h = await _register(client.http, "drysailor")
    state = await _onboard(client.http, h, planet="mars", race="martian")  # Marte: sin agua
    base = state["bases"][0]["id"]
    await _add_active_building(client.session_maker, "drysailor", "factory")
    r = await client.http.post(
        f"/api/v1/bases/{base}/train", headers=h, json={"unit_key": "ship", "quantity": 1}
    )
    assert r.status_code == 400 and "agua" in r.text.lower()


async def test_mutating_action_returns_409_when_player_locked(client):
    # Deuda técnica de prod: lock distribuido por jugador en acciones mutantes. Si otro request
    # ya tiene el lock (Redis), la acción concurrente devuelve 409 en vez de doble-gastar.
    from app.core.redis import get_redis
    from app.main import app

    class _LockedRedis:
        async def set(self, *a, **k):
            return None  # NX falla → simula lock ya tomado por otro request

    h = await _register(client.http, "locked")
    state = await _onboard(client.http, h)
    base = state["bases"][0]["id"]
    app.dependency_overrides[get_redis] = lambda: _LockedRedis()
    try:
        r = await client.http.post(
            f"/api/v1/bases/{base}/build", headers=h, json={"building_key": "mine"}
        )
    finally:
        app.dependency_overrides.pop(get_redis, None)
    assert r.status_code == 409 and "en curso" in r.text.lower()


async def test_mining_staffing_and_storage_e2e(client, monkeypatch):
    """SDD 47: con staffing on, las minas sin obreros no rinden; con obreros suficientes rinden;
    con storage caps on, al llenarse el tope el excedente se desperdicia (overflowing)."""
    from app.core.config import get_settings
    from app.models import ResourceStock
    s_ = get_settings()
    monkeypatch.setattr(s_, "mining_staffing_enabled", True)
    monkeypatch.setattr(s_, "storage_caps_enabled", True)
    monkeypatch.setattr(s_, "base_storage_per_mineral", 1000.0)
    monkeypatch.setattr(s_, "mining_staffing_floor", 0.0)   # piso 0: probamos staffing puro

    h = await _register(client.http, "miner")
    state = await _onboard(client.http, h, planet="earth", race="terran")
    base_id = state["bases"][0]["id"]
    past = datetime.now(UTC) - timedelta(hours=2)

    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "miner"))).scalar_one()
        pid = p.id
        p.energy = 1_000_000
        for _ in range(2):   # dos minas de hierro activas que produjeron hace 2h
            s.add(Building(base_id=base_id, building_key="mine", status="active",
                           production_mineral="iron", completes_at=past, last_collected_at=past))
        await s.commit()

    # (1) sin obreros: staffing 0 → no producen (el hierro inicial no sube)
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert me["mining"]["required_workers"] == 10      # 2 minas × 5 plazas
    assert me["mining"]["available_workers"] == 0
    assert me["mining"]["staffing"] == 0.0
    iron0 = me["stocks"].get("iron", 0)

    # (2) con 10 obreros: staffing 1 → producen (hierro sube)
    await _grant_units(client.session_maker, "miner", {"worker": 10})
    async with client.session_maker() as s:   # reseteo el reloj de las minas a 2h atrás
        for b in (await s.execute(select(Building).where(
                Building.base_id == base_id, Building.building_key == "mine"))).scalars():
            b.last_collected_at = past
        await s.commit()
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert me["mining"]["staffing"] == 1.0
    assert me["stocks"]["iron"] > iron0
    cap = me["storage"]["earth"]["iron"]["cap"]
    assert cap == 1000 + 5000 + 2000 + 2000            # base + HQ + 2 minas

    # (3) overflow: lleno el almacén casi al tope → el resto se desperdicia, nunca supera el cap
    async with client.session_maker() as s:
        row = (await s.execute(select(ResourceStock).where(
            ResourceStock.player_id == pid, ResourceStock.mineral_key == "iron",
            ResourceStock.planet_key == "earth"))).scalar_one()
        row.amount = cap - 5
        for b in (await s.execute(select(Building).where(
                Building.base_id == base_id, Building.building_key == "mine"))).scalars():
            b.last_collected_at = past
        await s.commit()
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    cell = me["storage"]["earth"]["iron"]
    assert cell["overflowing"] is True
    assert cell["stock"] <= cell["cap"]
    assert me["stocks"]["iron"] <= cap + 0.5           # el excedente no se acreditó


async def test_unit_housing_capacity_enforced_e2e(client, monkeypatch):
    """SDD 46: con enforce on, sin cuartel no hay plazas de infantería → entrenar soldado falla;
    al construir el cuartel sube la capacidad y se desbloquea; /players/me expone el alojamiento."""
    from app.core.config import get_settings
    from app.models import ResourceStock
    monkeypatch.setattr(get_settings(), "housing_enforced", True)
    monkeypatch.setattr(get_settings(), "base_housing_per_domain", 0)   # sin gracia: enforce puro

    h = await _register(client.http, "barracker")
    state = await _onboard(client.http, h, planet="earth", race="terran")
    base_id = state["bases"][0]["id"]
    cat = (await client.http.get("/api/v1/catalog")).json()
    minerals = [m["key"] for m in cat["minerals"]]
    async with client.session_maker() as s:   # energía + minerales de sobra en la Tierra
        p = (await s.execute(select(Player).where(Player.username == "barracker"))).scalar_one()
        p.energy = 1_000_000
        for m in minerals:
            row = (await s.execute(select(ResourceStock).where(
                ResourceStock.player_id == p.id, ResourceStock.mineral_key == m,
                ResourceStock.planet_key == "earth"))).scalar_one_or_none()
            if row:
                row.amount = 1_000_000
            else:
                s.add(ResourceStock(player_id=p.id, mineral_key=m, amount=1_000_000,
                                    planet_key="earth"))
        await s.commit()

    # sin cuartel: infantería sin plazas → 400 con mensaje accionable
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert me["housing"]["infantry"]["capacity"] == 0
    r = await client.http.post(f"/api/v1/bases/{base_id}/train", headers=h,
                               json={"unit_key": "soldier", "quantity": 1})
    assert r.status_code == 400 and "plaza" in r.text.lower()

    # construyo un cuartel activo → capacidad 30 → entrenar funciona y la ocupación sube
    await _add_active_building(client.session_maker, "barracker", "barracks")
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert me["housing"]["infantry"]["capacity"] == 30
    r = await client.http.post(f"/api/v1/bases/{base_id}/train", headers=h,
                               json={"unit_key": "soldier", "quantity": 1})
    assert r.status_code == 201, r.text
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert me["housing"]["infantry"]["occupancy"] == 1   # la unidad en cola ya reserva plaza


async def test_physics_gravity_scales_build_time(client, monkeypatch):
    # SDD 13 §4: con physics on, construir en baja gravedad (Marte 0.38g) tarda menos que en la
    # Tierra (1g). Con physics off, ambos tardan igual (neutral). Encendemos el singleton settings.
    from datetime import datetime

    from app.core.config import get_settings

    async def _build_seconds(planet, race, user):
        h = await _register(client.http, user)
        st = await _onboard(client.http, h, planet=planet, race=race)
        base = st["bases"][0]["id"]
        r = await client.http.post(
            f"/api/v1/bases/{base}/build",
            headers=h,
            json={"building_key": "mine", "target_mineral": "iron"},
        )
        assert r.status_code == 201, r.text
        completes = datetime.fromisoformat(r.json()["completes_at"])
        return (completes - datetime.now(completes.tzinfo)).total_seconds()

    monkeypatch.setattr(get_settings(), "physics_enabled", True)
    mars = await _build_seconds("mars", "martian", "gquick")
    earth = await _build_seconds("earth", "terran", "gslow")
    assert mars < earth * 0.9  # Marte (0.38g) claramente más rápido que la Tierra

    monkeypatch.setattr(get_settings(), "physics_enabled", False)
    mars_off = await _build_seconds("mars", "martian", "goffm")
    earth_off = await _build_seconds("earth", "terran", "goffe")
    assert abs(mars_off - earth_off) < 2.0  # off ⇒ mismo tiempo (neutral)


async def test_physics_extreme_planet_regenerates_less_energy(client, monkeypatch):
    # SDD 13 §4: en un planeta hostil (Marte: poca insolación + frío extremo) la energía se
    # regenera más lento que en la Tierra. Verificado por la API tras 1h de regen.
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "physics_enabled", True)

    async def _energy_after_1h(planet, race, user):
        h = await _register(client.http, user)
        await _onboard(client.http, h, planet=planet, race=race)
        async with client.session_maker() as s:
            p = (await s.execute(select(Player).where(Player.username == user))).scalar_one()
            p.energy = 0.0
            p.energy_updated_at = datetime.now(UTC) - timedelta(hours=1)
            await s.commit()
        me = (await client.http.get("/api/v1/players/me", headers=h)).json()
        return me["energy"]

    earth = await _energy_after_1h("earth", "terran", "warmworld")
    mars = await _energy_after_1h("mars", "martian", "coldworld")
    assert 0 < mars < earth  # Marte regenera menos que la Tierra


async def test_npc_strategy_runs_in_tick(client):
    # SDD 29: el tick corre la capa estratégica de NPCs sin romper, y cada NPC queda con una
    # postura VÁLIDA persistida (no asumimos una exacta: el orden/estado entre tests puede variar).
    from app.services.npc import POSTURES

    h = await _register(client.http, "ticker")
    await _onboard(client.http, h)
    r = await client.http.post("/api/v1/admin/tick", headers=h)
    assert r.status_code == 200
    async with client.session_maker() as s:
        npcs = (await s.execute(select(Player).where(Player.is_npc.is_(True)))).scalars().all()
        assert npcs and all(n.npc_posture in POSTURES for n in npcs)


async def test_spy_and_intel_e2e(client):
    # SDD 35: lanzar espías → resolver al llegar → leer intel acumulada por objetivo.
    from datetime import UTC, datetime, timedelta

    from app.models import SpyMission, UnitStock

    ho = await _register(client.http, "spyboss")
    await _onboard(client.http, ho)
    ht = await _register(client.http, "victim")
    st = await _onboard(client.http, ht)
    target_base = st["bases"][0]["id"]

    async with client.session_maker() as s:
        obs = (await s.execute(select(Player).where(Player.username == "spyboss"))).scalar_one()
        s.add(UnitStock(player_id=obs.id, unit_key="spy", quantity=3))
        await s.commit()

    r = await client.http.post(
        "/api/v1/spy", headers=ho, json={"target_base_id": target_base, "spies": {"spy": 3}}
    )
    assert r.status_code == 201, r.text

    # adelantar la llegada y disparar el advance (GET /players/me) para resolver
    async with client.session_maker() as s:
        m = (await s.execute(select(SpyMission))).scalars().first()
        m.arrives_at = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()
    await client.http.get("/api/v1/players/me", headers=ho)

    intel = (await client.http.get("/api/v1/intel", headers=ho)).json()
    assert any(i["target"] == "victim" and i["depth"] > 0 for i in intel)

    # error: base inexistente
    bad = await client.http.post(
        "/api/v1/spy", headers=ho, json={"target_base_id": 999999, "spies": {"spy": 1}}
    )
    assert bad.status_code == 400


async def test_shared_vision_shares_intel_e2e(client):
    # SDD 35: una alianza con shared_vision comparte la intel — B ve lo que espió A.
    from datetime import UTC, datetime, timedelta

    from app.models import SpyMission, UnitStock

    ha = await _register(client.http, "vis_a")
    await _onboard(client.http, ha)
    hb = await _register(client.http, "vis_b")
    await _onboard(client.http, hb)
    hr = await _register(client.http, "vis_rival")
    sr = await _onboard(client.http, hr)
    rival_base = sr["bases"][0]["id"]

    # alianza con shared_vision (defensive): A crea, B se une
    al = (await client.http.post(
        "/api/v1/alliances", headers=ha,
        json={"name": "Vigias", "tag": "VIG", "type": "defensive"},
    )).json()
    j = await client.http.post(f"/api/v1/alliances/{al['id']}/join", headers=hb)
    assert j.status_code in (200, 201), j.text

    async with client.session_maker() as s:
        a = (await s.execute(select(Player).where(Player.username == "vis_a"))).scalar_one()
        s.add(UnitStock(player_id=a.id, unit_key="spy", quantity=4))
        await s.commit()

    r = await client.http.post(
        "/api/v1/spy", headers=ha, json={"target_base_id": rival_base, "spies": {"spy": 4}}
    )
    assert r.status_code == 201, r.text
    async with client.session_maker() as s:
        m = (await s.execute(select(SpyMission))).scalars().first()
        m.arrives_at = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()
    await client.http.get("/api/v1/players/me", headers=ha)

    # B ve la intel compartida (shared=True, via vis_a) sin haber espiado
    intel = (await client.http.get("/api/v1/intel", headers=hb)).json()
    shared = [i for i in intel if i["target"] == "vis_rival"]
    assert shared and shared[0]["shared"] is True and shared[0]["via"] == "vis_a"


async def test_profile_update_nick_and_password_e2e(client):
    # Cambiar nick + clave sin validar (autenticado); el reset olvidado va por OTP (login x código).
    h = await _register(client.http, "changer")
    await _onboard(client.http, h)
    r = await client.http.post(
        "/api/v1/players/me/profile", headers=h,
        json={"username": "changer2", "password": "newpass123"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "changer2"
    tok = r.json()["access_token"]
    # el token nuevo sirve y refleja el nick
    me = await client.http.get("/api/v1/players/me", headers={"Authorization": f"Bearer {tok}"})
    assert me.status_code == 200 and me.json()["username"] == "changer2"
    # login con nick + clave nuevos
    lg = await client.http.post(
        "/api/v1/auth/login", json={"username": "changer2", "password": "newpass123"}
    )
    assert lg.status_code == 200
    # nick en uso → 409
    h2 = await _register(client.http, "other")
    dup = await client.http.post(
        "/api/v1/players/me/profile", headers=h2, json={"username": "changer2"}
    )
    assert dup.status_code == 409


async def test_market_prices_and_buy_guard_e2e(client):
    # SDD 42: tabla de precios pública + comprar sin mercado → 400.
    h = await _register(client.http, "shopper")
    await _onboard(client.http, h)
    pr = (await client.http.get("/api/v1/market/prices?planet=mars", headers=h)).json()
    assert "prices" in pr and "iron" in pr["prices"]
    r = await client.http.post(
        "/api/v1/market/buy", headers=h,
        json={"planet_key": "mars", "mineral_key": "iron", "qty": 5},
    )
    assert r.status_code == 400   # sin mercado construido


async def test_black_market_barter_e2e(client):
    # SDD 42 Fase 3: trueque material-por-material en el mercado negro (sin energía, requiere nave).
    from app.models import Player, UnitStock
    from app.services.economy import get_or_create_stock

    h = await _register(client.http, "smuggler_e2e")
    await _onboard(client.http, h)   # terran/earth

    # el hub expone el cambio del mercado negro para que la UI estime (SDD 42)
    hub = (await client.http.get("/api/v1/market/hub", headers=h)).json()
    assert 0 < hub["black_market_rate"] <= 1

    # sin nave → 400
    blind = await client.http.post(
        "/api/v1/market/blackmarket", headers=h,
        json={"pay_mineral": "iron", "pay_qty": 100, "get_mineral": "titanium"},
    )
    assert blind.status_code == 400

    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "smuggler_e2e"))).scalar_one()
        s.add(UnitStock(player_id=p.id, unit_key="cargo_ship", quantity=1))
        (await get_or_create_stock(s, p.id, "iron", p.planet_key)).amount = 1000.0
        await s.commit()

    r = await client.http.post(
        "/api/v1/market/blackmarket", headers=h,
        json={"pay_mineral": "iron", "pay_qty": 500, "get_mineral": "titanium"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["paid"] == 500 and body["received"] > 0
    assert body["pay_mineral"] == "iron"
    assert body["get_mineral"] == "titanium"


async def test_transport_with_escort_e2e(client):
    # SDD 42 Fase 3: despachar un convoy con escolta militar (defensa anti-piratas).
    from app.models import Player, UnitStock
    from app.services.economy import get_or_create_stock

    h = await _register(client.http, "convoy_e2e")
    await _onboard(client.http, h)   # terran/earth
    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "convoy_e2e"))).scalar_one()
        s.add(UnitStock(player_id=p.id, unit_key="cargo_ship", quantity=1))
        s.add(UnitStock(player_id=p.id, unit_key="tank", quantity=2))
        (await get_or_create_stock(s, p.id, "iron", "earth")).amount = 1000.0
        await s.commit()

    # escoltar con nave de carga → 400
    bad = await client.http.post(
        "/api/v1/market/transport", headers=h,
        json={"from_planet": "earth", "to_planet": "mars", "cargo": {"iron": 100},
              "escort": {"cargo_ship": 1}},
    )
    assert bad.status_code == 400

    r = await client.http.post(
        "/api/v1/market/transport", headers=h,
        json={"from_planet": "earth", "to_planet": "mars", "cargo": {"iron": 300},
              "escort": {"tank": 1}},
    )
    assert r.status_code == 201, r.text
    assert r.json()["escort"] == {"tank": 1}
    # la escolta partió con el convoy → queda 1 tank
    ts = (await client.http.get("/api/v1/market/transport", headers=h)).json()
    assert any(t["escort"] == {"tank": 1} for t in ts)
    # /me lo expone para el panel de Colas (con ETA): ahí se ve el viaje y cuándo llega
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert me["transports"] and me["transports"][0]["to_planet"] == "mars"
    assert me["transports"][0]["arrives_at"]


async def test_hangar_raises_transport_cap_e2e(client):
    # SDD 42 Fase 3: el hangar (en el catálogo) sube el cupo de naves de carga por ventana.
    from app.models import Base_, Building, Player, UnitStock
    from app.services.economy import get_or_create_stock

    cat = (await client.http.get("/api/v1/catalog")).json()
    assert any(b["key"] == "hangar" for b in cat["buildings"])

    h = await _register(client.http, "hangar_e2e")
    await _onboard(client.http, h)   # terran/earth
    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "hangar_e2e"))).scalar_one()
        s.add(UnitStock(player_id=p.id, unit_key="cargo_ship", quantity=10))
        (await get_or_create_stock(s, p.id, "iron", "earth")).amount = 4000.0
        await s.commit()

    # sin hangar: 6 naves (3000/500) > cupo base 4 → 400
    body = {"from_planet": "earth", "to_planet": "mars", "cargo": {"iron": 3000}}
    over = await client.http.post("/api/v1/market/transport", headers=h, json=body)
    assert over.status_code == 400

    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "hangar_e2e"))).scalar_one()
        base = (await s.execute(select(Base_).where(Base_.player_id == p.id))).scalars().first()
        s.add(Building(base_id=base.id, building_key="hangar", status="active"))
        await s.commit()

    ok = await client.http.post("/api/v1/market/transport", headers=h, json=body)
    assert ok.status_code == 201, ok.text
    assert ok.json()["ships"] == 6


async def test_colonize_options_e2e(client):
    # SDD 37: el grafo de opciones raza×planeta para tu imperio.
    h = await _register(client.http, "colonizer")
    await _onboard(client.http, h)   # terran on earth (default _onboard)
    r = await client.http.get("/api/v1/colonize/options", headers=h)
    assert r.status_code == 200, r.text
    opts = r.json()
    assert opts and all("verdict" in o for o in opts)
    home = [o for o in opts if o["is_home"]]
    assert home and home[0]["verdict"] == "great"
    # pre-cálculo de costo: cada opción expone energía (surface/orbital) y transbordadores.
    o0 = opts[0]
    assert o0["energy_surface"] > 0
    assert o0["energy_orbital"] >= o0["energy_surface"]  # orbital cuesta más (mult >= 1)
    assert o0["shuttle_cost"] >= 1


async def test_colonize_with_tech_e2e(client):
    # SDD 37: con tech de colonización + transbordador, fundar una colonia en un mundo hostil.
    from app.models import Player, PlayerTech, UnitStock

    h = await _register(client.http, "settler")
    await _onboard(client.http, h)   # terran/earth

    # sin tech: Marte imposible → 400
    blind = await client.http.post("/api/v1/colonize", headers=h, json={"planet_key": "earth"})
    assert blind.status_code == 400

    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "settler"))).scalar_one()
        s.add(PlayerTech(player_id=p.id, tech_key="antigravity"))
        s.add(PlayerTech(player_id=p.id, tech_key="thermal_shielding"))
        s.add(UnitStock(player_id=p.id, unit_key="shuttle", quantity=1))
        p.energy = 999.0
        await s.commit()

    r = await client.http.post("/api/v1/colonize", headers=h, json={"planet_key": "earth"})
    assert r.status_code == 201, r.text
    assert r.json()["planet_key"] == "earth"
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert any(b["planet_key"] == "earth" for b in me["bases"])


async def test_announcements_public_localized_and_filtered(client):
    # SDD 27: anuncios públicos (sin auth), bilingües y filtrables por category/status.
    r = await client.http.get("/api/v1/announcements")
    assert r.status_code == 200, r.text
    items = r.json()
    assert items and all("key" in a and "title" in a and "category" in a for a in items)
    # live primero (orden por status)
    assert items[0]["status"] == "live"
    # EN: el spinoff trae title en inglés + 'differences' (qué cambia vs estándar)
    en = (await client.http.get("/api/v1/announcements?lang=en&category=spinoff")).json()
    assert en and all(a["category"] == "spinoff" for a in en)
    sw = next(a for a in en if a["key"] == "spinoff-star-wars")
    assert sw["title"] == "Universe: Star Wars" and sw["differences"]
    assert "title_en" not in sw   # helper *_en dropped
    # filtro por status
    live = (await client.http.get("/api/v1/announcements?status=live")).json()
    assert live and all(a["status"] == "live" for a in live)
    # SDD 27: los `release` se generan del CHANGELOG (auto), no del yaml
    rel = (await client.http.get("/api/v1/announcements?category=release")).json()
    assert rel and all(a["category"] == "release" for a in rel)
    assert any(a["key"].startswith("release-") for a in rel)   # vienen del changelog


async def test_events_feed_e2e(client):
    # SDD 36: el panel muestra activos + recientes + lo que puede aparecer (nunca vacío).
    h = await _register(client.http, "feeder")
    await _onboard(client.http, h)
    f = (await client.http.get("/api/v1/events/feed", headers=h)).json()
    assert {"active", "recent", "possible"} <= set(f)
    assert any(e["key"] == "happy_hour_build" for e in f["possible"])


async def test_events_admin_start_and_active_e2e(client):
    # SDD 36: admin fuerza un evento → aparece en /events/active; catálogo público lista los tipos.
    h = await _register(client.http, "eventer")
    await _onboard(client.http, h)
    r = await client.http.post("/api/v1/events/start/power_surge", headers=h)
    assert r.status_code == 201, r.text
    act = (await client.http.get("/api/v1/events/active", headers=h)).json()
    assert any(e["key"] == "power_surge" for e in act)
    cat = (await client.http.get("/api/v1/events/catalog")).json()
    assert any(e["key"] == "happy_hour_build" for e in cat)


async def test_solar_storm_blocks_training_allows_building_e2e(client):
    # SDD 72: tormenta solar → no se fabrica nada (unidades/drones/misiles/sats), solo construir;
    # y la energía es infinita (construir no cuesta energía).
    h = await _register(client.http, "stormrider")
    await _onboard(client.http, h, planet="earth", race="terran")
    r = await client.http.post("/api/v1/events/start/solar_storm", headers=h)
    assert r.status_code == 201, r.text
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert me["solar_storm"] is True
    # entrenar cualquier unidad → 400 (electrónica frita)
    t = await client.http.post("/api/v1/bases/1/train", headers=h,
                               json={"unit_key": "soldier", "quantity": 1})
    assert t.status_code == 400
    assert "solar" in t.text.lower() or "tormenta" in t.text.lower()
    # drenar la energía a 0 y construir igual → funciona (energía infinita durante la tormenta)
    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "stormrider"))).scalar_one()
        p.energy = 0.0
        await s.commit()
    b = await client.http.post("/api/v1/bases/1/build", headers=h,
                               json={"building_key": "power_plant"})
    assert b.status_code == 201, b.text   # energía 0 pero la tormenta la hace infinita → construye


async def test_journal_records_and_exports_e2e(client):
    # SDD 38: las acciones quedan en el journal; /journal (propio) + /journal/export (YAML).
    import yaml

    h = await _register(client.http, "journalist")
    await _onboard(client.http, h)
    await client.http.post(
        "/api/v1/bases/1/build", headers=h, json={"building_key": "power_plant"}
    )

    j = await client.http.get("/api/v1/journal", headers=h)
    assert j.status_code == 200, j.text
    types = [e["type"] for e in j.json()]
    assert "onboard" in types  # el onboarding quedó registrado
    assert all(e["seq"] for e in j.json())  # orden total

    exp = await client.http.get("/api/v1/journal/export?format=yaml", headers=h)
    assert exp.status_code == 200
    doc = yaml.safe_load(exp.text)
    assert "events" in doc and isinstance(doc["events"], list) and doc["events"]


async def test_combat_simulate_and_plan_e2e(client):
    # SDD 34: /combat/simulate (determinista) y /combat/plan (estima defensa desde tu intel).
    from datetime import UTC, datetime, timedelta

    from app.models import SpyMission, UnitStock

    ha = await _register(client.http, "calc_a")
    await _onboard(client.http, ha)
    ht = await _register(client.http, "calc_t")
    st = await _onboard(client.http, ht)
    tbase = st["bases"][0]["id"]

    # simulate: 10 tanks (300) vs 5 ships (150) + 80 flat → gana el atacante
    sim = await client.http.post(
        "/api/v1/combat/simulate", headers=ha,
        json={"attacker_force": {"tank": 10}, "defender_force": {"ship": 5},
              "defender_flat_defense": 80},
    )
    assert sim.status_code == 200, sim.text
    assert sim.json()["outcome"] == "attacker"

    # plan sin intel → 400 (espiá primero)
    blind = await client.http.post(
        "/api/v1/combat/plan", headers=ha, json={"target_base_id": tbase}
    )
    assert blind.status_code == 400

    # darle espías + defensa al objetivo, espiar, resolver y planear
    async with client.session_maker() as s:
        a = (await s.execute(select(Player).where(Player.username == "calc_a"))).scalar_one()
        t = (await s.execute(select(Player).where(Player.username == "calc_t"))).scalar_one()
        s.add(UnitStock(player_id=a.id, unit_key="spy", quantity=8))
        s.add(UnitStock(player_id=t.id, unit_key="ship", quantity=4))
        await s.commit()
    await client.http.post(
        "/api/v1/spy", headers=ha, json={"target_base_id": tbase, "spies": {"spy": 8}}
    )
    async with client.session_maker() as s:
        m = (await s.execute(select(SpyMission))).scalars().first()
        m.arrives_at = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()
    await client.http.get("/api/v1/players/me", headers=ha)

    plan = await client.http.post(
        "/api/v1/combat/plan", headers=ha, json={"target_base_id": tbase, "margin": 2}
    )
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["estimated_defense"] > 0 and body["options"]


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


async def test_advisor_model_selector_e2e(client):
    # SDD 9: selector de modelo gpu/cloud/byok. (Sin LLM configurado en tests cae al fallback det.)
    h = await _register(client.http, "modelpicker")
    await _onboard(client.http, h)
    # modo cloud → 200 (responde con tips deterministas si no hay LLM)
    rc = await client.http.post("/api/v1/players/me/advisor/ask", headers=h,
                                json={"message": "qué hago", "model_mode": "cloud"})
    assert rc.status_code == 200, rc.text
    # byok sin key/modelo → 400
    rb = await client.http.post("/api/v1/players/me/advisor/ask", headers=h,
                                json={"message": "qué hago", "model_mode": "byok"})
    assert rb.status_code == 400
    # modo inválido → 422 (validación)
    ri = await client.http.post("/api/v1/players/me/advisor/ask", headers=h,
                                json={"message": "x", "model_mode": "otro"})
    assert ri.status_code == 422


async def test_advisor_hack_grants_and_exhausts_daily_budget(client):
    h = await _register(client.http, "hacker2")
    state = await _onboard(client.http, h)

    # SDD 2: el hack CREA GRATIS. Gastamos los 3 del día en edificios que no piden elegir mineral
    # (mina/silo sí lo piden → 400). Con materiales o sin ellos, crea igual.
    for target in ("power_plant", "barracks", "research_lab"):
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


async def test_advisor_hack_creates_silo_with_default_mineral(client):
    """SDD 2 fix: el hack también crea mina/silo (antes fallaba "elegí mineral"). Sin pasar mineral,
    usa el estructural de la raza; también acepta uno explícito."""
    h = await _register(client.http, "silo_hacker")
    await _onboard(client.http, h, planet="earth", race="terran")
    # sin target_mineral → usa el estructural por default y crea el silo
    r = await client.http.post(
        "/api/v1/players/me/advisor/hack", headers=h, json={"target": "silo"}
    )
    assert r.status_code == 200, r.text
    assert "silo" in r.json()["message"].lower()
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    silos = [bl for b in me["bases"] for bl in b["buildings"] if bl["building_key"] == "silo"]
    assert silos, "el hack debería haber creado un silo"


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


async def test_admin_npc_stats_e2e(client, monkeypatch):
    # Observabilidad NPC: el admin ve un snapshot por NPC (score, acciones, combate). Gated.
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "allowed_emails", "boss@npc.com,plebe@npc.com")
    monkeypatch.setattr(get_settings(), "admin_email", "boss@npc.com")

    # no-admin → 403
    r0 = await client.http.post(
        "/api/v1/auth/register",
        json={"username": "plebe", "password": "secret123", "email": "plebe@npc.com"},
    )
    h = {"Authorization": f"Bearer {r0.json()['access_token']}"}
    assert (await client.http.get("/api/v1/admin/npc-stats", headers=h)).status_code == 403

    # admin → corre un tick (crea + mueve NPCs) y consulta
    r = await client.http.post(
        "/api/v1/auth/register",
        json={"username": "npcboss", "password": "secret123", "email": "boss@npc.com"},
    )
    ah = {"Authorization": f"Bearer {r.json()['access_token']}"}
    await client.http.post("/api/v1/admin/tick", headers=ah)
    res = await client.http.get("/api/v1/admin/npc-stats", headers=ah)
    assert res.status_code == 200, res.text
    stats = res.json()
    assert len(stats) >= 1
    s0 = stats[0]
    assert {"username", "score", "actions", "combat", "recent", "backend", "model",
            "decisions"} <= set(s0)
    assert s0["backend"] in ("gpu", "cloud")
    assert "wins" in s0["combat"] and "battles" in s0["combat"]
    assert {"llm", "fallback", "llm_rate", "fallback_reasons"} <= set(s0["decisions"])


async def test_admin_dashboards_e2e(client, monkeypatch):
    # SDD 19 §9.3: ver Grafana DENTRO del admin. Data-driven: solo devuelve lo configurado.
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "allowed_emails", "boss@gf.com,plebe@gf.com")
    monkeypatch.setattr(get_settings(), "admin_email", "boss@gf.com")

    # no-admin → 403
    r0 = await client.http.post(
        "/api/v1/auth/register",
        json={"username": "plebe_gf", "password": "secret123", "email": "plebe@gf.com"},
    )
    h = {"Authorization": f"Bearer {r0.json()['access_token']}"}
    assert (await client.http.get("/api/v1/admin/dashboards", headers=h)).status_code == 403

    r = await client.http.post(
        "/api/v1/auth/register",
        json={"username": "gfboss", "password": "secret123", "email": "boss@gf.com"},
    )
    ah = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # sin configurar → vacío (el front no muestra nada, sin cambios de UI)
    res = await client.http.get("/api/v1/admin/dashboards", headers=ah)
    assert res.status_code == 200, res.text
    assert res.json() == {}

    # configurado → devuelve la URL del dashboard NPC AI
    url = "https://grafana.example/d/online-game-npc-ai?kiosk"
    monkeypatch.setattr(get_settings(), "grafana_npc_dashboard_url", url)
    res = await client.http.get("/api/v1/admin/dashboards", headers=ah)
    assert res.status_code == 200, res.text
    assert res.json() == {"npc_ai": url}


async def test_admin_approval_flow_e2e(client, monkeypatch):
    # SDD 14: con aprobación activa, el alta nace 'pending' (no juega) hasta que el admin aprueba.
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "admin_email", "boss@ap.com")
    monkeypatch.setattr(get_settings(), "signup_requires_approval", True)

    rn = await client.http.post("/api/v1/auth/register",
        json={"username": "newbie_ap", "password": "secret123", "email": "newbie@ap.com"})
    assert rn.status_code == 201, rn.text
    ntok = {"Authorization": f"Bearer {rn.json()['access_token']}"}
    me = (await client.http.get("/api/v1/players/me", headers=ntok)).json()
    assert me["account_status"] == "pending" and me["is_admin"] is False
    # pending → no puede onboardear (403)
    ob = await client.http.post("/api/v1/players/onboard", headers=ntok,
        json={"galaxy_key": "milky_way", "planet_key": "mars", "race_key": "martian"})
    assert ob.status_code == 403
    # no-admin no puede listar pendientes
    assert (await client.http.get("/api/v1/admin/players", headers=ntok)).status_code == 403

    # admin (email configurado) nace active + is_admin
    ra = await client.http.post("/api/v1/auth/register",
        json={"username": "boss_ap", "password": "secret123", "email": "boss@ap.com"})
    atok = {"Authorization": f"Bearer {ra.json()['access_token']}"}
    ame = (await client.http.get("/api/v1/players/me", headers=atok)).json()
    assert ame["is_admin"] is True and ame["account_status"] == "active"
    pend = (await client.http.get("/api/v1/admin/players?status=pending", headers=atok)).json()
    nid = next(p["id"] for p in pend if p["username"] == "newbie_ap")
    assert (await client.http.post(f"/api/v1/admin/players/{nid}/approve",
                                   headers=atok)).status_code == 200
    # aprobado → ahora sí puede jugar
    me2 = (await client.http.get("/api/v1/players/me", headers=ntok)).json()
    assert me2["account_status"] == "active"
    ob2 = await client.http.post("/api/v1/players/onboard", headers=ntok,
        json={"galaxy_key": "milky_way", "planet_key": "mars", "race_key": "martian"})
    assert ob2.status_code == 201, ob2.text


async def test_admin_account_abm_e2e(client, monkeypatch):
    # SDD 14: ABM — el admin edita (nick/email/status) y borra cuentas, con guardas.
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "admin_email", "boss@abm.com")
    # cuenta a administrar (con typo en el nick, como el caso real)
    await client.http.post("/api/v1/auth/register",
        json={"username": "villadamine_typo", "password": "secret123", "email": "typo@abm.com"})
    ra = await client.http.post("/api/v1/auth/register",
        json={"username": "boss_abm", "password": "secret123", "email": "boss@abm.com"})
    atok = {"Authorization": f"Bearer {ra.json()['access_token']}"}

    players = (await client.http.get("/api/v1/admin/players", headers=atok)).json()
    pid = next(p["id"] for p in players if p["username"] == "villadamine_typo")

    # Modificación: corregir el nick + estado
    ed = await client.http.post(f"/api/v1/admin/players/{pid}/edit", headers=atok,
        json={"username": "villadalmine_fixed", "status": "active"})
    assert ed.status_code == 200 and ed.json()["username"] == "villadalmine_fixed"
    # se puede loguear con el nick corregido
    assert (await client.http.post("/api/v1/auth/login",
        json={"username": "villadalmine_fixed", "password": "secret123"})).status_code == 200

    # guardas: no borrarse a sí mismo, no borrar a otro admin
    bid = next(p["id"] for p in players if p["username"] == "boss_abm")
    no_self = await client.http.delete(f"/api/v1/admin/players/{bid}", headers=atok)
    assert no_self.status_code == 400

    # Baja: borrar la cuenta administrada
    dl = await client.http.delete(f"/api/v1/admin/players/{pid}", headers=atok)
    assert dl.status_code == 200
    after = (await client.http.get("/api/v1/admin/players", headers=atok)).json()
    assert not any(p["id"] == pid for p in after)
    # no-admin no puede usar el ABM
    nn = await client.http.post("/api/v1/auth/register",
        json={"username": "rando_abm", "password": "secret123", "email": "r@abm.com"})
    ntok = {"Authorization": f"Bearer {nn.json()['access_token']}"}
    assert (await client.http.get("/api/v1/admin/players", headers=ntok)).status_code == 403


async def test_login_by_username_or_email(client):
    # SDD 6/14: tras renombrar el nick, podés entrar con el USUARIO o con el EMAIL + tu clave.
    r = await client.http.post("/api/v1/auth/register",
        json={"username": "renamed_user", "password": "secret123", "email": "me@dom.com"})
    assert r.status_code == 201, r.text
    by_user = await client.http.post("/api/v1/auth/login",
        json={"username": "renamed_user", "password": "secret123"})
    assert by_user.status_code == 200
    by_email = await client.http.post("/api/v1/auth/login",
        json={"username": "me@dom.com", "password": "secret123"})
    assert by_email.status_code == 200
    # clave mal → 401
    assert (await client.http.post("/api/v1/auth/login",
        json={"username": "me@dom.com", "password": "nope"})).status_code == 401


async def test_universes_showcase_public(client):
    # SDD 26: vitrina pública de universos spin-off (genérico/homenaje), bilingüe.
    r = await client.http.get("/api/v1/universes")
    assert r.status_code == 200, r.text
    lst = r.json()
    assert lst and any(u["key"] == "colonial_war" for u in lst)
    full = (await client.http.get("/api/v1/universes/colonial_war?lang=en")).json()
    assert full["name"] == "The Colonial War" and full["homage_to"]
    assert full["ships"] and full["worlds"] and full["materials"]
    assert full["ships"][0]["name"] == "Star Battleship"   # localizado EN
    assert "name_en" not in full   # helper *_en dropped
    assert (await client.http.get("/api/v1/universes/nope")).status_code == 404


async def test_admin_reset_password_e2e(client, monkeypatch):
    # SDD 14: el admin resetea la clave → temp de un solo uso → el jugador entra con ella.
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "admin_email", "boss@rp.com")
    # jugador olvidadizo
    await client.http.post("/api/v1/auth/register",
        json={"username": "forgetful", "password": "oldpass123", "email": "f@rp.com"})
    # admin
    ra = await client.http.post("/api/v1/auth/register",
        json={"username": "boss_rp", "password": "secret123", "email": "boss@rp.com"})
    atok = {"Authorization": f"Bearer {ra.json()['access_token']}"}
    pid = next(p["id"] for p in
               (await client.http.get("/api/v1/admin/players", headers=atok)).json()
               if p["username"] == "forgetful")
    rr = await client.http.post(f"/api/v1/admin/players/{pid}/reset-password", headers=atok)
    assert rr.status_code == 200
    temp = rr.json()["temp_password"]
    assert temp
    # la clave vieja ya no anda; la temporal sí
    bad = await client.http.post("/api/v1/auth/login",
        json={"username": "forgetful", "password": "oldpass123"})
    assert bad.status_code == 401
    ok = await client.http.post("/api/v1/auth/login",
        json={"username": "forgetful", "password": temp})
    assert ok.status_code == 200
    # no-admin no puede resetear a otro
    ntok = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert (await client.http.post(f"/api/v1/admin/players/{pid}/reset-password",
                                   headers=ntok)).status_code == 403


async def test_me_is_admin_by_email_without_db_flag(client, monkeypatch):
    # SDD 14: setear ADMIN_EMAIL alcanza para que una cuenta EXISTENTE sea admin (panel + /admin/*),
    # sin tocar la DB. /me refleja is_admin por flag O por coincidencia de email.
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "admin_email", "")   # se registra sin flag admin
    r = await client.http.post("/api/v1/auth/register",
        json={"username": "futureadmin", "password": "secret123", "email": "chief@x.com"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.http.get("/api/v1/players/me", headers=h)).json()["is_admin"] is False
    # ahora ADMIN_EMAIL = su email → reconocido admin sin tocar la base
    monkeypatch.setattr(get_settings(), "admin_email", "chief@x.com")
    assert (await client.http.get("/api/v1/players/me", headers=h)).json()["is_admin"] is True
    assert (await client.http.post("/api/v1/admin/tick", headers=h)).status_code == 200


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


async def test_build_insufficient_energy_message_has_detail(client):
    # El error de energía debe decir cuánto falta y en cuánto se recarga (no solo "insuficiente").
    from datetime import UTC, datetime

    from sqlalchemy import select

    h = await _register(client.http, "drained")
    state = await _onboard(client.http, h)
    base_id = state["bases"][0]["id"]
    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "drained"))).scalar_one()
        p.energy = 0.0
        p.energy_updated_at = datetime.now(UTC)  # sin regen acumulada
        await s.commit()
    r = await client.http.post(
        f"/api/v1/bases/{base_id}/build",
        headers=h,
        json={"building_key": "mine", "target_mineral": "iron"},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "necesitás" in detail
    assert "faltan" in detail


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


async def test_tech_tree_gates_buildings_and_research_e2e(client):
    # SDD 1 (árbol): factory pide research_lab; deep_core_mining pide mining_efficiency.
    from app.models import Building, Player
    h = await _register(client.http, "techtree")
    state = await _onboard(client.http, h)
    bid = state["bases"][0]["id"]

    # factory sin laboratorio → 400
    r = await client.http.post(f"/api/v1/bases/{bid}/build", headers=h,
                               json={"building_key": "factory"})
    assert r.status_code == 400, r.text
    # research encadenada: deep_core_mining sin mining_efficiency → 400
    r2 = await client.http.post("/api/v1/research", headers=h,
                                json={"tech_key": "deep_core_mining"})
    assert r2.status_code == 400

    # con laboratorio activo → factory sale
    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "techtree"))).scalar_one()
        s.add(Building(base_id=bid, building_key="research_lab", status="active"))
        p.energy = 99999.0
        await s.commit()
    ok = await client.http.post(f"/api/v1/bases/{bid}/build", headers=h,
                                json={"building_key": "factory"})
    assert ok.status_code == 201, ok.text


async def test_train_requires_building(client):
    h = await _register(client.http)
    state = await _onboard(client.http, h)
    base_id = state["bases"][0]["id"]
    r = await client.http.post(
        f"/api/v1/bases/{base_id}/train", headers=h, json={"unit_key": "tank", "quantity": 1}
    )
    assert r.status_code == 400  # no factory (SDD 1 árbol de tech)


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


async def test_battles_feed_global_and_admin_no_unit_info(client):
    # Panel general + admin: feed de TODAS las batallas (quién ganó, origen→destino) SIN unidades.
    ha = await _register(client.http, "raider")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hd = await _register(client.http, "victim")
    dstate = await _onboard(client.http, hd, planet="venus", race="venusian")
    target_base = dstate["bases"][0]["id"]
    await _clear_protection(client.session_maker, "raider", "victim")
    await _grant_units(client.session_maker, "raider", {"tank": 5})
    await client.http.post(
        "/api/v1/combat/attack", headers=ha,
        json={"target_base_id": target_base, "force": {"tank": 5}},
    )
    await _fast_forward_arrivals(client.session_maker)
    await client.http.post("/api/v1/admin/tick", headers=ha)

    # Público: lo ve OTRO jugador (la victima), no solo el atacante.
    feed = (await client.http.get("/api/v1/combat/battles", headers=hd)).json()
    assert len(feed) == 1
    b = feed[0]
    assert b["attacker"] == "raider" and b["defender"] == "victim"
    assert b["outcome"] == "attacker"
    assert b["from_planet"] == "mars" and b["to_planet"] == "venus"   # origen → destino
    # SDD 35: NADA de unidades/bajas en el feed (eso es intel que se consigue espiando).
    assert "attacker_losses" not in b and "defender_losses" not in b and "units" not in b

    # Admin: mismo feed (sin gate de ADMIN_EMAIL en tests).
    adm = (await client.http.get("/api/v1/admin/battles", headers=ha)).json()
    assert len(adm) == 1 and adm[0]["winner_id"] is not None
    assert "attacker_losses" not in adm[0]


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


async def test_sse_no_backlog_replay(client):
    # El endpoint usa catch_up=False: al conectar NO re-emite el backlog (si no, el cliente
    # reproducía 30 sonidos y disparaba 30 refresh). El historial lo trae el GET /notifications.
    from app.services.notifications import notify, stream_events

    h = await _register(client.http, "nobacklog")
    state = await _onboard(client.http, h)
    async with client.session_maker() as s:
        for i in range(5):
            await notify(s, state["id"], "old_event", f"vieja {i}", {})
        await s.commit()

    chunks = [
        c async for c in stream_events(
            client.session_maker, state["id"], once=True, catch_up=False
        )
    ]
    assert chunks == [], "el SSE no debe re-emitir el backlog con catch_up=False"


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


async def test_npcs_are_independent_by_default(client, monkeypatch):
    # SDD 29 v2: por default las NPC son INDEPENDIENTES (alliance_id=None) → también se atacan entre
    # sí. Con `npc_shared_alliance` ON vuelven a compartir alianza (cooperan).
    from app.core.config import get_settings
    h = await _register(client.http, "observer")
    await _onboard(client.http, h)
    await client.http.post("/api/v1/admin/tick", headers=h)  # spawnea NPCs (independientes)
    players = (await client.http.get("/api/v1/players", headers=h)).json()
    assert {p["alliance_id"] for p in players if p["is_npc"]} == {None}
    # cada NPC trae su postura (visible en el scoreboard)
    assert all(p.get("posture") for p in players if p["is_npc"])

    # opt-in: si comparten alianza, todas caen en una misma
    monkeypatch.setattr(get_settings(), "npc_shared_alliance", True)
    await client.http.post("/api/v1/admin/tick", headers=h)
    players = (await client.http.get("/api/v1/players", headers=h)).json()
    shared = {p["alliance_id"] for p in players if p["is_npc"]}
    assert None not in shared and len(shared) == 1


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


# ---- SDD 49: misiles -------------------------------------------------------
async def _grant_tech(maker, username, *techs):
    from app.models import PlayerTech
    async with maker() as s:
        p = (await s.execute(select(Player).where(Player.username == username))).scalar_one()
        for t in techs:
            s.add(PlayerTech(player_id=p.id, tech_key=t))
        await s.commit()


async def _set_energy(maker, username, amount):
    async with maker() as s:
        p = (await s.execute(select(Player).where(Player.username == username))).scalar_one()
        p.energy = amount
        await s.commit()


async def _fast_forward_strikes(maker):
    from app.models import StrikeMission
    async with maker() as s:
        for m in (await s.execute(select(StrikeMission))).scalars():
            m.arrives_at = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()


async def test_missile_strike_e2e(client, monkeypatch):
    """SDD 49: con strike_enabled, una salva de sónicos satura las torretas y los que pasan
    destruyen edificios de la base objetivo del MISMO planeta. Caso error: objetivo de otro."""
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "strike_enabled", True)

    # calculadora pura: 50 sónicos vs capacidad 30 → 20 impactan, daño 1200
    ha = await _register(client.http, "shooter")
    await _onboard(client.http, ha, planet="earth", race="terran")
    sim = await client.http.post("/api/v1/combat/strike/simulate", headers=ha,
                                 json={"force": {"sonic_missile": 50}, "intercept_capacity": 30})
    assert sim.status_code == 200
    assert sim.json()["impacted"] == {"sonic_missile": 35}   # 30/2=15 interceptados, 35 impactan
    assert sim.json()["damage"] == 2100

    hd = await _register(client.http, "bunker")
    dstate = await _onboard(client.http, hd, planet="earth", race="terran")
    target_base = dstate["bases"][0]["id"]
    await _clear_protection(client.session_maker, "shooter", "bunker")

    state = (await client.http.get("/api/v1/players/me", headers=ha)).json()
    launcher_base = state["bases"][0]["id"]
    await _grant_tech(client.session_maker, "shooter", "rocketry")
    await _add_active_building(client.session_maker, "shooter", "launcher")
    await _grant_units(client.session_maker, "shooter", {"sonic_missile": 50})
    await _set_energy(client.session_maker, "shooter", 1_000_000)
    await _add_active_building(client.session_maker, "bunker", "turret")  # intercepta + se destruye

    # error: misil a una base de OTRO planeta (montamos un defensor en Marte)
    hm = await _register(client.http, "martian_target")
    mstate = await _onboard(client.http, hm, planet="mars", race="martian")
    bad = await client.http.post("/api/v1/combat/strike", headers=ha, json={
        "launcher_base_id": launcher_base, "target_base_id": mstate["bases"][0]["id"],
        "force": {"sonic_missile": 1}})
    assert bad.status_code == 400 and "planeta" in bad.text.lower()

    # happy path: lanzar la salva intra-planeta
    r = await client.http.post("/api/v1/combat/strike", headers=ha, json={
        "launcher_base_id": launcher_base, "target_base_id": target_base,
        "force": {"sonic_missile": 50}})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "outbound"

    # en vuelo aparece en /players/me
    me = (await client.http.get("/api/v1/players/me", headers=ha)).json()
    assert len(me["strikes"]) == 1

    # resolver la llegada y ver el reporte: destruyó la torreta del rival
    await _fast_forward_strikes(client.session_maker)
    await client.http.post("/api/v1/admin/tick", headers=ha)
    reports = (await client.http.get("/api/v1/combat/reports", headers=ha)).json()
    assert reports[0]["outcome"] == "strike"
    assert "turret" in reports[0]["details"]["destroyed"]


async def test_strike_blocked_without_tech_e2e(client, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "strike_enabled", True)
    ha = await _register(client.http, "wannabe")
    state = await _onboard(client.http, ha, planet="earth", race="terran")
    hd = await _register(client.http, "victim2")
    dstate = await _onboard(client.http, hd, planet="earth", race="terran")
    await _clear_protection(client.session_maker, "wannabe", "victim2")
    await _add_active_building(client.session_maker, "wannabe", "launcher")
    await _grant_units(client.session_maker, "wannabe", {"sonic_missile": 1})
    await _set_energy(client.session_maker, "wannabe", 1_000_000)
    r = await client.http.post("/api/v1/combat/strike", headers=ha, json={
        "launcher_base_id": state["bases"][0]["id"],
        "target_base_id": dstate["bases"][0]["id"], "force": {"sonic_missile": 1}})
    assert r.status_code == 400 and "investigar" in r.text.lower()


# ---- SDD 50: drones --------------------------------------------------------
async def test_drone_squadron_e2e(client, monkeypatch):
    """SDD 50: con drones_enabled, lanzar un escuadrón espía intra-planeta da intel en vivo;
    retirarlo devuelve los sobrevivientes. Caso error: objetivo de otro planeta."""
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "drones_enabled", True)

    ho = await _register(client.http, "pilot")
    ostate = await _onboard(client.http, ho, planet="earth", race="terran")
    factory_base = ostate["bases"][0]["id"]
    ht = await _register(client.http, "watched")
    tstate = await _onboard(client.http, ht, planet="earth", race="terran")
    target_base = tstate["bases"][0]["id"]
    await _clear_protection(client.session_maker, "pilot", "watched")

    await _grant_tech(client.session_maker, "pilot", "dronework")
    await _add_active_building(client.session_maker, "pilot", "drone_factory")
    await _grant_units(client.session_maker, "pilot", {"recon_drone": 3})
    await _set_energy(client.session_maker, "pilot", 1_000_000)

    # calculadora pura
    sim = await client.http.post("/api/v1/drones/simulate", headers=ho, json={
        "force": {"recon_drone": 3}, "antiair": 20, "energy": 1000, "regen_per_tick": 1000})
    assert sim.status_code == 200 and sim.json()["intel_quality"] == 0.6

    # error: dron a otro planeta
    hm = await _register(client.http, "mars_guy")
    mstate = await _onboard(client.http, hm, planet="mars", race="martian")
    bad = await client.http.post("/api/v1/drones/launch", headers=ho, json={
        "factory_base_id": factory_base, "target_base_id": mstate["bases"][0]["id"],
        "force": {"recon_drone": 1}})
    assert bad.status_code == 400 and "planeta" in bad.text.lower()

    # lanzar escuadrón intra-planeta → intel en vivo en /players/me
    r = await client.http.post("/api/v1/drones/launch", headers=ho, json={
        "factory_base_id": factory_base, "target_base_id": target_base,
        "force": {"recon_drone": 3}})
    assert r.status_code == 201, r.text
    squad_id = r.json()["id"]
    me = (await client.http.get("/api/v1/players/me", headers=ho)).json()
    assert len(me["drones"]) == 1 and me["drones"][0]["intel_quality"] == 0.6
    assert str(target_base) in me["intel_live"]

    # retirar: los 3 drones vuelven al stock
    rc = await client.http.post(f"/api/v1/drones/{squad_id}/recall", headers=ho)
    assert rc.status_code == 200 and rc.json()["status"] == "recalled"
    me = (await client.http.get("/api/v1/players/me", headers=ho)).json()
    assert me["units"].get("recon_drone", 0) == 3
    assert me["drones"] == []


async def test_drones_die_without_energy_e2e(client, monkeypatch):
    """SDD 50: si el drenaje supera tu energía, el escuadrón muere al avanzar (lazy timestamp)."""
    from app.core.config import get_settings
    from app.models import DroneSquadron
    monkeypatch.setattr(get_settings(), "drones_enabled", True)

    ho = await _register(client.http, "lowfuel")
    ostate = await _onboard(client.http, ho, planet="earth", race="terran")
    ht = await _register(client.http, "watched2")
    tstate = await _onboard(client.http, ht, planet="earth", race="terran")
    await _clear_protection(client.session_maker, "lowfuel", "watched2")
    await _grant_tech(client.session_maker, "lowfuel", "dronework", "drone_endurance")
    await _add_active_building(client.session_maker, "lowfuel", "drone_factory")
    await _grant_units(client.session_maker, "lowfuel", {"recon_drone_mk3": 5})
    await _set_energy(client.session_maker, "lowfuel", 1_000_000)

    r = await client.http.post("/api/v1/drones/launch", headers=ho, json={
        "factory_base_id": ostate["bases"][0]["id"],
        "target_base_id": tstate["bases"][0]["id"], "force": {"recon_drone_mk3": 5}})
    assert r.status_code == 201, r.text

    # poca energía + el reloj del escuadrón 2 ticks atrás → drenaje (5×4=20/tick) la agota → muere
    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "lowfuel"))).scalar_one()
        p.energy = 8
        tick_s = get_settings().drone_tick_seconds
        sq = (await s.execute(select(DroneSquadron).where(
            DroneSquadron.owner_id == p.id))).scalar_one()
        sq.last_tick_at = datetime.now(UTC) - timedelta(seconds=tick_s * 2 + 5)
        await s.commit()

    me = (await client.http.get("/api/v1/players/me", headers=ho)).json()
    assert me["drones"] == []      # el escuadrón murió por falta de energía


async def test_player_history_analytics_e2e(client, monkeypatch):
    """SDD 51: el estado se muestrea en advance; /players/me/history devuelve serie + eventos."""
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "analytics_sample_seconds", 0)  # muestrear en cada lectura
    h = await _register(client.http, "historian")
    await _onboard(client.http, h, planet="earth", race="terran")
    await client.http.get("/api/v1/players/me", headers=h)   # genera muestras del estado
    await client.http.get("/api/v1/players/me", headers=h)

    r = await client.http.get("/api/v1/players/me/history?hours=24", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["samples"]) >= 1
    assert "energy" in data["samples"][0] and "score" in data["samples"][0]
    assert isinstance(data["events"], dict)
    # SDD 71: bloques nuevos de combate y uso de IA (per-jugador) para los gráficos in-app.
    c = data["combat"]
    assert {"atk_won", "atk_lost", "def_won", "def_lost", "series"} <= set(c)
    assert isinstance(c["series"], list)
    L = data["llm"]
    assert {"total", "by_mode", "series"} <= set(L)


async def test_attack_rate_limit_per_window_e2e(client, monkeypatch):
    """Límite de ataques por ventana: tras N ataques en la ventana, el siguiente da 400."""
    from app.core.config import get_settings
    # Aislar el límite POR VENTANA: apagamos los topes por-objetivo/entrante (SDD 55, probados
    # aparte); sino el 3º ataque al mismo rival lo bloquearían ellos antes que la ventana.
    monkeypatch.setattr(get_settings(), "attacks_per_target_per_day", 0)
    monkeypatch.setattr(get_settings(), "max_incoming_attacks_per_day", 0)
    ha = await _register(client.http, "raider_lim")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hd = await _register(client.http, "victim_lim")
    dstate = await _onboard(client.http, hd, planet="venus", race="venusian")
    target = dstate["bases"][0]["id"]
    await _clear_protection(client.session_maker, "raider_lim", "victim_lim")
    await _grant_units(client.session_maker, "raider_lim", {"soldier": 10})
    await _set_energy(client.session_maker, "raider_lim", 1_000_000)

    ok = 0
    for _ in range(3):
        r = await client.http.post("/api/v1/combat/attack", headers=ha,
                                   json={"target_base_id": target, "force": {"soldier": 1}})
        if r.status_code == 201:
            ok += 1
    assert ok == 3
    # el 4º en la ventana → rechazado por límite
    r = await client.http.post("/api/v1/combat/attack", headers=ha,
                               json={"target_base_id": target, "force": {"soldier": 1}})
    assert r.status_code == 400 and "límite" in r.text.lower()


async def test_attack_per_target_daily_cap_e2e(client, monkeypatch):
    """SDD 55: no podés farmear al MISMO rival — tope por par (atacante, defensor) por día."""
    from app.core.config import get_settings
    # Aislamos el tope por-objetivo: ventana y entrante holgados.
    monkeypatch.setattr(get_settings(), "attacks_per_window", 0)
    monkeypatch.setattr(get_settings(), "max_incoming_attacks_per_day", 0)
    monkeypatch.setattr(get_settings(), "attacks_per_target_per_day", 2)
    ha = await _register(client.http, "farmer")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hd = await _register(client.http, "farmed")
    dstate = await _onboard(client.http, hd, planet="venus", race="venusian")
    target = dstate["bases"][0]["id"]
    await _clear_protection(client.session_maker, "farmer", "farmed")
    await _grant_units(client.session_maker, "farmer", {"soldier": 10})
    await _set_energy(client.session_maker, "farmer", 1_000_000)

    codes = []
    for _ in range(3):
        r = await client.http.post("/api/v1/combat/attack", headers=ha,
                                   json={"target_base_id": target, "force": {"soldier": 1}})
        codes.append(r.status_code)
    assert codes[:2] == [201, 201]                      # 2 ataques al mismo rival OK
    assert codes[2] == 400                              # el 3º al MISMO rival → bloqueado
    r = await client.http.post("/api/v1/combat/attack", headers=ha,
                               json={"target_base_id": target, "force": {"soldier": 1}})
    assert "objetivo" in r.text.lower() or "abuso" in r.text.lower()


async def test_attack_incoming_daily_cap_e2e(client, monkeypatch):
    """SDD 55: un defensor no recibe infinitos ataques por día (puede reconstruir)."""
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "attacks_per_window", 0)
    monkeypatch.setattr(get_settings(), "attacks_per_target_per_day", 0)
    monkeypatch.setattr(get_settings(), "max_incoming_attacks_per_day", 3)
    ha = await _register(client.http, "sieger")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hd = await _register(client.http, "besieged")
    dstate = await _onboard(client.http, hd, planet="venus", race="venusian")
    target = dstate["bases"][0]["id"]
    await _clear_protection(client.session_maker, "sieger", "besieged")
    await _grant_units(client.session_maker, "sieger", {"soldier": 10})
    await _set_energy(client.session_maker, "sieger", 1_000_000)

    ok = 0
    for _ in range(3):
        r = await client.http.post("/api/v1/combat/attack", headers=ha,
                                   json={"target_base_id": target, "force": {"soldier": 1}})
        if r.status_code == 201:
            ok += 1
    assert ok == 3
    # el 4º entrante al mismo defensor → bloqueado (ya fue muy golpeado hoy)
    r = await client.http.post("/api/v1/combat/attack", headers=ha,
                               json={"target_base_id": target, "force": {"soldier": 1}})
    assert r.status_code == 400 and ("golpeado" in r.text.lower() or "abuso" in r.text.lower())


async def test_attacks_received_today_exposed_e2e(client, monkeypatch):
    """SDD 55 §3.3: el snapshot expone ataques recibidos hoy + tope, para el contador del front."""
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "attacks_per_window", 0)
    monkeypatch.setattr(get_settings(), "attacks_per_target_per_day", 0)
    monkeypatch.setattr(get_settings(), "max_incoming_attacks_per_day", 6)
    ha = await _register(client.http, "counter_atk")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hd = await _register(client.http, "counter_def")
    dstate = await _onboard(client.http, hd, planet="venus", race="venusian")
    target = dstate["bases"][0]["id"]
    # antes del ataque: cero recibidos, tope visible
    me0 = (await client.http.get("/api/v1/players/me", headers=hd)).json()
    assert me0["attacks_received_today"] == 0
    assert me0["max_incoming_attacks_per_day"] == 6
    await _clear_protection(client.session_maker, "counter_atk", "counter_def")
    await _grant_units(client.session_maker, "counter_atk", {"soldier": 5})
    await _set_energy(client.session_maker, "counter_atk", 1_000_000)
    r = await client.http.post("/api/v1/combat/attack", headers=ha,
                               json={"target_base_id": target, "force": {"soldier": 1}})
    assert r.status_code == 201, r.text
    me1 = (await client.http.get("/api/v1/players/me", headers=hd)).json()
    assert me1["attacks_received_today"] >= 1


async def test_garrison_combat_uses_only_attacked_base_e2e(client, monkeypatch):
    """SDD 62: con guarnición ON, el combate usa SOLO la guarnición de la base atacada y la flota
    sale de una base; las unidades en otra base / pool global no defienden ni atacan."""
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "garrison_enabled", True)
    monkeypatch.setattr(get_settings(), "attacks_per_window", 0)
    ha = await _register(client.http, "gar_atk")
    ast = await _onboard(client.http, ha, planet="mars", race="martian")
    a_base = ast["bases"][0]["id"]
    hd = await _register(client.http, "gar_def")
    dst = await _onboard(client.http, hd, planet="venus", race="venusian")
    d_base = dst["bases"][0]["id"]
    await _clear_protection(client.session_maker, "gar_atk", "gar_def")
    await _set_energy(client.session_maker, "gar_atk", 1_000_000)
    # atacante: tropas EN su base natal; defensor: 50 soldados en el POOL GLOBAL (no en su base).
    await _grant_units(client.session_maker, "gar_atk", {"tank": 10}, base_id=a_base)
    await _grant_units(client.session_maker, "gar_def", {"soldier": 50})  # global, NO en d_base

    # el snapshot muestra la guarnición por base
    me = (await client.http.get("/api/v1/players/me", headers=ha)).json()
    assert me["units_by_base"].get(str(a_base), {}).get("tank") == 10

    # atacar SIN tropas en la base de origen falla (prueba que lee por base)
    rbad = await client.http.post("/api/v1/combat/attack", headers=hd,
                                  json={"target_base_id": a_base, "force": {"soldier": 1}})
    assert rbad.status_code == 400  # el defensor tiene soldados globales, pero no en su base

    # atacar desde la base con guarnición funciona
    r = await client.http.post("/api/v1/combat/attack", headers=ha,
                               json={"target_base_id": d_base, "force": {"tank": 10},
                                     "source_base_id": a_base})
    assert r.status_code == 201, r.text
    await _fast_forward_arrivals(client.session_maker)
    await client.http.post("/api/v1/admin/tick", headers=ha)
    reports = (await client.http.get("/api/v1/combat/reports", headers=ha)).json()
    # los 50 soldados del defensor estaban globales (no en d_base) → base indefensa → gana atk
    assert reports and reports[0]["outcome"] == "attacker"


async def test_space_jump_instant_move_e2e(client, monkeypatch):
    """SDD 63: con jumper + tech space_jump, mover tropas por la API es instantáneo."""
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.models import Base_, PlayerTech, UnitStock
    monkeypatch.setattr(get_settings(), "garrison_enabled", True)
    monkeypatch.setattr(get_settings(), "space_jump_enabled", True)
    h = await _register(client.http, "jumper_e2e")
    st = await _onboard(client.http, h, planet="mars", race="martian")
    natal = st["bases"][0]["id"]
    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "jumper_e2e"))).scalar_one()
        colony = Base_(player_id=p.id, name="Col", planet_key="venus", base_type="surface")
        s.add(colony)
        await s.flush()
        s.add(UnitStock(player_id=p.id, unit_key="tank", quantity=3, base_id=natal))
        s.add(UnitStock(player_id=p.id, unit_key="jumper", quantity=1, base_id=natal))
        s.add(PlayerTech(player_id=p.id, tech_key="space_jump"))
        cid = colony.id
        await s.commit()
    r = await client.http.post(f"/api/v1/bases/{natal}/move-troops", headers=h,
                               json={"to_base_id": cid, "units": {"tank": 1}})
    assert r.status_code == 201, r.text
    from datetime import datetime
    arrives = datetime.fromisoformat(r.json()["arrives_at"].replace("Z", "+00:00"))
    assert (arrives - datetime.now(arrives.tzinfo)).total_seconds() <= 2  # instantáneo


async def test_bunker_dig_and_build_room_e2e(client, monkeypatch):
    """SDD 64: cavar el búnker y construir una habitación por la API (+ error sin la tech)."""
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.models import PlayerTech
    monkeypatch.setattr(get_settings(), "bunkers_enabled", True)
    h = await _register(client.http, "bunker_e2e")
    st = await _onboard(client.http, h, planet="mars", race="martian")
    base = st["bases"][0]["id"]
    # sin la tech → 400
    r0 = await client.http.post("/api/v1/bunker/dig", headers=h, json={"base_id": base})
    assert r0.status_code == 400
    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "bunker_e2e"))).scalar_one()
        s.add(PlayerTech(player_id=p.id, tech_key="bunker_engineering"))
        await s.commit()
    r = await client.http.post("/api/v1/bunker/dig", headers=h, json={"base_id": base})
    assert r.status_code == 201, r.text
    rr = await client.http.post("/api/v1/bunker/build-room", headers=h,
                                json={"base_id": base, "room_key": "farm", "cell": 0})
    assert rr.status_code == 201, rr.text
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert me["bunkers"] and me["bunkers"][0]["food_health"] == 100.0


async def test_bunker_dig_deeper_e2e(client, monkeypatch):
    """SDD 69 Fase 1: excavar agranda la grilla del búnker (+1 lado) por la API."""
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.models import PlayerTech
    from app.services.economy import get_or_create_stock
    s = get_settings()
    monkeypatch.setattr(s, "bunkers_enabled", True)
    monkeypatch.setattr(s, "bunker_expansion_enabled", True)
    h = await _register(client.http, "digdeep_e2e")
    st = await _onboard(client.http, h, planet="mars", race="martian")
    base = st["bases"][0]["id"]
    async with client.session_maker() as ses:
        p = (await ses.execute(select(Player).where(Player.username == "digdeep_e2e"))).scalar_one()
        ses.add(PlayerTech(player_id=p.id, tech_key="bunker_engineering"))
        ses.add(PlayerTech(player_id=p.id, tech_key="underground_construction"))
        await ses.commit()
    assert (await client.http.post("/api/v1/bunker/dig", headers=h,
                                   json={"base_id": base})).status_code == 201
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    side0 = me["bunkers"][0]["side"]
    # fondear estructural para pagar la excavación
    from app.content.registry import get_content
    struct = get_content().resolve_role("martian", "structural")
    async with client.session_maker() as ses:
        p = (await ses.execute(select(Player).where(Player.username == "digdeep_e2e"))).scalar_one()
        (await get_or_create_stock(ses, p.id, struct, "mars")).amount = 100000
        await ses.commit()
    r = await client.http.post("/api/v1/bunker/dig-deeper", headers=h, json={"base_id": base})
    assert r.status_code == 201, r.text
    me2 = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert me2["bunkers"][0]["side"] == side0 + 1
    assert me2["bunkers"][0]["grid_level"] == 1


async def test_bunker_vault_stash_withdraw_e2e(client, monkeypatch):
    """SDD 69 Fase 1: guardar mineral en la bóveda (a salvo del saqueo) y sacarlo, por la API."""
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.models import Bunker, BunkerRoom, PlayerTech
    from app.services.economy import get_or_create_stock
    monkeypatch.setattr(get_settings(), "bunkers_enabled", True)
    h = await _register(client.http, "vault_e2e")
    st = await _onboard(client.http, h, planet="mars", race="martian")
    base = st["bases"][0]["id"]
    async with client.session_maker() as ses:
        p = (await ses.execute(select(Player).where(Player.username == "vault_e2e"))).scalar_one()
        ses.add(PlayerTech(player_id=p.id, tech_key="bunker_engineering"))
        await ses.commit()
    assert (await client.http.post("/api/v1/bunker/dig", headers=h,
                                   json={"base_id": base})).status_code == 201
    # construir la bóveda y activarla + fondear iron
    assert (await client.http.post("/api/v1/bunker/build-room", headers=h,
            json={"base_id": base, "room_key": "vault", "cell": 0})).status_code == 201
    async with client.session_maker() as ses:
        p = (await ses.execute(select(Player).where(Player.username == "vault_e2e"))).scalar_one()
        b = (await ses.execute(select(Bunker).where(Bunker.base_id == base))).scalar_one()
        room = (await ses.execute(
            select(BunkerRoom).where(BunkerRoom.bunker_id == b.id))).scalars().first()
        room.status = "active"
        (await get_or_create_stock(ses, p.id, "iron", "mars")).amount = 100000
        await ses.commit()
    r = await client.http.post("/api/v1/bunker/stash", headers=h,
                               json={"base_id": base, "mineral": "iron", "amount": 1000})
    assert r.status_code == 201, r.text
    assert r.json()["stashed"] == 1000
    me = (await client.http.get("/api/v1/players/me", headers=h)).json()
    assert me["bunkers"][0]["vault"].get("iron") == 1000
    w = await client.http.post("/api/v1/bunker/withdraw", headers=h,
                               json={"base_id": base, "mineral": "iron", "amount": 400})
    assert w.status_code == 201 and w.json()["withdrawn"] == 400


async def test_bunker_raid_e2e(client, monkeypatch):
    """SDD 64: sabotear el búnker de un rival mapeado por la API (happy) + 400 sin intel."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.core.config import get_settings
    from app.models import Bunker, PlayerTech, SatelliteMission
    monkeypatch.setattr(get_settings(), "bunkers_enabled", True)
    monkeypatch.setattr(get_settings(), "satellites_enabled", True)
    ha = await _register(client.http, "bk_raider")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hd = await _register(client.http, "bk_victim")
    dstate = await _onboard(client.http, hd, planet="venus", race="venusian")
    await _clear_protection(client.session_maker, "bk_raider", "bk_victim")
    await _set_energy(client.session_maker, "bk_raider", 1_000_000)
    now = datetime.now(UTC)
    async with client.session_maker() as s:
        atk = (await s.execute(select(Player).where(Player.username == "bk_raider"))).scalar_one()
        tgt = (await s.execute(select(Player).where(Player.username == "bk_victim"))).scalar_one()
        s.add(PlayerTech(player_id=tgt.id, tech_key="bunker_engineering"))
        s.add(Bunker(player_id=tgt.id, base_id=dstate["bases"][0]["id"], food_health=100,
                     water_health=100, people_health=100, updated_at=now, created_at=now))
        tid = tgt.id
        await s.commit()
    # sin intel → 400
    r0 = await client.http.post("/api/v1/bunker/raid", headers=ha,
                                json={"target_id": tid, "action": "gas"})
    assert r0.status_code == 400 and "mapear" in r0.text.lower()
    # con el rival mapeado por satélites → sabotaje aplicado
    async with client.session_maker() as s:
        s.add(SatelliteMission(owner_id=atk.id, target_id=tid, unit_key="spy_satellite",
                               kind="spy", target_planet="venus", shield_grade=0, energy=100,
                               discovered_pct=80, status="orbiting",
                               last_tick_at=now, created_at=now))
        await s.commit()
    r = await client.http.post("/api/v1/bunker/raid", headers=ha,
                               json={"target_id": tid, "action": "gas"})
    assert r.status_code == 201, r.text
    assert r.json()["people"] < 100
    # el defensor ve sus medidores golpeados en el snapshot
    me = (await client.http.get("/api/v1/players/me", headers=hd)).json()
    assert me["bunkers"][0]["people_health"] < 100


async def test_satellite_launch_and_intel_e2e(client, monkeypatch):
    """SDD 61: lanzar un satélite espía y verlo en el intel (happy path + error con flag OFF)."""
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "satellites_enabled", True)
    ha = await _register(client.http, "sat_e2e_atk")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hd = await _register(client.http, "sat_e2e_def")
    dstate = await _onboard(client.http, hd, planet="venus", race="venusian")
    await _grant_units(client.session_maker, "sat_e2e_atk", {"spy_satellite": 1})
    r = await client.http.post("/api/v1/satellites/launch", headers=ha,
                               json={"unit_key": "spy_satellite", "target_id": dstate["id"]})
    assert r.status_code == 201, r.text
    intel = (await client.http.get("/api/v1/satellites/intel", headers=ha)).json()
    assert any(s["kind"] == "spy" for s in intel["satellites"])
    # error: espía sin objetivo
    await _grant_units(client.session_maker, "sat_e2e_atk", {"spy_satellite": 1})
    r2 = await client.http.post("/api/v1/satellites/launch", headers=ha,
                                json={"unit_key": "spy_satellite"})
    assert r2.status_code == 400


async def test_move_troops_e2e(client, monkeypatch):
    """SDD 62: mover tropas entre bases propias por la API (happy path + error de misma base)."""
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.models import Base_, UnitStock
    monkeypatch.setattr(get_settings(), "garrison_enabled", True)
    h = await _register(client.http, "mover_e2e")
    st = await _onboard(client.http, h, planet="mars", race="martian")
    natal = st["bases"][0]["id"]
    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "mover_e2e"))).scalar_one()
        colony = Base_(player_id=p.id, name="Col", planet_key="venus", base_type="surface")
        s.add(colony)
        await s.flush()
        s.add(UnitStock(player_id=p.id, unit_key="tank", quantity=5, base_id=natal))
        cid = colony.id
        await s.commit()
    r = await client.http.post(f"/api/v1/bases/{natal}/move-troops", headers=h,
                               json={"to_base_id": cid, "units": {"tank": 3}})
    assert r.status_code == 201, r.text
    assert r.json()["to_base_id"] == cid
    # error: mover a la misma base
    r2 = await client.http.post(f"/api/v1/bases/{natal}/move-troops", headers=h,
                                json={"to_base_id": natal, "units": {"tank": 1}})
    assert r2.status_code == 400


async def test_worker_floor_survives_combat_e2e(client):
    """SDD 54: tras un ataque arrasador, al defensor SIEMPRE le quedan ≥ min_surviving_workers
    trabajadores → puede seguir juntando material (no queda trabado)."""
    ha = await _register(client.http, "crusher")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hd = await _register(client.http, "stuck")
    dstate = await _onboard(client.http, hd, planet="venus", race="venusian")
    target = dstate["bases"][0]["id"]
    await _clear_protection(client.session_maker, "crusher", "stuck")
    await _grant_units(client.session_maker, "crusher", {"tank": 20})   # fuerza aplastante
    await _grant_units(client.session_maker, "stuck", {"worker": 5})    # solo obreros, sin defensa
    await _set_energy(client.session_maker, "crusher", 1_000_000)

    r = await client.http.post("/api/v1/combat/attack", headers=ha,
                               json={"target_base_id": target, "force": {"tank": 20}})
    assert r.status_code == 201, r.text
    await _fast_forward_arrivals(client.session_maker)
    await client.http.post("/api/v1/admin/tick", headers=ha)
    reports = (await client.http.get("/api/v1/combat/reports", headers=ha)).json()
    assert reports and reports[0]["outcome"] == "attacker"
    # el defensor perdió la batalla pero conserva el piso de obreros
    dme = (await client.http.get("/api/v1/players/me", headers=hd)).json()
    assert dme["units"].get("worker", 0) >= 2


async def test_turret_counts_as_defense_e2e(client):
    """SDD 54: una torreta ACTIVA en la base atacada cuenta como defensa (reproduce el reporte)."""
    from sqlalchemy import select

    from app.models import Building
    ha = await _register(client.http, "atk_turret")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hd = await _register(client.http, "def_turret")
    dstate = await _onboard(client.http, hd, planet="venus", race="venusian")
    target = dstate["bases"][0]["id"]
    await _clear_protection(client.session_maker, "atk_turret", "def_turret")
    await _grant_units(client.session_maker, "atk_turret", {"soldier": 3})
    await _set_energy(client.session_maker, "atk_turret", 1_000_000)
    # Plantamos una torreta ACTIVA en la base atacada (defense_power fijo).
    async with client.session_maker() as s:
        s.add(Building(base_id=target, building_key="turret", status="active"))
        await s.commit()
        cnt = (await s.execute(select(Building).where(
            Building.base_id == target, Building.building_key == "turret",
            Building.status == "active"))).scalars().all()
        assert len(cnt) == 1

    r = await client.http.post("/api/v1/combat/attack", headers=ha,
                               json={"target_base_id": target, "force": {"soldier": 3}})
    assert r.status_code == 201, r.text
    await _fast_forward_arrivals(client.session_maker)
    await client.http.post("/api/v1/admin/tick", headers=ha)
    reports = (await client.http.get("/api/v1/combat/reports", headers=ha)).json()
    assert reports, "debería haber un reporte de combate"
    det = reports[0].get("details", reports[0])
    # 3 soldados (ataque 24) NO superan la defensa fija de la torreta → la torreta defendió.
    assert reports[0]["outcome"] == "defender", det


async def test_base_defense_detectable_for_no_defense_warning_e2e(client):
    """SDD 54 (UX): el front avisa "esta base no tiene defensas". Necesita (a) el catálogo con
    `defense_power` por edificio y (b) los edificios de cada base → acá verificamos ambos datos."""
    cat = (await client.http.get("/api/v1/catalog")).json()
    turret = next(b for b in cat["buildings"] if b["key"] == "turret")
    assert turret.get("defense_power", 0) > 0     # la torreta es defensiva (el front la detecta)
    h = await _register(client.http, "no_def_base")
    st = await _onboard(client.http, h, planet="earth", race="terran")
    base = st["bases"][0]
    defmap = {b["key"]: b.get("defense_power", 0) for b in cat["buildings"]}
    # una base recién creada (solo HQ) no tiene ningún edificio defensivo activo → el front avisa
    has_def = any(bl["status"] == "active" and defmap.get(bl["building_key"], 0) > 0
                  for bl in base["buildings"])
    assert not has_def


async def test_hyperspace_speeds_up_space_fleet_e2e(client):
    """SDD 57 v2: una flota con naves espaciales y la tech `hyperspace_travel` llega más rápido."""
    from sqlalchemy import select

    from app.models import AttackMission, PlayerTech
    ha = await _register(client.http, "jumper")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hd = await _register(client.http, "jdef")
    dstate = await _onboard(client.http, hd, planet="venus", race="venusian")  # cross-planet
    target = dstate["bases"][0]["id"]
    await _clear_protection(client.session_maker, "jumper", "jdef")
    await _grant_units(client.session_maker, "jumper", {"shuttle": 2})
    await _set_energy(client.session_maker, "jumper", 1_000_000)

    # 1) sin tech: viaje normal
    r1 = await client.http.post("/api/v1/combat/attack", headers=ha,
                                json={"target_base_id": target, "force": {"shuttle": 1}})
    assert r1.status_code == 201, r1.text
    # 2) con hyperspace_travel investigado: salto más rápido
    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "jumper"))).scalar_one()
        s.add(PlayerTech(player_id=p.id, tech_key="hyperspace_travel"))
        await s.commit()
        pid = p.id
    r2 = await client.http.post("/api/v1/combat/attack", headers=ha,
                                json={"target_base_id": target, "force": {"shuttle": 1}})
    assert r2.status_code == 201, r2.text
    async with client.session_maker() as s:
        ms = (await s.execute(select(AttackMission).where(
            AttackMission.attacker_id == pid).order_by(AttackMission.id))).scalars().all()
    d_normal = (ms[0].arrives_at - ms[0].created_at).total_seconds()
    d_hyper = (ms[1].arrives_at - ms[1].created_at).total_seconds()
    assert d_hyper < d_normal, (d_hyper, d_normal)


async def test_dreadnought_razes_surplus_buildings_e2e(client):
    """SDD 57: el acorazado (siege_power) al ganar demuele edificios EXCEDENTES de la base — nunca
    el HQ ni el último de su tipo (anti-lockout)."""
    from sqlalchemy import select

    from app.models import Base_, Building
    ha = await _register(client.http, "razer")
    await _onboard(client.http, ha, planet="mars", race="martian")
    hd = await _register(client.http, "razed_def")
    dstate = await _onboard(client.http, hd, planet="venus", race="venusian")
    target = dstate["bases"][0]["id"]
    await _clear_protection(client.session_maker, "razer", "razed_def")
    await _grant_units(client.session_maker, "razer", {"dreadnought": 1})
    await _set_energy(client.session_maker, "razer", 1_000_000)
    # defensor: 2 cuarteles activos (excedente) sin defensa → el acorazado gana y bombardea
    async with client.session_maker() as s:
        for _ in range(2):
            s.add(Building(base_id=target, building_key="barracks", status="active"))
        await s.commit()

    r = await client.http.post("/api/v1/combat/attack", headers=ha,
                               json={"target_base_id": target, "force": {"dreadnought": 1}})
    assert r.status_code == 201, r.text
    await _fast_forward_arrivals(client.session_maker)
    await client.http.post("/api/v1/admin/tick", headers=ha)
    reports = (await client.http.get("/api/v1/combat/reports", headers=ha)).json()
    assert reports and reports[0]["outcome"] == "attacker", reports
    assert reports[0]["details"].get("razed"), reports[0]["details"]
    # quedó 1 cuartel (solo se voló el excedente) y el HQ intacto
    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "razed_def"))).scalar_one()
        keys = [b.building_key for b in (await s.execute(
            select(Building).join(Base_, Building.base_id == Base_.id)
            .where(Base_.player_id == p.id))).scalars()]
    assert keys.count("barracks") == 1            # de 2 → 1 (solo el excedente)
    assert "headquarters" in keys                 # el HQ nunca se destruye


async def test_building_repair_demolish_upgrade_e2e(client, monkeypatch):
    """SDD 66: reparar (averiada→sana), demoler (salvage), mejorar (sube nivel). Flag ON."""
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.models import Building, PlayerTech
    monkeypatch.setattr(get_settings(), "building_condition_enabled", True)
    h = await _register(client.http, "bld_ops")
    st = await _onboard(client.http, h, planet="mars", race="martian")
    base = st["bases"][0]["id"]
    async with client.session_maker() as s:
        p = (await s.execute(select(Player).where(Player.username == "bld_ops"))).scalar_one()
        s.add(PlayerTech(player_id=p.id, tech_key="weapons"))
        # torreta activa averiada + una segunda para demoler
        t = Building(base_id=base, building_key="turret", status="active", condition=40.0)
        s.add(t)
        s.add(Building(base_id=base, building_key="turret", status="active", condition=100.0))
        await s.flush()
        tid = t.id
        # recursos para pagar
        from app.services.economy import get_or_create_stock
        for m in ("iron", "sulfur", "magnesium"):
            (await get_or_create_stock(s, p.id, m, p.planet_key)).amount = 100000
        p.energy = 100000
        await s.commit()
    # reparar
    r = await client.http.post(f"/api/v1/bases/buildings/{tid}/repair", headers=h)
    assert r.status_code == 200 and r.json()["condition"] == 100.0, r.text
    # mejorar defensa → nivel 2
    r2 = await client.http.post(f"/api/v1/bases/buildings/{tid}/upgrade?kind=defense", headers=h)
    assert r2.status_code == 200 and r2.json()["level"] == 2, r2.text
    # demoler
    r3 = await client.http.post(f"/api/v1/bases/buildings/{tid}/demolish", headers=h)
    assert r3.status_code == 200 and r3.json()["salvage"], r3.text
    # no se puede demoler el HQ
    async with client.session_maker() as s:
        hq = (await s.execute(select(Building).where(
            Building.base_id == base, Building.building_key == "headquarters"))).scalar_one()
        hqid = hq.id
    r4 = await client.http.post(f"/api/v1/bases/buildings/{hqid}/demolish", headers=h)
    assert r4.status_code == 400
