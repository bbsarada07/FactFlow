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

    # Pipeline behaviour
    DEEP_REASONING_THRESHOLD: float = 0.85
    MAX_REQUESTS_PER_MINUTE: int = 10
    CACHE_TTL_HOURS: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
