"""Mercado (SDD 42 Fase 1): precios por planeta + comprar/vender minerales con energía."""
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player, lock_current_player
from app.core.db import get_session
from app.models import Player, TransportMission
from app.schemas import (
    HubTradeRequest,
    MarketTradeRequest,
    TransportMissionOut,
    TransportRequest,
)
from app.services import market

router = APIRouter()


@router.get("/hub")
async def hub(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Hub galáctico: precios dinámicos de TU galaxia + de las demás (consulta inter-galaxia)."""
    return {
        "galaxy": player.galaxy_key,
        "prices": await market.hub_prices(session, player.galaxy_key) if player.galaxy_key else {},
        "galaxies": await market.hub_prices_all(session),
    }


@router.post("/hub/{side}")
async def hub_trade(
    side: str,
    body: HubTradeRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Comprar (`buy`) o vender (`sell`) en el hub de tu galaxia al precio dinámico."""
    if side not in ("buy", "sell"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "side debe ser buy o sell.")
    try:
        res = await market.hub_trade(session, player, body.mineral_key, body.qty, side)
    except market.MarketError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    await session.commit()
    return res


@router.post("/transport", response_model=TransportMissionOut, status_code=status.HTTP_201_CREATED)
async def transport(
    body: TransportRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Envía minerales de un planeta tuyo a otro (necesita naves de carga; viaja y llega)."""
    try:
        m = await market.start_transport(
            session, player, body.from_planet, body.to_planet, body.cargo
        )
    except market.MarketError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    await session.commit()
    return TransportMissionOut(
        id=m.id, from_planet=m.from_planet, to_planet=m.to_planet,
        cargo=json.loads(m.cargo), ships=m.ships, status=m.status, arrives_at=m.arrives_at,
    )


@router.get("/transport", response_model=list[TransportMissionOut])
async def transports(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Tus transportes en curso."""
    res = await session.execute(
        select(TransportMission).where(
            TransportMission.player_id == player.id, TransportMission.status == "outbound"
        )
    )
    return [
        TransportMissionOut(
            id=m.id, from_planet=m.from_planet, to_planet=m.to_planet,
            cargo=json.loads(m.cargo), ships=m.ships, status=m.status, arrives_at=m.arrives_at,
        )
        for m in res.scalars()
    ]


@router.get("/prices")
async def market_prices(
    planet: str,
    _: Player = Depends(get_current_player),
):
    """Tabla de precios (compra/venta en energía) de un planeta — barato donde abunda."""
    return {"planet": planet, "prices": market.prices(planet)}


@router.get("/planets")
async def my_market_planets(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Planetas donde tenés un mercado activo (para elegir dónde comerciar)."""
    return await market.player_market_planets(session, player)


@router.post("/buy")
async def buy(
    body: MarketTradeRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    try:
        res = await market.buy(session, player, body.planet_key, body.mineral_key, body.qty)
    except market.MarketError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    await session.commit()
    return res


@router.post("/sell")
async def sell(
    body: MarketTradeRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    try:
        res = await market.sell(session, player, body.planet_key, body.mineral_key, body.qty)
    except market.MarketError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    await session.commit()
    return res
