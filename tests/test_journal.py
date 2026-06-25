"""SDD 38 — journal de eventos: record() registra + mide; las acciones dejan su evento."""
import json

from app.core import metrics
from app.models import Player
from app.services.journal import list_events, record, to_dict
from app.services.onboarding import onboard_player


async def test_record_appends_event_and_meters(session):
    key = ("unit_test_evt",)
    before = metrics.JOURNAL_EVENTS._vals.get(key, 0.0)
    await record(session, "unit_test_evt", None, foo=1, bar="x")
    await session.commit()
    evs = [e for e in await list_events(session) if e.type == "unit_test_evt"]
    assert evs, "el evento debe quedar en el journal"
    d = to_dict(evs[-1])
    assert d["payload"] == {"foo": 1, "bar": "x"} and d["seq"] > 0
    assert metrics.JOURNAL_EVENTS._vals.get(key, 0.0) == before + 1  # Prometheus por tipo


async def test_onboard_and_actions_are_journaled(session):
    p = Player(username="journaler", password_hash="x")
    session.add(p)
    await session.flush()
    await onboard_player(session, p, "milky_way", "mars", "martian")
    await session.commit()

    evs = await list_events(session, p.id)
    types = [e.type for e in evs]
    assert "onboard" in types
    onb = next(e for e in evs if e.type == "onboard")
    assert json.loads(onb.payload)["race"] == "martian"
    # orden total por seq (ids crecientes)
    seqs = [e.id for e in evs]
    assert seqs == sorted(seqs)
