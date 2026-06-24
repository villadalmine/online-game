"""Browser e2e: drives the real web client in Chromium and saves screenshots so you
can see how each screen looks. Run with `make test-ui`."""
import re
import uuid

from playwright.sync_api import Page, expect


def _shot(page, path):
    """Best-effort screenshot — never fail the test over capture quirks."""
    for kw in ({"full_page": True}, {}):
        try:
            page.screenshot(path=str(path), **kw)
            return
        except Exception:
            continue


def test_full_play_through_ui(page: Page, live_server, shots):
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(live_server + "/")

    # 1) Login screen
    expect(page.get_by_text("Crear cuenta / Entrar")).to_be_visible()
    _shot(page, shots / "01-login.png")

    # 2) Register (creates the account and logs in)
    user = "ui_" + uuid.uuid4().hex[:6]
    page.locator("#u").fill(user)
    page.locator("#p").fill("secret123")
    page.click("button:has-text('Registrar')")

    # 3) Onboarding
    expect(page.locator("#onboard")).to_be_visible()
    _shot(page, shots / "02-onboard.png")
    page.select_option("#planet", "mars")
    page.select_option("#race", "martian")
    page.click("button:has-text('Comenzar')")

    # 4) Game screen
    expect(page.locator("#game")).to_be_visible()
    expect(page.get_by_text("Tu imperio")).to_be_visible()
    expect(page.locator("#minerals")).to_contain_text("iron")
    _shot(page, shots / "03-game.png")

    # 5) Build a mine (shows in the bases panel, building, with a countdown)
    page.select_option("#building", "mine")
    page.click("button:has-text('Construir')")
    expect(page.locator("#bases")).to_contain_text("mine")

    # 6) Create an alliance and see its benefits explained
    page.locator("#aname").fill("Halcones UI")
    page.locator("#atag").fill("HUI")
    page.select_option("#atype", "full")
    page.click("button:has-text('crear')")
    expect(page.get_by_text("Beneficios:")).to_be_visible()
    expect(page.locator("#alliances")).to_contain_text("Comercio")
    _shot(page, shots / "04-alliance.png")

    # 7) Guide / glossary
    page.click("button:has-text('mostrar')")
    expect(page.locator("#guide")).to_contain_text("Minerales")
    _shot(page, shots / "05-guide.png")


def test_fleets_in_transit_render_as_traveling_ships(page: Page, live_server, shots):
    """The galaxy map shows in-flight fleets as animated ships. We inject the exact
    state shape the API returns (AttackMissionOut + expeditions + incoming) and assert
    the UI draws a traveling ship per leg, positioned along its track."""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(live_server + "/")
    user = "ui_" + uuid.uuid4().hex[:6]
    page.locator("#u").fill(user)
    page.locator("#p").fill("secret123")
    page.click("button:has-text('Registrar')")
    page.select_option("#planet", "mars")
    page.select_option("#race", "martian")
    page.click("button:has-text('Comenzar')")
    expect(page.locator("#game")).to_be_visible()

    # Happy path: inject fleets and render synchronously (return HTML before the
    # 1s/4s pollers overwrite state), so the assertion can't race the timers.
    html = page.evaluate(
        """() => {
            const arr = new Date(Date.now()+30000).toISOString();   // arrives in 30s
            const ret = new Date(Date.now()+90000).toISOString();   // leg = 60s -> 50% done
            players.push({id:999, username:'Enemigo', race_key:'terran',
                          planet_key:'venus', is_npc:true, home_base_id:42, alliance_id:null});
            state.missions_outgoing = [{id:1, target_base_id:42, force:{tank:3},
                                        status:'outbound', arrives_at:arr, returns_at:ret}];
            state.expeditions = [{id:1, moon_key:'phobos',
                                  completes_at:new Date(Date.now()+60000).toISOString()}];
            state.missions_incoming = [{id:1, target_base_id:state.bases[0].id,
                                        arrives_at:new Date(Date.now()+30000).toISOString()}];
            renderTransits();
            return document.getElementById('transits').innerHTML;
        }"""
    )
    assert "🚀" in html        # outbound attack
    assert "🛰" in html        # expedition
    assert "☄" in html         # inbound attack
    assert "Marte" in html and "Venus" in html  # origin -> destination resolved by planet
    assert "left:50" in html   # ship sits mid-track (50% of the leg elapsed)
    _shot(page, shots / "06-transit.png")

    # Edge case: no fleets -> explicit empty state, no stray ship.
    empty = page.evaluate(
        "() => { state.missions_outgoing=[]; state.expeditions=[]; "
        "state.missions_incoming=[]; renderTransits(); "
        "return document.getElementById('transits').innerHTML; }"
    )
    assert "sin flotas en vuelo" in empty
    assert "ship" not in empty


