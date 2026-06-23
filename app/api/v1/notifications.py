import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.api.deps import get_current_player
from app.core.config import get_settings
from app.core.db import get_session, get_sessionmaker
from app.core.security import decode_token
from app.models import Player
from app.schemas import MarkReadRequest, NotificationOut
from app.services.notifications import list_notifications, mark_read, stream_events

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
    gen = stream_events(maker, player.id, request.is_disconnected, interval)
    return StreamingResponse(gen, media_type="text/event-stream")


@router.get("", response_model=list[NotificationOut])
async def get_notifications(
    unread: bool = False,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    items = await list_notifications(session, player.id, unread_only=unread)
    return [
        NotificationOut(
            id=n.id,
            type=n.type,
            message=n.message,
            data=json.loads(n.data or "{}"),
            is_read=n.is_read,
            created_at=n.created_at,
        )
        for n in items
    ]


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
