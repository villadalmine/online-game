"""Shared transport to any OpenAI-compatible chat endpoint (OpenRouter / LiteLLM / Ollama /
vLLM). Used by the NPC brain and the personal assistant — they all speak the same
`/chat/completions` schema; only LLM_BASE_URL/LLM_MODEL/LLM_API_KEY change.

Raises on missing config or network error so callers can fall back (NPC -> rules, assistant ->
deterministic blockers). One place to change the HTTP contract, used everywhere."""
import time

import httpx

from app.core import metrics
from app.core.config import get_settings


async def llm_chat(
    messages: list[dict],
    *,
    max_tokens: int = 400,
    temperature: float = 0.0,
    json_mode: bool = False,
    user: str | None = None,
    model: str | None = None,
    timeout: float | None = None,
) -> str:
    """POST messages to the configured LLM and return the assistant message content.

    `user` viaja como el campo OpenAI `user` → LiteLLM lo etiqueta `end_user` en sus métricas
    (atribución de tokens/costo por jugador y backend, SDD 28)."""
    settings = get_settings()
    if not settings.llm_key:
        raise RuntimeError("LLM no configurado (sin LLM_API_KEY/OPENROUTER_API_KEY)")
    payload = {
        "model": model or settings.llm_model_name,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if user:
        payload["user"] = user  # → end_user en LiteLLM (SDD 28)
    if json_mode:
        # Honored by OpenAI/LiteLLM/Ollama/vLLM; makes the reply parse-safe.
        payload["response_format"] = {"type": "json_object"}
    _t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout or settings.llm_timeout_seconds) as client:
            resp = await client.post(
                f"{settings.llm_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.llm_key}",
                    "X-Title": "online-game",  # ignored by non-OpenRouter servers
                },
                json=payload,
            )
            resp.raise_for_status()
            out = resp.json()["choices"][0]["message"]["content"]
        metrics.LLM_REQUESTS.inc(status="ok")  # SDD 19
        return out
    except Exception:
        metrics.LLM_REQUESTS.inc(status="error")
        raise
    finally:
        metrics.LLM_LATENCY.observe(time.perf_counter() - _t0)
