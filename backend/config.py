"""Central configuration, loaded from backend/.env."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Inference (any OpenAI-compatible provider; Groq by default)
    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1/"
    NANO_MODEL: str = "openai/gpt-oss-20b"
    ULTRA_MODEL: str = "openai/gpt-oss-120b"
    VISION_MODEL: str = "qwen/qwen3.8-27b"
    # Sent only to models that accept it (gpt-oss family); blank disables.
    NANO_REASONING_EFFORT: str = "low"
    ULTRA_REASONING_EFFORT: str = "medium"
    LLM_TIMEOUT_SECONDS: float = 60.0

    # Evidence sources
    NEWS_API_KEY: str = ""
    GOOGLE_FACT_CHECK_API_KEY: str = ""
    TESSERACT_CMD: str = ""

    # Storage
    ASYNC_DATABASE_URL: str = f"sqlite+aiosqlite:///{(BASE_DIR / 'nemesisai.db').as_posix()}"
    SQLITE_FALLBACK: bool = True

    # Queue / cache
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    CELERY_BROKER_URL: str = "redis://127.0.0.1:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://127.0.0.1:6379/0"
    USE_CELERY: bool = False

    # App
    SECRET_KEY: str = ""
    FRONTEND_URL: str = "http://localhost:3000"
    BACKEND_URL: str = "http://localhost:8000"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Shown to users in the footer / navbar (must name the real provider)
    INFERENCE_PROVIDER: str = "Groq"

    # Pipeline behaviour
    DEEP_REASONING_THRESHOLD: float = 0.85
    MAX_REQUESTS_PER_MINUTE: int = 10
    MAX_CLAIM_CHARS: int = 4000

    # Honest-uncertainty gate
    MIN_STRONG_SOURCES: int = 2  # tier 1-2 sources required for a definitive verdict
    MIN_VERDICT_CONFIDENCE: float = 0.6

    # Public registry / repeat detection
    REPEAT_WINDOW_DAYS: int = 7
    REPEAT_SIMILARITY: float = 85.0  # rapidfuzz token_set_ratio, 0-100
    REPEAT_CORPUS_SIZE: int = 500

    # Allow-listed URLs for user-facing "checks to do" (never model-generated)
    GOOGLE_SEARCH_URL: str = "https://www.google.com/search?q="
    REVERSE_IMAGE_SEARCH_URL: str = "https://lens.google.com/"
    PIB_FACTCHECK_URL: str = "https://factcheck.pib.gov.in"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
