"""Colonización (SDD 37, v1): el grafo de opciones raza×planeta para tu imperio (read-only)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player, lock_current_player
from app.core.db import get_session
from app.models import Player
from app.schemas import ColonizeOptionOut, ColonizeRequest, ColonyOut
from app.services.colonization import ColonizeError, found_colony, options

router = APIRouter()


@router.post("", response_model=ColonyOut, status_code=status.HTTP_201_CREATED)
async def colonize(
    body: ColonizeRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Funda una colonia en otro planeta (valida raza×planeta, consume transbordador + energía)."""
    try:
        base = await found_colony(session, player, body.planet_key, body.mode)
    except ColonizeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return ColonyOut(
        base_id=base.id, planet_key=base.planet_key, name=base.name, base_type=base.base_type
    )


@router.get("/options", response_model=list[ColonizeOptionOut])
async def colonize_options(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Para tu raza, el veredicto de cada planeta de tu galaxia (great/ok/poor/impossible) con
    modifiers y el porqué. Es el grafo para decidir a dónde expandirse."""
    if player.race_key is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Primero completá el onboarding.")
    from sqlalchemy import func, select

    from app.core.config import get_settings
    from app.models import Base_
    from app.services.research import researched_techs
    techs = await researched_techs(session, player.id)
    s = get_settings()
    # Costo de la PRÓXIMA colonia: escala con cuántas ya tenés (sin contar el mundo natal).
    n_bases = (await session.execute(
        select(func.count()).select_from(Base_).where(Base_.player_id == player.id)
    )).scalar_one()
    colonies = max(0, n_bases - 1)
    e_surface = s.colonize_energy_cost * (1 + colonies)
    e_orbital = e_surface * s.orbital_cost_mult
    return [
        ColonizeOptionOut(
            **o, energy_surface=round(e_surface, 1), energy_orbital=round(e_orbital, 1)
        )
        for o in options(player.race_key, player.galaxy_key, techs)
    ]
