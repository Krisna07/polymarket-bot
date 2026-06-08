from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import get_settings
from backend.app.db.session import get_db
from backend.app.services.advisor import get_investment_advice
from backend.app.services.llm_runtime import (
    get_llm_runtime_status,
    list_available_models,
    set_active_model,
)

router = APIRouter(prefix="/advisor", tags=["advisor"])


class ModelSelectRequest(BaseModel):
    model: str


@router.get("/recommendations")
async def investment_recommendations(
    address: str = Query(..., min_length=42, max_length=42),
    keyword: str | None = Query(default=None, min_length=2, max_length=120),
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = get_settings()
    return await get_investment_advice(settings, db, address, research_keyword=keyword)


@router.get("/models")
async def advisor_models() -> dict:
    settings = get_settings()
    return await get_llm_runtime_status(settings)


@router.post("/models/select")
async def advisor_select_model(body: ModelSelectRequest) -> dict:
    settings = get_settings()
    models = await list_available_models(settings)
    if models and body.model not in models:
        return {
            "ok": False,
            "error": "Model not available",
            "models": models,
        }

    await set_active_model(body.model)
    return {
        "ok": True,
        "active_model": body.model,
        "models": models,
    }
