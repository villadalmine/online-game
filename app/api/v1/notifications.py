import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.api.deps import get_current_player
from app.content.registry import normalize_lang
from app.core import metrics
from app.core.config import get_settings
from app.core.db import get_session, get_sessionmaker
from app.core.security import decode_token
from app.models import Player
from app.schemas import MarkReadRequest, NotificationOut
from app.services.notifications import (
    list_notifications,
    localize,
    mark_read,
    stream_events,
)

router = APIRouter()


@router.get("/stream")
async def stream(
    request: Request,
    token: str,
    interval: float | None = None,
    maker=Depends(get_sessionmaker),
):
    """Server-Sent Events: pushes notifications live. Auth via ?token= because
    EventSource can't send headers. Connect from JS with `new EventSource(url)`."""
    username = decode_token(token)
    if username is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token invalido")
    async with maker() as s:
        player = (
            await s.execute(select(Player).where(Player.username == username))
        ).scalar_one_or_none()
    if player is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Jugador no encontrado")

    # Default desde config (SDD 7): subir STREAM_INTERVAL en prod baja la carga DB del SSE.
    if interval is None:
        interval = get_settings().stream_interval
    interval = min(max(interval, 0.05), 30.0)
    # catch_up=False: el SSE solo empuja notificaciones NUEVAS (el historial lo trae el GET);
    # evita reproducir el backlog al conectar (30 sonidos + 30 refresh de golpe).
    gen = stream_events(maker, player.id, request.is_disconnected, interval, catch_up=False)

    async def _counted():
        # SDD 19: gauge de conexiones SSE = "conectados ahora".
        metrics.SSE_CONNECTIONS.inc()
        try:
            async for ev in gen:
                yield ev
        finally:
            metrics.SSE_CONNECTIONS.dec()

    return StreamingResponse(_counted(), media_type="text/event-stream")


@router.get("", response_model=list[NotificationOut])
async def get_notifications(
    unread: bool = False,
    lang: str | None = None,
    accept_language: str | None = Header(default=None),
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    items = await list_notifications(session, player.id, unread_only=unread)
    lg = normalize_lang(lang or accept_language)  # SDD 4: re-render del texto del server
    out = []
    for n in items:
        data = json.loads(n.data or "{}")
        out.append(
            NotificationOut(
                id=n.id,
                type=n.type,
                message=localize(n.type, data, n.message, lg),
                data=data,
                is_read=n.is_read,
                created_at=n.created_at,
            )
        )
    return out


@router.post("/read")
async def read_notifications(
    body: MarkReadRequest | None = None,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Marca notificaciones como leídas (todas, o las de `ids`)."""
    ids = body.ids if body else None
    count = await mark_read(session, player.id, ids)
    await session.commit()
    return {"marked_read": count}
