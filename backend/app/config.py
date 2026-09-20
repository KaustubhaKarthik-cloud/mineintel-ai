"""MineIntel AI application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py → parents[1] = backend/, parents[2] = mineintel-ai/
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            str(_PROJECT_ROOT / ".env"),
            str(_BACKEND_ROOT / ".env"),
            ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MineIntel AI"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = "dev-secret-change-me"

    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Prefer DATABASE_URL; USE_SQLITE keeps local demo easy without Docker
    database_url: str = "postgresql+psycopg2://mineintel:mineintel@localhost:5432/mineintel"
    use_sqlite: bool = True
    sqlite_url: str = "sqlite:///./mineintel_demo.db"

    llm_api_base: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    embedding_api_base: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    documents_dir: str = "../documents"
    upload_max_size_mb: int = 50

    tesseract_cmd: str = ""
    ocr_language: str = "eng"
    # Min average chars/page to treat PDF as digital (else OCR)
    pdf_digital_text_threshold: int = 40
    # Base render DPI for scanned PDFs (stable layout); detail pass corrects digit confusions
    ocr_dpi: int = 200
    ocr_detail_dpi: int = 300
    ocr_detail_refine: bool = True

    # Phase 3 — LLM extraction
    llm_provider: str = "mock"  # mock | openai
    high_confidence_threshold: float = 0.85
    review_threshold: float = 0.70
    extraction_page_batch_size: int = 5
    achievement_discrepancy_tolerance: float = 2.0  # percentage points

    # Phase 4 — embeddings / retrieval
    embedding_provider: str = "mock"  # mock | openai
    chunk_size: int = 500
    chunk_overlap: int = 80
    search_top_k: int = 5
    min_similarity_threshold: float = 0.28  # hybrid score floor (vector + keyword boost)
    max_search_query_length: int = 1000
    index_verified_facts: bool = True

    # Phase 5 — validation / contradiction detection
    validation_absolute_tolerance: float = 0.01
    validation_relative_tolerance: float = 0.002  # 0.2%
    validation_reviewer_default: str = "ops.analyst"

    # Phase 6 — Analytics + Topics + local LLM (assistant already present)
    assistant_llm_provider: str = "mock"  # mock | openai | compatible | local_qwen | ollama
    assistant_max_history: int = 8
    assistant_rag_top_k: int = 5
    # Local Qwen (no API key). Prefer Ollama OpenAI-compatible endpoint.
    local_llm_base_url: str = "http://127.0.0.1:11434"
    local_llm_model: str = "qwen2.5:7b"
    local_llm_timeout_seconds: float = 90.0
    local_llm_enabled: bool = True
    topic_min_hits: int = 1
    topic_summary_top_k: int = 6

    demo_mode: bool = True
    # Phase 7 — auth / RBAC
    auth_required: bool = False  # False = demo can browse; protected write routes still check permissions when token present
    jwt_expire_hours: int = 24
    auth_seed_users: bool = True

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def effective_database_url(self) -> str:
        if self.use_sqlite:
            return self.sqlite_url
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
