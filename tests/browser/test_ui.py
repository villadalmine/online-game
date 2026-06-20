"""Browser e2e: drives the real web client in Chromium and saves screenshots so you
can see how each screen looks. Run with `make test-ui`."""
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
