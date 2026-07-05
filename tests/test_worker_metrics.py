"""SDD 19 §7.quinquies: los contadores del tick (proceso efímero) se ACUMULAN en Redis antes de
pushear, si no `rate()`/`increase()` en Grafana quedan vacíos (el bug del dashboard de vida
artificial). Verificamos acumulación entre corridas + continuidad de series con fakeredis."""
import fakeredis

from app import worker
from app.core import metrics


def _bunker_line(body: str) -> str | None:
    for ln in body.splitlines():
        if ln.startswith('game_ai_autopilot_total{action="bunker"}'):
            return ln
    return None


def test_cumulative_counter_render_accumulates_across_ticks():
    r = fakeredis.FakeStrictRedis()
    metrics.AI_AUTOPILOT._vals.clear()          # aislá de otros tests
    # tick 1: el autopiloto cava el búnker una vez
    metrics.AI_AUTOPILOT.inc(action="bunker")
    body1 = worker._cumulative_counter_render(r)
    assert _bunker_line(body1) == 'game_ai_autopilot_total{action="bunker"} 1.0'
    # tick 2 = proceso NUEVO: el contador arranca en 0 otra vez y vuelve a cavar
    metrics.AI_AUTOPILOT._vals.clear()
    metrics.AI_AUTOPILOT.inc(action="bunker")
    body2 = worker._cumulative_counter_render(r)
    assert _bunker_line(body2) == 'game_ai_autopilot_total{action="bunker"} 2.0'   # ACUMULÓ
    # tick 3: hace OTRA acción; la serie 'bunker' sigue presente (continuidad para Prometheus)
    metrics.AI_AUTOPILOT._vals.clear()
    metrics.AI_AUTOPILOT.inc(action="sell_surplus")
    body3 = worker._cumulative_counter_render(r)
    assert _bunker_line(body3) == 'game_ai_autopilot_total{action="bunker"} 2.0'
    assert 'game_ai_autopilot_total{action="sell_surplus"} 1.0' in body3


def test_cumulative_render_without_redis_falls_back():
    # sin Redis (dev/local) → render normal (deltas), sin romper
    metrics.AI_AUTOPILOT._vals.clear()
    metrics.AI_AUTOPILOT.inc(action="attack")
    body = worker._cumulative_counter_render(None)
    assert 'game_ai_autopilot_total{action="attack"} 1' in body
