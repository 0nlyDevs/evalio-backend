"""Centralised runtime configuration, read once from the environment."""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _list(name: str) -> list[str]:
    return [v.strip() for v in os.getenv(name, "").split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    # LLM (any OpenAI-compatible endpoint: OpenRouter, Groq, Together, vLLM, Ollama...)
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    llm_model: str = os.getenv("LLM_MODEL") or os.getenv(
        "FREE_LLM_MODEL", "liquid/lfm-2.5-1.2b-thinking:free"
    )
    llm_timeout: int = _int("LLM_TIMEOUT", 90)
    llm_max_retries: int = _int("LLM_MAX_RETRIES", 3)
    # Tried in order when the main model errors out (comma separated). Defaults to
    # OpenRouter's zero-cost router when the endpoint is OpenRouter.
    llm_fallback_models: list[str] = field(default_factory=lambda: _list("LLM_FALLBACK_MODELS"))
    base_prompt: str = os.getenv("BASE_PROMPT", "").strip()

    # Database
    db_host: str = os.getenv("DB_HOST", "localhost")
    db_port: int = _int("DB_PORT", 5432)
    db_name: str = os.getenv("DB_NAME", "evalio")
    db_user: str = os.getenv("DB_USER", "postgres")
    db_password: str = os.getenv("DB_PASSWORD", "postgres")
    db_pool_min: int = _int("DB_POOL_MIN", 1)
    db_pool_max: int = _int("DB_POOL_MAX", 10)

    # Vector store (embedded by default, or a remote Chroma server when CHROMA_HOST is set)
    chroma_dir: str = os.getenv("CHROMA_DIR", "./data/chroma")
    chroma_host: str = os.getenv("CHROMA_HOST", "")
    chroma_port: int = _int("CHROMA_PORT", 8000)

    # Embeddings for the code index and semantic search. When set, an
    # OpenAI-compatible /embeddings endpoint is used instead of Chroma's
    # bundled ONNX model: loading that model in-process needs 600MB+ of RAM
    # (more than a Render free instance) and can stall on first download.
    # Leave empty to fall back to the local model (fine on a dev machine).
    embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "")
    embedding_api_key: str = os.getenv("EMBEDDING_API_KEY", "")

    # Repository ingestion
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    repo_clone_timeout: int = _int("REPO_CLONE_TIMEOUT", 180)
    repo_max_files: int = _int("REPO_MAX_FILES", 2500)
    repo_max_file_kb: int = _int("REPO_MAX_FILE_KB", 256)
    repo_max_chunks: int = _int("REPO_MAX_CHUNKS", 1200)
    repo_history_depth: int = _int("REPO_HISTORY_DEPTH", 300)

    # Evaluation worker
    run_worker: bool = _bool("RUN_WORKER", True)
    worker_concurrency: int = _int("WORKER_CONCURRENCY", 2)
    job_max_attempts: int = _int("JOB_MAX_ATTEMPTS", 2)
    job_stale_minutes: int = _int("JOB_STALE_MINUTES", 20)

    # Web search for the market agent
    web_search_enabled: bool = _bool("WEB_SEARCH_ENABLED", True)
    web_search_region: str = os.getenv("WEB_SEARCH_REGION", "us-en")

    # HTTP
    cors_origins: list[str] = field(default_factory=lambda: _list("CORS_ORIGINS"))


settings = Settings()
