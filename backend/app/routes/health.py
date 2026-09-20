from fastapi import APIRouter

from app.assistant.providers import probe_local_llm
from app.config import get_settings
from app.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    settings = get_settings()
    db_mode = "sqlite" if settings.use_sqlite else "postgresql"
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        demo_mode=settings.demo_mode,
        database=db_mode,
    )


@router.get("/health/llm")
def health_llm() -> dict:
    """Local / configured LLM status — never fails the app."""
    settings = get_settings()
    return {
        "assistant_llm_provider": settings.assistant_llm_provider,
        "local": probe_local_llm(),
        "api_key_configured": bool(settings.llm_api_key),
    }
