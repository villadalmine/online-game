"""SDD 71 — analítica per-jugador para gráficos in-app: combate (ataques/defensas) + uso de IA."""
import json

from app.core.security import hash_password
from app.models import CombatLog, GameEvent, Player
from app.services.analytics import ai_activity, combat_summary, llm_usage


async def _p(session, name):
    p = Player(username=name, password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    return p


async def test_combat_summary_counts_wins_losses_and_loot(session):
    me = await _p(session, "gral")
    foe = await _p(session, "rival")
    # gané un ataque (con botín), perdí otro; me defendí bien una vez y me arrasaron otra.
    won = json.dumps({"loot": {"iron": 100, "silicon": 50}})
    lost = json.dumps({"loot": {"iron": 30}})
    session.add(CombatLog(attacker_id=me.id, defender_id=foe.id, target_base_id=1,
                          outcome="attacker", details=won))
    session.add(CombatLog(attacker_id=me.id, defender_id=foe.id, target_base_id=1,
                          outcome="defender"))
    session.add(CombatLog(attacker_id=foe.id, defender_id=me.id, target_base_id=2,
                          outcome="defender"))
    session.add(CombatLog(attacker_id=foe.id, defender_id=me.id, target_base_id=2,
                          outcome="attacker", details=lost))
    await session.flush()

    c = await combat_summary(session, me.id, hours=24)
    assert c["atk_won"] == 1 and c["atk_lost"] == 1
    assert c["def_won"] == 1 and c["def_lost"] == 1
    assert c["loot_gained"] == 150.0   # 100+50 del ataque ganado
    assert c["loot_lost"] == 30.0      # lo que me saquearon al perder defendiendo
    assert isinstance(c["series"], list) and len(c["series"]) >= 1


async def test_llm_usage_breaks_down_by_mode(session):
    me = await _p(session, "consultor")
    for m in ("gpu", "gpu", "cloud", "hack"):
        session.add(GameEvent(type="advisor_ask", player_id=me.id, payload=json.dumps({"mode": m})))
    session.add(GameEvent(type="build", player_id=me.id, payload="{}"))  # ruido: no cuenta
    await session.flush()

    u = await llm_usage(session, me.id, hours=24)
    assert u["total"] == 4
    assert u["by_mode"]["gpu"] == 2 and u["by_mode"]["cloud"] == 1 and u["by_mode"]["hack"] == 1
    assert sum(u["series"]) == 4


async def test_ai_activity_groups_autopilot_by_action(session):
    # SDD 69: qué hicieron los robots (journal ai_autopilot), agrupado por acción + suma de qty.
    me = await _p(session, "robotico")
    for action, qty in (("staff_workers", 5), ("staff_workers", 3), ("build_mine", 0),
                        ("attack", 0)):
        session.add(GameEvent(type="ai_autopilot", player_id=me.id,
                              payload=json.dumps({"action": action, "qty": qty})))
    session.add(GameEvent(type="build", player_id=me.id, payload="{}"))  # ruido: no cuenta
    await session.flush()

    a = await ai_activity(session, me.id, hours=24)
    assert a["total"] == 4
    assert a["by_action"]["staff_workers"] == {"count": 2, "qty": 8}
    assert a["by_action"]["build_mine"]["count"] == 1
    assert a["by_action"]["attack"]["count"] == 1
