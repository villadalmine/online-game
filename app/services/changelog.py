"""CHANGELOG → Novedades (SDD 27): genera anuncios `release` automáticamente desde el CHANGELOG.

El CHANGELOG es la bitácora curada por fecha; cada versión `## [X.Y.Z] - AAAA-MM-DD` con su título
`### AAAA-MM-DD — Título` se transforma en un anuncio `release` para el panel de Novedades, así no
hay que mantener los releases a mano en `announcements.yaml`. Es ES (la bitácora está en ES)."""
import re
from functools import lru_cache

from app.core.config import REPO_ROOT

_VER = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})")
_HEAD = re.compile(r"^### .*?—\s*(.+?)\s*$")        # "### fecha — Título" → Título
_BULLET = re.compile(r"^\s*-\s+(.+?)\s*$")


def _clean(text: str) -> str:
    """Saca el markdown del bullet (negrita/código/links) para un resumen legible."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)   # [txt](url) → txt
    text = text.replace("**", "").replace("`", "")
    return text.strip()


@lru_cache(maxsize=1)
def recent_releases(limit: int = 8) -> list[dict]:
    """Últimas `limit` versiones del CHANGELOG como anuncios `release` (más nueva primero)."""
    try:
        lines = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    versions: list[dict] = []
    cur: dict | None = None
    for ln in lines:
        mv = _VER.match(ln)
        if mv:
            if cur:
                versions.append(cur)
            cur = {"version": mv.group(1), "date": mv.group(2), "title": None, "summary": None}
            continue
        if cur is None:
            continue
        mh = _HEAD.match(ln)
        if mh and cur["title"] is None:
            cur["title"] = mh.group(1)
            continue
        mb = _BULLET.match(ln)
        if mb and cur["summary"] is None:
            cur["summary"] = _clean(mb.group(1))
    if cur:
        versions.append(cur)
    out = []
    for v in versions[:limit]:
        head = v["title"] or "novedades"
        out.append({
            "key": f"release-{v['version']}",
            "category": "release",
            "status": "live",
            "date": v["date"],
            "title": f"v{v['version']} — {head}",
            "summary": v["summary"] or "",
            "tags": ["release"],
            "link": "CHANGELOG.md",   # el front lo manda a GitHub (docLink)
        })
    return out
