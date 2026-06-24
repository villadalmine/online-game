#!/usr/bin/env python3
"""Genera web/og-image.png (1200×630) para la landing (SDD 24): screenshot de /game con Playwright.

Levanta un server efímero (SQLite) y captura la landing renderizada. Correr a mano cuando cambie
el diseño:  .venv/bin/python scripts/capture_og.py
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main() -> int:
    import httpx
    from playwright.sync_api import sync_playwright

    port = _free_port()
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{ROOT}/_og.db",
        "ALLOWED_EMAILS": "",
        "REDIS_ENABLED": "false",
        "AUTO_TICK_SECONDS": "0",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(60):
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1200, "height": 630})
            pg.goto(f"http://127.0.0.1:{port}/game")
            pg.wait_for_timeout(900)
            pg.screenshot(path=str(ROOT / "web" / "og-image.png"))
            b.close()
        print("web/og-image.png generado")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        (ROOT / "_og.db").unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
