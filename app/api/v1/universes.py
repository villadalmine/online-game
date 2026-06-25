"""Universos spin-off (SDD 26) — VITRINA pública (showcase, no jugable aún).

Sirve los packs de `content/universes.yaml` para mostrarlos en la página: mundos, naves, materiales
y en qué difieren del universo estándar. Modo genérico/homenaje (nombres alterados). Sin auth."""
from fastapi import APIRouter, Header, HTTPException, status

from app.content.registry import get_content, localize, normalize_lang

router = APIRouter()

_NESTED = ("materials", "worlds", "ships")


def _localize_pack(pack: dict, lang: str, *, full: bool) -> dict:
    out = localize(pack, lang)
    for k in _NESTED:
        items = pack.get(k) or []
        out[k] = [localize(it, lang) for it in items] if full else len(items)
    out["key"] = pack["key"]
    return out


@router.get("")
async def universes(
    lang: str | None = None,
    accept_language: str | None = Header(default=None),
):
    """Lista de universos (resumen): nombre, homenaje, tagline, conteos. Público, localizado."""
    chosen = normalize_lang(lang or accept_language)
    return [_localize_pack(u, chosen, full=False) for u in get_content().universes]


@router.get("/{key}")
async def universe(
    key: str,
    lang: str | None = None,
    accept_language: str | None = Header(default=None),
):
    """Pack completo de un universo: materiales, mundos y naves + diferencias con el estándar."""
    chosen = normalize_lang(lang or accept_language)
    pack = next((u for u in get_content().universes if u["key"] == key), None)
    if pack is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Universo desconocido: {key}")
    return _localize_pack(pack, chosen, full=True)
