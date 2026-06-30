"""SDD 62: traslado de tropas entre bases propias (guarnición). Lazy by timestamp como las flotas:
salen de la base origen al crearse y se depositan en destino al llegar (intra-planeta rápido,
inter-planeta usa la distancia). Solo aplica con `garrison_enabled`."""
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Base_, Player, TroopMove
from app.services.combat import travel_seconds
from app.services.notifications import notify
from app.services.training import get_or_create_unit_stock, units_at_base


class TroopError(Exception):
    pass


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def start_move(
    session: AsyncSession, player: Player, from_base_id: int, to_base_id: int, units: dict[str, int]
) -> TroopMove:
    if not get_settings().garrison_enabled:
        raise TroopError("La guarnición está desactivada.")
    if from_base_id == to_base_id:
        raise TroopError("El origen y el destino son la misma base.")
    src = await session.get(Base_, from_base_id)
    dst = await session.get(Base_, to_base_id)
    if src is None or dst is None or src.player_id != player.id or dst.player_id != player.id:
        raise TroopError("Base inválida (origen y destino deben ser tuyas).")
    units = {k: int(q) for k, q in units.items() if q and int(q) > 0}
    if not units:
        raise TroopError("Elegí al menos una unidad para mover.")
    have = await units_at_base(session, player.id, from_base_id)
    for k, q in units.items():
        if have.get(k, 0) < q:
            raise TroopError(f"No tenés {q} {k} en la base de origen (tenés {have.get(k, 0)}).")

    now = datetime.now(UTC)
    for k, q in units.items():   # bloquear: salen de la base origen
        (await get_or_create_unit_stock(session, player.id, k, from_base_id)).quantity -= q
    travel = travel_seconds(src.planet_key, dst.planet_key)
    move = TroopMove(
        player_id=player.id, from_base_id=from_base_id, to_base_id=to_base_id,
        units=json.dumps(units), status="moving", arrives_at=now + timedelta(seconds=travel),
    )
    session.add(move)
    await session.flush()
    return move


async def process_moves(
    session: AsyncSession, now: datetime | None = None, player_id: int | None = None
) -> int:
    """Deposita en destino las tropas que llegaron (lazy). Devuelve cuántos se cerraron."""
    now = now or datetime.now(UTC)
    conds = [TroopMove.status == "moving"]
    if player_id is not None:
        conds.append(TroopMove.player_id == player_id)
    res = await session.execute(select(TroopMove).where(*conds))
    done = 0
    for move in res.scalars():
        if _aware(move.arrives_at) > now:
            continue
        for k, q in json.loads(move.units).items():
            (await get_or_create_unit_stock(
                session, move.player_id, k, move.to_base_id
            )).quantity += q
        move.status = "done"
        done += 1
        await notify(session, move.player_id, "troops_arrived",
                     f"Tus tropas llegaron a la base {move.to_base_id}",
                     {"to_base_id": move.to_base_id, "units": json.loads(move.units)})
    return done


async def active_moves(session: AsyncSession, player_id: int) -> list[TroopMove]:
    res = await session.execute(
        select(TroopMove).where(TroopMove.player_id == player_id, TroopMove.status == "moving")
    )
    return list(res.scalars())
