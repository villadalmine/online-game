"""SDD 22 — smoke del deploy: CLI + camino de error (sin server)."""
from scripts import smoke


def test_smoke_cli_usage():
    assert smoke.main(["smoke.py"]) == 2  # sin args/sin --selftest


def test_smoke_url_failpath():
    # conexión a un puerto muerto → falla limpio con código 1 (no excepción)
    assert smoke.smoke_url("http://127.0.0.1:9") == 1
