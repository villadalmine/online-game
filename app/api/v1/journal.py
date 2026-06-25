"""Journal de eventos (SDD 38): tu diario de acciones + export de la partida a YAML (admin)."""
import yaml
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import PlainTextResponse

from app.api.deps import get_current_admin, get_current_player
from app.core.db import get_session
from app.models import Player
from app.schemas import JournalEventOut
from app.services.journal import list_events, to_dict

router = APIRouter()


@router.get("/journal", response_model=list[JournalEventOut])
async def my_journal(
    since: int = 0,
    limit: int = 200,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Tus acciones registradas, en orden (seq). Base para un timeline/diario del jugador."""
    events = await list_events(session, player.id, since, limit)
    return [JournalEventOut(**to_dict(e)) for e in events]


@router.get("/journal/export", response_class=PlainTextResponse)
async def export_journal(
    since: int = 0,
    limit: int = 5000,
    _: Player = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    """Toda la partida como YAML ordenado por seq (admin) → 'guardo todo' / reproducir (SDD 38)."""
    events = await list_events(session, None, since, limit)
    docs = [{**to_dict(e), "at": to_dict(e)["at"].isoformat()} for e in events]
    body = yaml.safe_dump({"events": docs}, allow_unicode=True, sort_keys=False)
    return PlainTextResponse(body, media_type="text/yaml")
