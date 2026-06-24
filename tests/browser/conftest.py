"""Fixtures for browser (Playwright) tests: spin up the real server against a temp
SQLite DB on a free port, and expose its URL as Playwright's base_url."""
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SHOTS = Path(__file__).parent / "screenshots"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def live_server(tmp_path_factory):
    port = _free_port()
    db = tmp_path_factory.mktemp("uidb") / "ui.db"
    env = {
        "PATH": __import__("os").environ.get("PATH", ""),
        "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
        "JWT_SECRET": "ui-tests-secret-at-least-32-bytes-long",
        "AUTO_TICK_SECONDS": "1",  # NPCs spawn/play so the scoreboard/alliances fill in
        "NPC_BRAIN": "rules",
        # Aislar del .env local (pydantic lo lee del cwd): registro abierto, sin admin gate,
        # mailer a consola (no Resend) → los browser-tests son herméticos.
        "ALLOWED_EMAILS": "",
        "ADMIN_EMAIL": "",
        "MAIL_BACKEND": "console",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            if httpx.get(url + "/health", timeout=1).status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        proc.terminate()
        raise RuntimeError("el server no arrancó para los tests de navegador")
    yield url
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


@pytest.fixture(scope="session")
def base_url(live_server):
    return live_server


@pytest.fixture
def shots():
    SHOTS.mkdir(exist_ok=True)
    return SHOTS
