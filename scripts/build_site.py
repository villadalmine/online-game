#!/usr/bin/env python3
"""Genera el GitHub Pages del juego leyendo los SDDs + CHANGELOG (SDD 18). Stdlib, sin deps.

Auto-actualizable: el Action lo corre en cada push a main. La URL del juego viene de la env
GAME_URL (variable de repo), no hardcodeada. Un guard de privacidad aborta si detecta PII/secretos
en el HTML generado (defensa en profundidad: el repo es público).
"""
from __future__ import annotations

import html
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Patrones sensibles: si aparecen en la salida, abortamos (no publicar).
_PII = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"        # emails
    r"|\b(?:\d{1,3}\.){3}\d{1,3}\b"                            # IPv4
    r"|sk-or-v1-[A-Za-z0-9]+|re_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9]{12,}"  # API keys
)
# Excepciones de ejemplo permitidas (placeholders de docs).
_ALLOWED = {"you@example.com", "192.0.2.50", "nombre.apellido@correo.com"}


def parse_sdd(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    title = ""
    estado = ""
    objetivo = ""
    lines = text.splitlines()
    for ln in lines:
        if ln.startswith("# "):
            title = ln[2:].strip()
            break
    m = re.search(r"\*\*Estado:\*\*\s*([^·\n]+)", text)
    if m:
        estado = m.group(1).strip()
    # primer párrafo bajo "## 1. Objetivo"
    obj_idx = next(
        (i for i, ln in enumerate(lines) if ln.strip().startswith("## 1. Objetivo")), None
    )
    if obj_idx is not None:
        buf = []
        for ln in lines[obj_idx + 1:]:
            if ln.startswith("#"):
                break
            if ln.strip():
                buf.append(ln.strip())
            elif buf:
                break
        objetivo = " ".join(buf)
    num = re.search(r"SDD\s+(\d+)", title)
    return {
        "num": int(num.group(1)) if num else 999,
        "title": title,
        "estado": estado,
        "objetivo": objetivo,
    }


def collect_sdds(root: Path) -> list[dict]:
    sdds = [parse_sdd(p) for p in sorted((root / "docs").glob("sdd-*.md"))]
    return sorted(sdds, key=lambda s: s["num"])


def latest_changelog(root: Path, n: int = 8) -> list[str]:
    cl = (root / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    out = []
    for ln in cl:
        if ln.startswith("### "):
            out.append(ln[4:].strip())
            if len(out) >= n:
                break
    return out


def _badge(estado: str) -> str:
    e = estado.lower()
    if "implementado" in e or "hecho" in e:
        return "🟢"
    if "bloque" in e:
        return "⛔"
    return "📝"


def build_html(sdds: list[dict], changelog: list[str], game_url: str) -> str:
    rows = "\n".join(
        f'<tr><td>{_badge(s["estado"])}</td><td><b>{html.escape(s["title"])}</b>'
        f'<div class="muted">{html.escape(s["objetivo"][:240])}</div></td></tr>'
        for s in sdds
    )
    news = "\n".join(f"<li>{html.escape(c)}</li>" for c in changelog)
    play = (
        f'<a class="btn" href="{html.escape(game_url)}">▶ Jugar</a>'
        if game_url
        else '<span class="muted">(pedí acceso al admin — es por invitación)</span>'
    )
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Online Galaxy War</title>
<style>
 body{{font-family:system-ui,sans-serif;max-width:900px;margin:0 auto;padding:24px;
   background:#0b0e17;color:#e8eaf0}}
 h1{{font-size:2rem}} .muted{{color:#9aa3b2;font-size:.9rem}}
 .btn{{display:inline-block;background:#3b82f6;color:#fff;padding:10px 18px;border-radius:8px;
   text-decoration:none;font-weight:600}}
 table{{width:100%;border-collapse:collapse;margin-top:16px}}
 td{{border-top:1px solid #232a3a;padding:10px;vertical-align:top}}
 ul{{line-height:1.6}} a{{color:#7eb6ff}}
</style></head><body>
<h1>🌌 Online Galaxy War</h1>
<p>Juego de estrategia espacial por turnos, <b>API-first</b>, con galaxias y planetas reales,
   asistente de IA y NPCs con LLM. {play}</p>
<h2>Estado / Features</h2>
<table>{rows}</table>
<h2>Novedades</h2>
<ul>{news}</ul>
<p class="muted">Generado automáticamente desde los SDDs + CHANGELOG ·
   <a href="https://github.com/villadalmine/online-game">repo</a></p>
</body></html>
"""


def scan_pii(text: str) -> list[str]:
    return [m for m in _PII.findall(text) if m not in _ALLOWED]


def main(root: Path = ROOT, out: Path | None = None) -> str:
    out = out or (root / "site")
    sdds = collect_sdds(root)
    changelog = latest_changelog(root)
    game_url = os.environ.get("GAME_URL", "").strip()
    page = build_html(sdds, changelog, game_url)
    leaks = scan_pii(page)
    if leaks:
        raise SystemExit(f"ABORT: posible PII/secreto en el sitio: {sorted(set(leaks))[:5]}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page, encoding="utf-8")
    return page


if __name__ == "__main__":
    main()
    print("site/index.html generado", file=sys.stderr)
