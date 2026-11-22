"""Central configuration, loaded from backend/.env."""
from functools import lru_cache
from typing import Literal
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
    # Provider routing. Every verdict, reason, correction and harm score comes from the reasoning
    # provider, which can only be Groq. Gemma 4 (Gemini API) only reads screenshots: it returns
    # the visible text and a few visible cues, never a verdict. VISION_PROVIDER "gemini" falls
    # back to Tesseract when the key is missing or Gemma fails; "none" means Tesseract only.
    REASONING_PROVIDER: Literal["groq"] = "groq"
    VISION_PROVIDER: Literal["gemini", "groq", "none"] = "gemini"
    GEMINI_API_KEY: str = ""
    GEMMA_MODEL: str = "gemma-4-26b-a4b-it"  # listed by the Gemini API models endpoint, 2026-10-21
    GEMMA_MAX_IMAGE_BYTES: int = 5 * 1024 * 1024
    # Sent only to models that accept it (gpt-oss family); blank disables.
    NANO_REASONING_EFFORT: str = "low"
    ULTRA_REASONING_EFFORT: str = "medium"
    LLM_TIMEOUT_SECONDS: float = 60.0

    # Evidence sources
    NEWS_API_KEY: str = ""
    GOOGLE_FACT_CHECK_API_KEY: str = ""
    TESSERACT_CMD: str = ""
    GDELT_ENABLED: bool = True
    GDELT_URL: str = "https://api.gdeltproject.org/api/v2/doc/doc"
    GDELT_ARCHIVE_START: str = "2017-01-01"  # earliest date the DOC API accepts (verified 2026-10-21)
    # Search window for date-capable news sources (GDELT). Claims about events older than
    # this are searched without a date filter. NewsAPI keeps its free-plan window (~30 days).
    NEWS_WINDOW_DAYS: int = 90

    # Source credibility tiers: fixed allow-lists (comma-separated domains), never model-assigned.
    # Suffix entries starting with "." match any domain ending in them.
    TIER_1_DOMAINS: str = "aninews.in,pib.gov.in,ptinews.com,reuters.com,apnews.com,who.int,rbi.org.in,.gov.in,.nic.in"
    # Tier 2 = established national newsrooms and IFCN-certified fact-checkers (Vishvas News, Fact Crescendo,
    # NewsMeter, The Logical Indian, Youturn and India Today's fact-check desk are IFCN signatories like Alt News,
    # BOOM and Factly). Without them a rumour refuted by six certified fact-checkers counted one strong source.
    TIER_2_DOMAINS: str = (
        "siasat.com,telanganatoday.com,thehindu.com,timesofindia.indiatimes.com,indianexpress.com,"
        "ndtv.com,news18.com,altnews.in,boomlive.in,factly.in,"
        "afp.com,newschecker.in,thequint.com,snopes.com,"
        "vishvasnews.com,factcrescendo.com,newsmeter.in,thelogicalindian.com,youturn.in,indiatoday.in,"
        "hindustantimes.com,livemint.com,economictimes.indiatimes.com,business-standard.com,thehindubusinessline.com,"
        "deccanherald.com,newindianexpress.com,theprint.in,scroll.in,bbc.com,bbc.co.uk"
    )
    TIER_4_DOMAINS: str = (
        "facebook.com,twitter.com,x.com,instagram.com,youtube.com,tiktok.com,reddit.com,quora.com,medium.com,"
        "blogspot.com,wordpress.com,sharechat.com,t.me,telegram.me,whatsapp.com,pinterest.com,substack.com,kooapp.com"
    )

    # Storage
    ASYNC_DATABASE_URL: str = f"sqlite+aiosqlite:///{(BASE_DIR / 'factflow.db').as_posix()}"
    SQLITE_FALLBACK: bool = True

    # Queue / cache
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    CELERY_BROKER_URL: str = "redis://127.0.0.1:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://127.0.0.1:6379/0"
    USE_CELERY: bool = False

    # App
    BUILD_COMMIT: str = ""  # git commit of the running build, reported by /health
    SECRET_KEY: str = ""
    FRONTEND_URL: str = "http://localhost:3000"
    BACKEND_URL: str = "http://localhost:8000"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Accounts: Sign in with Google (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET below). Everything a user checks or
    # connects is theirs alone. Sessions are HttpOnly cookies; only their SHA-256 is stored.
    ALLOWED_EMAILS: str = ""  # comma-separated; empty = anyone Google lets sign in (Testing mode: test users only)
    ADMIN_EMAILS: str = ""  # comma-separated; admins can run the benchmark and read system audit events
    SESSION_DAYS: int = 30
    # Free hosting sleeps after ~15 minutes without visitors, and a sleeping agent checks no mail. When set, the
    # backend requests this public URL (its own /health) every KEEP_ALIVE_MINUTES so it stays awake. One service
    # awake all month uses ~720 of the 750 free Render hours per workspace.
    KEEP_ALIVE_URL: str = ""
    KEEP_ALIVE_MINUTES: float = 10.0

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

    # Knowledge Base / Semantic Retrieval (RAG v1)
    # False skips KB retrieval entirely, so sentence-transformers/PyTorch is never imported.
    # Use on small hosts (e.g. Render free, 512 MB): loading the model there kills the process.
    KB_ENABLED: bool = True
    KB_SIMILARITY_THRESHOLD: float = 0.60
    KB_TOP_K: int = 5

    # Shield / inbox. Empty secrets keep the features that need them switched off (fail closed).
    APPROVAL_SECRET: str = ""  # signs approval tokens; at least 32 characters
    INBOX_USE_LLM: bool = True  # False = rules-only analysis (no model calls)
    INBOX_MAX_CLAIMS: int = 3
    INBOX_FACTCHECK_CONCURRENCY: int = 2
    # Upper bound for one inbox model call including retries; past it the analysis continues
    # rules-only (a rate-limited provider would otherwise be retried for over a minute).
    INBOX_LLM_TIMEOUT_SECONDS: float = 25.0
    MAX_INBOX_PER_MINUTE: int = 10
    ENABLE_LINK_EXPANSION: bool = False  # follow shortened links (HEAD only, SSRF-guarded)
    ENABLE_DNS_CHECKS: bool = False  # look up SPF and DMARC records of the sender's domain

    # Mail agent and read-only Gmail (docs/GMAIL_SETUP.md). Empty values keep Gmail disconnected.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    # Empty = FRONTEND_URL + /api/mail/gmail/callback (the frontend forwards /api to this backend).
    GOOGLE_REDIRECT_URI: str = ""
    TOKEN_ENCRYPTION_KEY: str = ""  # Fernet key that encrypts stored OAuth tokens
    MAIL_POLL_ENABLED: bool = True
    MAIL_POLL_SECONDS: float = 45.0
    MAIL_FIRST_SYNC: int = 20  # on first connect, only the most recent messages
    MAIL_MAX_PER_SYNC: int = 50
    MAIL_AGENT_MAX_PER_MINUTE: int = 20
    # Acting on mail (Phase 3). Every outgoing message waits MAIL_SEND_DELAY_SECONDS so it can be undone.
    MAIL_SEND_DELAY_SECONDS: int = 120
    MAIL_APPROVAL_TTL_HOURS: int = 72  # how long a "Needs you" item from the mail agent stays open
    AUTO_REPLY_MAX_CHARS: int = 1200
    MAX_FILE_BYTES: int = 10 * 1024 * 1024  # files in "My files" that the agent may send
    MAX_FILES_PER_USER: int = 50
    MAIL_SENT_SCAN_PER_SYNC: int = 20  # sent messages checked for leaks per sync
    DIGEST_HOURS: int = 24

    # Allow-listed URLs for user-facing "checks to do" (never model-generated)
    GOOGLE_SEARCH_URL: str = "https://www.google.com/search?q="
    REVERSE_IMAGE_SEARCH_URL: str = "https://lens.google.com/"
    PIB_FACTCHECK_URL: str = "https://factcheck.pib.gov.in"

    # Sandbox assistant demo (must default to False, required for vulnerable mode)
    ALLOW_VULNERABLE_DEMO: bool = False

    # WhatsApp checks (docs/WHATSAPP_SETUP.md). Missing values keep the webhook closed (503); the app still starts.
    WHATSAPP_PROVIDER: Literal["twilio", "meta"] = "twilio"
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""  # also the key that signs Twilio's webhook requests
    TWILIO_WHATSAPP_FROM: str = ""  # e.g. +14155238886 (the Twilio sandbox number)
    META_APP_SECRET: str = ""  # only for WHATSAPP_PROVIDER=meta (X-Hub-Signature-256)
    PUBLIC_BASE_URL: str = ""  # the public https origin the provider calls, e.g. https://abc.example
    WHATSAPP_HASH_SALT: str = ""  # salts the SHA-256 of sender numbers; at least 16 characters
    WHATSAPP_MAX_PER_HOUR: int = 10  # checks per sender
    WHATSAPP_MAX_TEXT_CHARS: int = 4096
    WHATSAPP_MAX_MEDIA_BYTES: int = 5 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
