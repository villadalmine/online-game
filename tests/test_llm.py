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
