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


pytestmark = pytest.mark.skipif(not _chromium_ok(), reason="Chromium de Playwright no disponible")


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
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _shown(pg, sel):
    return pg.eval_on_selector(sel, "el=>!el.classList.contains('hidden')")


def _has_token(pg):
    return pg.evaluate("!!localStorage.getItem('token')")


def _token(username):
    st, d = _req("/api/v1/auth/register", "POST", {"username": username, "password": "pw12345"})
    if st != 201:
        st, d = _req("/api/v1/auth/login", "POST", {"username": username, "password": "pw12345"})
    tok = d["access_token"]
    if not _req("/api/v1/players/me", token=tok)[1].get("race_key"):
        _req("/api/v1/players/onboard", "POST",
             {"galaxy_key": "milky_way", "planet_key": "earth", "race_key": "terran"}, token=tok)
    return tok


def test_pictographic_mode_renders_without_js_errors(server):
    tok = _token("web_picto")
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(BASE + "/")
        pg.evaluate("(t)=>localStorage.setItem('token', t)", tok)
        pg.goto(BASE + "/")
        pg.wait_for_timeout(1200)
        assert _shown(pg, "#game"), "el juego no se mostró"
        pg.click("#pictotoggle")          # modo dibujos ON
        pg.wait_for_timeout(1000)
        # los minerales se renderizan como íconos, sin romper
        minerals = pg.eval_on_selector("#minerals", "el=>el.innerHTML")
        assert "ico" in minerals, "el modo dibujos no renderizó íconos de mineral"
        assert _shown(pg, "#game"), "el juego desapareció en picto"
        b.close()
    assert not errors, f"errores de JS en runtime: {errors}"


def test_boot_does_not_logout_on_transient_5xx(server):
    """Un fallo transitorio de /players/me (deploy/pod rolando) NO debe desloguear."""
    tok = _token("web_resil")
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
    tok = _token("web_401")
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
