"""Application configuration loaded from environment variables and .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings for Veltrix PeopleOps Assistant.

    Follows 12-factor application design, reading from environment variables
    with fallback to .env and sensible defaults pointing to ./data.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core data paths
    CORPUS_DIR: Path = Path("./data/corpus")
    MANIFEST_PATH: Path = Path("./data/manifest.json")
    DB_PATH: Path = Path("./data/veltrix.db")
    APP_DB_PATH: Path = Path("./app.db")

    # Reference date (YYYY-MM-DD). If unset, system date is used.
    APP_TODAY: str | None = None

    # LLM settings
    LLM_PROVIDER: str = "gemini"
    LLM_MODEL: str = "gemini-2.5-flash"
    GEMINI_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""

    # ChromaDB & Embeddings
    CHROMA_DIR: Path = Path("./chroma_db")
    FAST_EMBED_MODEL: str = "BAAI/bge-small-en-v1.5"

    # Operational & Behavioral Flags
    LLM_CACHE_ENABLED: bool = True
    CITE_CALENDAR_IN_TOOL_ROUTE: bool = False
    LOG_LEVEL: str = "INFO"
    MAX_CORPUS_TOKENS: int = 3000
    REQUEST_TIMEOUT_SECONDS: float = 25.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton Settings instance."""
    return Settings()
