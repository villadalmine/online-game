"""SDD 28 / métricas por app — el campo `user` (end_user en LiteLLM) lleva la etiqueta de la app
para que el dashboard separe online-game del resto de servicios que comparten el LiteLLM/GPU."""
from app.services.llm import APP_TAG, _tag_user


def test_tag_user_prefixes_app():
    assert _tag_user("player:bob") == f"{APP_TAG}:player:bob"
    assert _tag_user("npc:42") == f"{APP_TAG}:npc:42"


def test_tag_user_without_subid_is_just_app():
    assert _tag_user(None) == APP_TAG
    assert _tag_user("") == APP_TAG


async def test_llm_calls_metric_by_kind(monkeypatch):
    # SDD 28 §3.5: game_llm_calls_total se etiqueta por kind (advisor|npc|other).
    import httpx

    from app.core import metrics
    from app.services import llm

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    async def _post(self, url, **kw):
        return _Resp()

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)
    before = metrics.LLM_CALLS._vals.get(("npc", "ok"), 0.0)
    out = await llm.llm_chat(
        [{"role": "user", "content": "hi"}], kind="npc",
        api_key="k", base_url="http://litellm.test/v1",
    )
    assert out == "ok"
    assert metrics.LLM_CALLS._vals.get(("npc", "ok"), 0.0) == before + 1


async def test_llm_route_and_tokens_metrics(monkeypatch):
    # SDD 65 obs: verificamos que la GPU respondió (route) y contamos tokens del campo `usage`.
    import time

    import httpx

    from app.core import metrics
    from app.services import llm

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 30}}

    async def _post(self, url, **kw):
        return _Resp()

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)
    r_before = metrics.LLM_ROUTE._vals.get(("npc", "gpu", "ok"), 0.0)
    p_before = metrics.LLM_TOKENS._vals.get(("npc", "gpu", "prompt"), 0.0)
    c_before = metrics.LLM_TOKENS._vals.get(("npc", "gpu", "completion"), 0.0)
    t0 = time.time()
    out = await llm.llm_chat(
        [{"role": "user", "content": "hi"}], kind="npc", route="gpu",
        api_key="k", base_url="http://gpu.test/v1",
    )
    assert out == "ok"
    assert metrics.LLM_ROUTE._vals.get(("npc", "gpu", "ok"), 0.0) == r_before + 1
    assert metrics.LLM_TOKENS._vals.get(("npc", "gpu", "prompt"), 0.0) == p_before + 120
    assert metrics.LLM_TOKENS._vals.get(("npc", "gpu", "completion"), 0.0) == c_before + 30
    assert metrics.LLM_LAST_OK._vals.get(("gpu",), 0.0) >= t0   # heartbeat de la ruta gpu