def test_planet_detail_modal(page: Page, live_server, shots):
    """Clicking a planet on the map opens a detail modal with its mineral abundance,
    moons and colonies; Escape/✕ closes it."""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(live_server + "/")
    user = "ui_" + uuid.uuid4().hex[:6]
    page.locator("#u").fill(user)
    page.locator("#p").fill("secret123")
    page.click("button:has-text('Registrar')")
    page.select_option("#planet", "mars")
    page.select_option("#race", "martian")
    page.click("button:has-text('Comenzar')")
    expect(page.locator("#game")).to_be_visible()

    # Open Earth's detail (it has the Luna moon and iron-rich abundance).
    page.click(".planet .head:has-text('Tierra')")
    modal = page.locator("#pmodal")
    expect(modal).to_be_visible()
    expect(modal).to_contain_text("Abundancia mineral")
    expect(modal).to_contain_text("Hierro")     # mineral name resolved from catalog
    expect(modal).to_contain_text("Lunas")
    expect(modal).to_contain_text("Luna")       # Earth's moon
    expect(modal).to_contain_text("Colonias")
    _shot(page, shots / "07-planet.png")

    # Close with the ✕ button.
    page.click("#pmodal .x")
    expect(modal).to_be_hidden()


def test_sound_toggle(page: Page, live_server):
    """The sound toggle flips the icon, persists the preference, and exposes playBeep."""
    page.goto(live_server + "/")
    btn = page.locator("#sound")
    expect(btn).to_be_visible()
    expect(btn).to_have_text("🔊")
    assert page.evaluate("typeof playBeep") == "function"

    btn.click()  # mute
    expect(btn).to_have_text("🔇")
    assert page.evaluate("localStorage.getItem('sound')") == "off"

    btn.click()  # unmute
    expect(btn).to_have_text("🔊")
    assert page.evaluate("localStorage.getItem('sound')") == "on"


def test_world_events_ui(page: Page, live_server, shots):
    """The world events card shows the alliance you just formed."""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(live_server + "/")
    user = "ui_" + uuid.uuid4().hex[:6]
    page.locator("#u").fill(user)
    page.locator("#p").fill("secret123")
    page.click("button:has-text('Registrar')")
    page.select_option("#planet", "earth")
    page.select_option("#race", "terran")
    page.click("button:has-text('Comenzar')")
    expect(page.locator("#game")).to_be_visible()

    page.locator("#aname").fill("Vigías del Mundo")
    page.locator("#atag").fill("VDM")
    page.click("button:has-text('crear')")

    # refresh() polls /world/events every 4s; the new alliance should appear.
    expect(page.locator("#world")).to_contain_text("Vigías del Mundo", timeout=10000)
    _shot(page, shots / "09-world.png")


def test_alliance_chat_ui(page: Page, live_server, shots):
    """After creating an alliance, the chat card appears and a posted message shows up."""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(live_server + "/")
    user = "ui_" + uuid.uuid4().hex[:6]
    page.locator("#u").fill(user)
    page.locator("#p").fill("secret123")
    page.click("button:has-text('Registrar')")
    page.select_option("#planet", "earth")
    page.select_option("#race", "terran")
    page.click("button:has-text('Comenzar')")
    expect(page.locator("#game")).to_be_visible()

    page.locator("#aname").fill("Tertulia")
    page.locator("#atag").fill("TER")
    page.select_option("#atype", "full")
    page.click("button:has-text('crear')")

    # The chat card shows up once you're in an alliance.
    expect(page.locator("#chatcard")).to_be_visible(timeout=10000)
    page.locator("#chatmsg").fill("hola galaxia")
    page.click("#chatcard button:has-text('enviar')")
    expect(page.locator("#chatfeed")).to_contain_text("hola galaxia")
    expect(page.locator("#chatfeed")).to_contain_text("(vos)")
    _shot(page, shots / "08-chat.png")


def test_npc_alliance_is_not_joinable_in_ui(page: Page, live_server):
    page.goto(live_server + "/")
    user = "ui_" + uuid.uuid4().hex[:6]
    page.locator("#u").fill(user)
    page.locator("#p").fill("secret123")
    page.click("button:has-text('Registrar')")
    page.select_option("#planet", "earth")
    page.select_option("#race", "terran")
    page.click("button:has-text('Comenzar')")
    expect(page.locator("#game")).to_be_visible()

    # AUTO_TICK spawns the NPC alliance; it must show up flagged as not joinable.
    expect(page.locator("#ally-list")).to_contain_text("NPC (no unible)", timeout=15000)


