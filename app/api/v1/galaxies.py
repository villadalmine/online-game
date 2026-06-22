"""Galaxy instances / shards (SDD 8). Lecturas autenticadas; cupo y estado por instancia."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player
from app.core.db import get_session
from app.models import Player
from app.schemas import GalaxyInstanceOut
from app.services import galaxies as svc

router = APIRouter()


@router.get("", response_model=list[GalaxyInstanceOut])
async def list_galaxies(
    _: Player = Depends(get_current_player), session: AsyncSession = Depends(get_session)
):
    """Instancias de galaxia con su cupo usado (para ver/elegir partidas)."""
    return [
        GalaxyInstanceOut(
            id=i.id, template_key=i.template_key, seq=i.seq, name=i.name,
            capacity=i.capacity, player_count=i.player_count, status=i.status,
        )
        for i in await svc.list_instances(session)
    ]
