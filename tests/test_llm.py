"""SDD 28 / métricas por app — el campo `user` (end_user en LiteLLM) lleva la etiqueta de la app
para que el dashboard separe online-game del resto de servicios que comparten el LiteLLM/GPU."""
from app.services.llm import APP_TAG, _tag_user


def test_tag_user_prefixes_app():
    assert _tag_user("player:bob") == f"{APP_TAG}:player:bob"
    assert _tag_user("npc:42") == f"{APP_TAG}:npc:42"


def test_tag_user_without_subid_is_just_app():
    assert _tag_user(None) == APP_TAG
    assert _tag_user("") == APP_TAG
