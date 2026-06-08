from __future__ import annotations

from typing import Any

import httpx
import structlog

from backend.app.config import Settings
from backend.app.services.redis_store import redis_get, redis_set

log = structlog.get_logger(__name__)

ACTIVE_MODEL_KEY = "llm:active_model"
_active_model_cache: str | None = None


async def get_active_model(settings: Settings) -> str:
    global _active_model_cache
    if _active_model_cache:
        return _active_model_cache

    cached = await redis_get(ACTIVE_MODEL_KEY)
    if cached:
        _active_model_cache = cached
        return cached

    return settings.ollama_model


async def set_active_model(model: str) -> None:
    global _active_model_cache
    value = model.strip()
    _active_model_cache = value
    await redis_set(ACTIVE_MODEL_KEY, value)


async def list_available_models(settings: Settings) -> list[str]:
    base = settings.ollama_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{base}/api/tags")
        resp.raise_for_status()
        data = resp.json()

    models: list[str] = []
    rows = data.get("models", []) if isinstance(data, dict) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name") or row.get("model")
        if isinstance(name, str) and name.strip():
            models.append(name.strip())

    unique = sorted(set(models))
    return unique


async def get_llm_runtime_status(settings: Settings) -> dict[str, Any]:
    available = True
    models: list[str] = []
    try:
        models = await list_available_models(settings)
    except Exception as e:
        available = False
        log.warning("llm_model_list_failed", error=str(e))

    active_model = await get_active_model(settings)
    if models and active_model not in models:
        active_model = models[0]
        await set_active_model(active_model)

    return {
        "available": available,
        "active_model": active_model,
        "models": models,
    }
