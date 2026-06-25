"""Anuncios / "Lo que viene" (SDD 27): contenido público, data-as-code, bilingüe.

Un solo endpoint sirve a web/CLI/futuros clientes. Sin auth (es contenido público). Filtra por
`category`/`status` y localiza con `?lang=` / Accept-Language."""
from fastapi import APIRouter, Header

from app.content.registry import get_content, localize, normalize_lang

router = APIRouter()

# orden de status para mostrar lo disponible primero, luego lo que viene
_STATUS_ORDER = {"live": 0, "coming": 1, "planned": 2}


@router.get("")
async def announcements(
    lang: str | None = None,
    category: str | None = None,
    status: str | None = None,
    accept_language: str | None = Header(default=None),
):
    """Lista pública de anuncios, localizada y filtrable. Orden: status (live→planned), luego fecha
    descendente (lo más nuevo primero)."""
    chosen = normalize_lang(lang or accept_language)
    items = get_content().announcements
    if category:
        items = [a for a in items if a.get("category") == category]
    if status:
        items = [a for a in items if a.get("status") == status]
    items = sorted(
        items,
        key=lambda a: (_STATUS_ORDER.get(a.get("status"), 9), _neg_date(a.get("date"))),
    )
    return [{**localize(a, chosen), "key": a["key"]} for a in items]


def _neg_date(d) -> str:
    """Clave de orden: fecha descendente (ISO invertido). Sin fecha → al final del grupo."""
    return "" if not d else "".join(chr(255 - ord(c)) for c in str(d))
