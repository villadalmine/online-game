"""E2E de FRONTEND con un browser real (Playwright + Chromium).

Atrapa errores de runtime de la web (`web/index.html`) que `node --check` no ve: excepciones de JS
al renderizar, y regresiones de sesión (no desloguear ante un fallo transitorio de la API).

Se SALTEA solo si no hay Playwright/Chromium instalado, para no romper la suite en CI mínimos.
Levanta un uvicorn propio (puerto 8771, SQLite temporal, registro abierto) — no toca prod.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

PORT = 8771
BASE = f"http://127.0.0.1:{PORT}"


def _chromium_ok() -> bool:
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            b.close()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.chrome,
    pytest.mark.skipif(not _chromium_ok(), reason="Chromium de Playwright no disponible"),
]


def _req(path, method="GET", body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    db = tmp_path_factory.mktemp("websmoke") / "web.db"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
        "ALLOWED_EMAILS": "",            # registro abierto para el test
        "SIGNUP_REQUIRES_APPROVAL": "false",
        "AUTO_TICK_SECONDS": "0",
        "NPC_BRAIN": "rules",            # SDD 45: sin LLM/créditos en el gate
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            try:
                with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
                    pass
                if _req("/health")[0] == 200:
                    break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("uvicorn no levantó")
        yield str(db)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _shown(pg, sel):
    return pg.eval_on_selector(sel, "el=>!el.classList.contains('hidden')")


def _wait_shown(pg, sel, timeout=10000):
    """Espera a que `sel` exista y NO tenga la clase 'hidden' (evita flakes por sleeps fijos:
    bajo carga el boot puede tardar > el wait fijo y el panel todavía no se mostró)."""
    pg.wait_for_function(
        "s=>{const e=document.querySelector(s); return !!e && !e.classList.contains('hidden')}",
        arg=sel, timeout=timeout,
    )


def _has_token(pg):
    return pg.evaluate("!!localStorage.getItem('token')")


def _token(username):
    # Tolerante al rate-limit (429 → _req devuelve un STRING, no un dict): reintentar con backoff y
    # username único por intento; nunca hacer d["access_token"] sobre un string/error.
    import time as _time
    tok = None
    last = None
    for attempt in range(6):
        u = username if attempt == 0 else f"{username}{attempt}"
        st, d = _req("/api/v1/auth/register", "POST", {"username": u, "password": "pw12345"})
        if st != 201:
            st, d = _req("/api/v1/auth/login", "POST", {"username": u, "password": "pw12345"})
        if isinstance(d, dict) and d.get("access_token"):
            tok = d["access_token"]
            break
        last = (st, d)
        _time.sleep(0.6)   # backoff ante rate-limit / respuesta transitoria
    assert tok, f"no se obtuvo access_token tras reintentos: {last}"
    me = _req("/api/v1/players/me", token=tok)[1]
    if not me.get("race_key"):
        _req("/api/v1/players/onboard", "POST",
             {"galaxy_key": "milky_way", "planet_key": "earth", "race_key": "terran"}, token=tok)
        me = _req("/api/v1/players/me", token=tok)[1]
    return tok, me["id"]


def _seed_unlimited(db_path, pid):
    """SDD 45: el entorno de testing NO frena por recursos — se siembra al usuario con energía
    altísima, naves, escolta, minerales y techs para poder ejercitar TODA acción de la UI."""
    import sqlite3
    con = sqlite3.connect(db_path)
    con.execute("UPDATE players SET energy=999999, energy_updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (pid,))
    for u, q in (("cargo_ship", 50), ("soldier", 100), ("shuttle", 10), ("spy", 10)):
        con.execute("INSERT INTO unit_stocks (player_id, unit_key, quantity) VALUES (?,?,?)",
                    (pid, u, q))
    # minerales abundantes en el planeta natal (las filas las creó el onboarding; subimos el monto)
    con.execute("UPDATE resource_stocks SET amount=999999 WHERE player_id=?", (pid,))
    con.commit()
    con.close()


def test_all_panels_render_without_js_errors(server):
    """SDD 45: abre TODOS los paneles en modo normal y en modo dibujos, con el usuario sembrado
    sin límites, y falla ante cualquier console.error / pageerror. Atrapa los 500/JS de render."""
    tok, pid = _token("web_panels")
    _seed_unlimited(server, pid)
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(BASE + "/")
        pg.evaluate("(t)=>localStorage.setItem('token', t)", tok)
        pg.goto(BASE + "/")
        _wait_shown(pg, "#game")        # espera el boot (robusto, sin sleep fijo)
        panels = pg.eval_on_selector_all("[data-panel]", "els=>els.map(e=>e.dataset.panel)")
        assert len(panels) >= 10, f"se esperaban muchos paneles, hubo {panels}"

        def expand_all():
            # des-colapsar todo para forzar el render del contenido de cada card
            pg.evaluate("document.querySelectorAll('.card.collapsed>h2').forEach(h=>h.click())")
            pg.wait_for_timeout(800)

        expand_all()
        # modo normal: el contenido de cada panel está renderizado
        for name in panels:
            html = pg.eval_on_selector(f'[data-panel="{name}"]', "el=>el.innerHTML")
            assert html and len(html) > 0, f"panel {name} vacío en modo normal"
        # modo dibujos ON: re-render de todo
        pg.click("#pictotoggle")
        pg.wait_for_timeout(1200)
        expand_all()
        _wait_shown(pg, "#game")        # sigue visible tras el modo dibujos
        # íconos de mineral presentes en el imperio
        assert "ico" in pg.eval_on_selector("#minerals", "el=>el.innerHTML"), "sin íconos en picto"
        b.close()
    assert not errors, f"errores de JS en runtime (paneles): {errors}"


def test_boot_does_not_logout_on_transient_5xx(server):
    """Un fallo transitorio de /players/me (deploy/pod rolando) NO debe desloguear."""
    tok, _ = _token("web_resil")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(BASE + "/")
        pg.evaluate("(t)=>localStorage.setItem('token', t)", tok)
        state = {"hit": False}

        def handler(route):
            if not state["hit"]:
                state["hit"] = True
                route.fulfill(status=503, content_type="application/json", body='{"detail":"x"}')
            else:
                route.continue_()
        pg.route("**/api/v1/players/me", handler)
        pg.goto(BASE + "/")
        pg.wait_for_timeout(4000)         # > 3s para que dispare el reintento
        assert _has_token(pg), "perdió el token ante un 503 transitorio"
        assert not _shown(pg, "#auth"), "lo mandó al login por un 503"
        b.close()


def test_boot_logs_out_on_401(server):
    """Un 401 (token inválido) SÍ debe desloguear y volver al login."""
    tok, _ = _token("web_401")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(BASE + "/")
        pg.evaluate("(t)=>localStorage.setItem('token', t)", tok)
        pg.route("**/api/v1/players/me",
                 lambda r: r.fulfill(status=401, content_type="application/json",
                                      body='{"detail":"x"}'))
        pg.goto(BASE + "/")
        pg.wait_for_timeout(1500)
        assert not _has_token(pg), "no limpió el token ante 401"
        assert _shown(pg, "#auth"), "no volvió al login ante 401"
        b.close()
