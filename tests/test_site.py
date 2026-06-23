"""SDD 18 — generador del GitHub Pages: tests del generador + guard de privacidad."""
from pathlib import Path

from scripts import build_site


def test_build_html_has_sdd_titles_and_status():
    sdds = [
        {"num": 1, "title": "SDD 1 — Grafo", "estado": "implementado", "objetivo": "Un grafo."},
        {"num": 5, "title": "SDD 5 — Telegram", "estado": "propuesto (bloqueado)", "objetivo": "B"},
    ]
    html = build_site.build_html(sdds, ["2026-06-23 — algo"], game_url="")
    assert "SDD 1 — Grafo" in html and "SDD 5 — Telegram" in html
    assert "🟢" in html and "⛔" in html  # badges por estado
    assert "pedí acceso" in html  # sin GAME_URL muestra el aviso


def test_build_html_play_button_with_url():
    html = build_site.build_html([], [], game_url="https://example.test")
    assert 'href="https://example.test"' in html and "▶ Jugar" in html


def test_scan_pii_detects_secrets_and_allows_placeholders():
    assert build_site.scan_pii("contacto real@gmail.com") == ["real@gmail.com"]
    assert build_site.scan_pii("ip 10.0.0.5") == ["10.0.0.5"]
    assert build_site.scan_pii("ejemplo you@example.com y 192.0.2.50") == []  # placeholders OK


def test_generator_runs_on_repo_and_is_clean(tmp_path):
    # Corre el generador real sobre el repo: no debe filtrar PII (los docs están limpios).
    root = Path(__file__).resolve().parents[1]
    page = build_site.main(root=root, out=tmp_path / "site")
    assert "<html" in page and "Online Galaxy War" in page
    assert (tmp_path / "site" / "index.html").exists()
    assert build_site.scan_pii(page) == []  # el sitio publicado no lleva PII
