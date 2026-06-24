#!/usr/bin/env python3
"""Smoke test del deploy (SDD 22): pega a los endpoints clave y sale ≠0 si algo falla.

Usos:
  python scripts/smoke.py http://galaxy-api      # contra una release viva (helm test / manual)
  python scripts/smoke.py --selftest             # levanta la app en SQLite efímero y se prueba sola
"""
from __future__ import annotations

import sys
import uuid


def _checks(client, base: str) -> None:
    """Corre los chequeos contra `client` (httpx.Client o TestClient). Levanta AssertionError."""
    r = client.get(base + "/health")
    assert r.status_code == 200 and r.json()["status"] == "ok", f"/health: {r.status_code}"

    r = client.get(base + "/api/v1/catalog")
    assert r.status_code == 200 and r.json().get("planets"), "/catalog vacío"

    user = "smoke_" + uuid.uuid4().hex[:8]
    r = client.post(
        base + "/api/v1/auth/register",
        json={"username": user, "password": "smoke-pass-123"},
    )
    assert r.status_code == 201, f"register: {r.status_code} {r.text[:120]}"
    tok = r.json()["access_token"]

    r = client.get(base + "/api/v1/players/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, f"/players/me: {r.status_code}"
    print("smoke OK: health, catalog, register, me", file=sys.stderr)


def smoke_url(base: str) -> int:
    import httpx

    base = base.rstrip("/")
    try:
        with httpx.Client(timeout=15) as c:
            _checks(c, base)
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"SMOKE FAIL: {e}", file=sys.stderr)
        return 1


def smoke_selftest() -> int:
    """Levanta la app real (SQLite efímero) y corre los chequeos — para la Capa 2 (initContainer).
    Pensado como PROCESO nuevo: la env se setea antes de importar la app; el lifespan de TestClient
    aplica las migraciones (crea el esquema)."""
    import os

    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./_smoke.db")
    os.environ.setdefault("ALLOWED_EMAILS", "")  # registro abierto para el smoke
    from fastapi.testclient import TestClient

    from app.main import app

    try:
        with TestClient(app) as c:  # entra al lifespan → run_migrations crea el esquema
            _checks(c, "")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"SMOKE FAIL (selftest): {e}", file=sys.stderr)
        return 1


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return smoke_selftest()
    if len(argv) < 2:
        print("uso: smoke.py <base_url> | --selftest", file=sys.stderr)
        return 2
    return smoke_url(argv[1])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