def test_login_page_public_showcase(page: Page, live_server):
    """La página de login muestra stats públicas del universo sin estar logueado (SDD 12)."""
    page.goto(live_server + "/")
    expect(page.locator("#universe")).to_contain_text("jugadores", timeout=10000)


def test_header_shows_galaxy_instance(page: Page, live_server):
    """El header muestra tu instancia de galaxia (SDD 8)."""
    page.goto(live_server + "/")
    user = "ui_" + uuid.uuid4().hex[:6]
    page.locator("#u").fill(user)
    page.locator("#p").fill("secret123")
    page.click("button:has-text('Registrar')")
    page.select_option("#planet", "earth")
    page.select_option("#race", "terran")
    page.click("button:has-text('Comenzar')")
    expect(page.locator("#game")).to_be_visible()
    # "Vía Láctea #1" (o el nombre localizado del template + seq)
    expect(page.locator("#who")).to_contain_text("#", timeout=10000)


def test_season_card_shows_current_and_protection(page: Page, live_server, shots):
    """La card de Temporada muestra la temporada activa y el escudo de novato (SDD 11)."""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(live_server + "/")
    user = "ui_" + uuid.uuid4().hex[:6]
    page.locator("#u").fill(user)
    page.locator("#p").fill("secret123")
    page.click("button:has-text('Registrar')")
    page.select_option("#planet", "earth")
    page.select_option("#race", "terran")
    page.click("button:has-text('Comenzar')")
    expect(page.locator("#game")).to_be_visible()

    expect(page.locator("#seasoninfo")).to_contain_text("Temporada", timeout=10000)
    expect(page.locator("#seasoninfo")).to_contain_text("Protección de novato")
    page.click("button:has-text('ver ranking de temporada')")
    expect(page.locator("#seasonranking")).to_contain_text(user, timeout=10000)
    _shot(page, shots / "15-season.png")


def test_email_otp_request_and_verify(page: Page, live_server, shots):
    """Passwordless por la UI: pedir código llama al server real (MAIL_BACKEND=console) y aparece
    el campo de código; verificar con un código mal da error claro (sin crashear la UI)."""
    page.goto(live_server + "/")
    email = f"otp_{uuid.uuid4().hex[:6]}@b.com"

    page.locator("#otpemail").fill(email)
    page.click("button:has-text('Enviar código')")
    # request-code real (200 uniforme) → aparece el input del código
    expect(page.locator("#otpcoderow")).to_be_visible(timeout=10000)
    expect(page.locator("#autherr")).to_contain_text(email)

    page.locator("#otpcode").fill("000000")  # código incorrecto
    page.click("#otpcoderow button:has-text('Entrar')")
    expect(page.locator("#autherr")).to_be_visible()   # error mostrado, UI viva
    expect(page.locator("#otpemail")).to_be_visible()
    _shot(page, shots / "14-otp.png")


def test_language_toggle_en_es(page: Page, live_server, shots):
    """🌐 toggles the game between ES and EN: panel titles + catalog content; persists."""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(live_server + "/")
    user = "ui_" + uuid.uuid4().hex[:6]
    page.locator("#u").fill(user)
    page.locator("#p").fill("secret123")
    page.click("button:has-text('Registrar')")
    page.select_option("#planet", "earth")
    page.select_option("#race", "terran")
    page.click("button:has-text('Comenzar')")
    expect(page.locator("#game")).to_be_visible()

    # starts in Spanish
    expect(page.locator(".card[data-panel='mundo'] > h2")).to_have_text("🌍 Eventos del mundo")

    page.click("#langtoggle")  # -> EN
    expect(page.locator("#langtoggle")).to_have_text("🌐 EN")
    expect(page.locator(".card[data-panel='mundo'] > h2")).to_have_text("🌍 World events")
    # catalog content switched too: the build select now has English option labels
    expect(page.locator("#building")).to_contain_text("Mine")
    _shot(page, shots / "13-lang-en.png")

    page.reload()  # persists across reload
    expect(page.locator("#game")).to_be_visible()
    expect(page.locator("#langtoggle")).to_have_text("🌐 EN")
    expect(page.locator(".card[data-panel='mundo'] > h2")).to_have_text("🌍 World events")

    page.click("#langtoggle")  # back to ES
    expect(page.locator(".card[data-panel='mundo'] > h2")).to_have_text("🌍 Eventos del mundo")


