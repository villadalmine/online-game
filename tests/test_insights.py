"""SDD 41 — meta-insights: agrega el journal y calcula win-rates que la IA lee."""
import json

from app.models import GameEvent
from app.services.insights import compute_meta, get_insights, meta_summary_text


async def _battle(session, force, outcome):
    session.add(GameEvent(type="battle_resolved",
                          payload=json.dumps({"force": force, "outcome": outcome})))


async def test_compute_meta_winrates(session):
    await _battle(session, {"tank": 10}, "attacker")   # tank gana
    await _battle(session, {"tank": 5}, "defender")    # tank pierde
    await _battle(session, {"aircraft": 8}, "attacker")
    await session.commit()
    await compute_meta(session)
    await session.commit()

    ins = await get_insights(session)
    aw = ins["attack_winrate"]["payload"]
    assert aw["rate"] == round(2 / 3, 3) and aw["n"] == 3
    bu = ins["winrate_by_unit"]["payload"]
    assert bu["tank"]["rate"] == 0.5 and bu["tank"]["n"] == 2
    assert bu["aircraft"]["rate"] == 1.0


async def test_meta_summary_empty_then_filled(session):
    assert await meta_summary_text(session) == ""     # sin datos, no inventa
    await _battle(session, {"tank": 3}, "attacker")
    await session.commit()
    await compute_meta(session)
    await session.commit()
    txt = await meta_summary_text(session)
    assert "Meta" in txt and "tank" in txt


async def test_meta_tolerant_to_new_units(session):
    # una unidad que "no existía antes" (clave nueva) igual se agrupa → data sigue sirviendo
    await _battle(session, {"mecha_z": 4}, "attacker")
    await session.commit()
    await compute_meta(session)
    await session.commit()
    bu = (await get_insights(session))["winrate_by_unit"]["payload"]
    assert "mecha_z" in bu
