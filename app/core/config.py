"""Application configuration settings using Pydantic Settings."""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for DecisionVault."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application Metadata
    PROJECT_NAME: str = "DecisionVault"
    VERSION: str = "0.1.0"
    APP_ENV: Literal["development", "test", "production"] = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Server Configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    API_V1_STR: str = "/api/v1"

    # CORS Configuration
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # PostgreSQL Connection Parameters
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "decisionvault"
    POSTGRES_PASSWORD: str = "decisionvault_secret_password"
    POSTGRES_DB: str = "decisionvault"

    # Optional direct DATABASE_URL override
    DATABASE_URL: str | None = None

    # Connection Pool Settings
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    # Deterministic Guardrails & Safety Parameters
    DUPLICATE_DETECTION_WINDOW_SECONDS: int = 300
    PRICE_DRIFT_THRESHOLD_PERCENT: Decimal = Decimal("25.0")
    PRICE_DRIFT_MIN_SAMPLES: int = 3
    HISTORICAL_LOOKBACK_DAYS: int = 90
    MEMORY_CONTEXT_LIMIT: int = 10

    # Semantic Memory & Vector Embedding Settings
    EMBEDDING_PROVIDER: str = "deterministic"
    EMBEDDING_MODEL: str = "decisionvault-embed-v1"
    EMBEDDING_DIMENSION: int = 384
    SEMANTIC_SIMILARITY_THRESHOLD: Decimal = Decimal("0.70")
    OPENAI_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None

    # Memory Compression Settings
    MEMORY_COMPRESSION_LOOKBACK_DAYS: int = 90
    MEMORY_COMPRESSION_MAX_SOURCE_EVENTS: int = 500

    # Razorpay Test Mode Payment Gateway Settings
    RAZORPAY_KEY_ID: str | None = None
    RAZORPAY_KEY_SECRET: str | None = None
    RAZORPAY_CURRENCY_DEFAULT: str = "INR"
    RAZORPAY_MOCK_FALLBACK: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def async_database_url(self) -> str:
        """Returns an async-compatible database connection URL."""
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            # Normalize standard postgresql:// to postgresql+asyncpg://
            if url.startswith("postgresql://"):
                return url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return url
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_database_url(self) -> str:
        """Returns a sync-compatible database URL (for Alembic migrations)."""
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            if url.startswith("postgresql+asyncpg://"):
                return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
            if url.startswith("sqlite+aiosqlite://"):
                return url.replace("sqlite+aiosqlite://", "sqlite://", 1)
            return url
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        """Parsed list of allowed CORS origins."""
        if not self.CORS_ORIGINS:
            return []
        return [
            origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """Returns cached application settings singleton."""
    return Settings()