def test_panels_collapse_persist_and_expand(page: Page, live_server, shots):
    """Clicking a panel title folds it to the header; the state survives a reload."""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(live_server + "/")
    user = "ui_" + uuid.uuid4().hex[:6]
    page.locator("#u").fill(user)
    page.locator("#p").fill("secret123")
    page.click("button:has-text('Registrar')")
    page.select_option("#planet", "earth")
    page.select_option("#race", "terran")
    page.click("button:has-text('Comenzar')")
    expect(page.locator("#game")).to_be_visible()

    world = page.locator("#world")
    expect(world).to_be_visible()
    page.click(".card[data-panel='mundo'] > h2")  # collapse
    expect(world).to_be_hidden()
    expect(page.locator(".card[data-panel='mundo'] > h2")).to_be_visible()  # title stays

    page.reload()  # persistence: still collapsed after reload
    expect(page.locator("#game")).to_be_visible()
    expect(page.locator("#world")).to_be_hidden()
    _shot(page, shots / "12-panels-collapsed.png")

    page.click(".card[data-panel='mundo'] > h2")  # expand again
    expect(page.locator("#world")).to_be_visible()

    # "expand all" clears every collapsed panel
    page.click(".card[data-panel='mundo'] > h2")  # collapse one again
    page.click("#expandall")
    expect(page.locator("#world")).to_be_visible()


def test_advisor_card_gives_advice_and_suggestions(page: Page, live_server, shots):
    """The assistant card answers and renders an actionable suggestion. No LLM in tests, so
    this exercises the deterministic fallback (grounded on the dependency graph)."""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(live_server + "/")
    user = "ui_" + uuid.uuid4().hex[:6]
    page.locator("#u").fill(user)
    page.locator("#p").fill("secret123")
    page.click("button:has-text('Registrar')")
    page.select_option("#planet", "mars")
    page.select_option("#race", "martian")
    page.click("button:has-text('Comenzar')")
    expect(page.locator("#game")).to_be_visible()

    page.locator("#advmsg").fill("quiero una mina de silicio")
    page.click("button:has-text('preguntar')")

    # naming a mineral yields a one-click suggestion that builds THAT mine (not a stale one).
    expect(page.locator("#advsugs")).to_contain_text("mina de silicon", timeout=10000)
    expect(page.locator("#advreply")).not_to_contain_text("te aconsejo según el grafo")
    _shot(page, shots / "11-advisor.png")


def test_mark_read_clears_notifications_feed(page: Page, live_server, shots):
    """Bug fix: 'marcar leídas' must empty the feed (it used to leave stale items).
    The feed renders unread notifications from the API; mocking that endpoint keeps the
    test deterministic (real notifications need slow in-game timers)."""
    seen_read = {"done": False}

    def handle_list(route):
        body = (
            "[]"
            if seen_read["done"]
            else '[{"id":1,"type":"battle","message":"NPC atacó tu base",'
            '"data":{},"is_read":false,"created_at":"2026-06-22T10:00:00+00:00"}]'
        )
        route.fulfill(status=200, content_type="application/json", body=body)

    def handle_read(route):
        seen_read["done"] = True
        route.fulfill(
            status=200, content_type="application/json", body='{"marked_read":1}'
        )

    page.route(re.compile(r"/api/v1/notifications\?unread=true"), handle_list)
    page.route(re.compile(r"/api/v1/notifications/read$"), handle_read)

    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(live_server + "/")
    user = "ui_" + uuid.uuid4().hex[:6]
    page.locator("#u").fill(user)
    page.locator("#p").fill("secret123")
    page.click("button:has-text('Registrar')")
    page.select_option("#planet", "earth")
    page.select_option("#race", "terran")
    page.click("button:has-text('Comenzar')")
    expect(page.locator("#game")).to_be_visible()

    # The unread notification shows up in the feed...
    expect(page.locator("#feed")).to_contain_text("NPC atacó tu base", timeout=10000)
    _shot(page, shots / "10-notifs-before.png")

    # ...and 'marcar leídas' empties it (the regression).
    page.click("button:has-text('marcar leídas')")
    expect(page.locator("#feed")).to_contain_text("sin notificaciones sin leer")
    expect(page.locator("#feed")).not_to_contain_text("NPC atacó tu base")
    _shot(page, shots / "10-notifs-after.png")


def test_language_toggle_to_english(page: Page, live_server, shots):
    """SDD 4 i18n: el toggle 🌐 pasa la UI a inglés (auth screen)."""
    page.goto(live_server + "/")
    expect(page.get_by_text("Crear cuenta / Entrar")).to_be_visible()
    page.click("#langtoggle")  # es -> en
    expect(page.get_by_text("Sign up / Log in")).to_be_visible()
    expect(page.locator("button:has-text('Register and play')")).to_be_visible()
    expect(page.locator("button:has-text('Log in')").first).to_be_visible()
    _shot(page, shots / "11-en.png")
