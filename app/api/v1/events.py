"""Eventos dinámicos del mundo (SDD 36): leer los activos + (admin) forzar uno para QA."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_current_player
from app.content.registry import get_content, localize, normalize_lang
from app.core.db import get_session
from app.models import Player
from app.schemas import ActiveEventOut
from app.services.events import active_events_out, start_event

router = APIRouter()


@router.get("/active", response_model=list[ActiveEventOut])
async def active(
    _: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Eventos vigentes (con `ends_at` para la cuenta regresiva). Para el panel 📣 Eventos."""
    return [ActiveEventOut(**e) for e in await active_events_out(session)]


@router.get("/catalog")
async def catalog(lang: str | None = None):
    """Tipos de evento posibles ('qué puede pasar'), localizado. Público."""
    chosen = normalize_lang(lang)
    return [
        {**localize(e, chosen), "key": e["key"]} for e in get_content().events.values()
    ]


@router.post("/start/{key}", response_model=ActiveEventOut, status_code=status.HTTP_201_CREATED)
async def force_start(
    key: str,
    _: Player = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    """Fuerza un evento ya (admin/QA)."""
    try:
        await start_event(session, key)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await session.commit()
    out = next((e for e in await active_events_out(session) if e["key"] == key), None)
    if out is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "No se pudo iniciar el evento.")
    return ActiveEventOut(**out)
