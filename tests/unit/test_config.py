"""Unit tests for configuration management."""

from app.core.config import Settings, get_settings


def test_default_settings():
    """Verify default configuration values."""
    settings = Settings(DATABASE_URL=None)
    assert settings.PROJECT_NAME == "DecisionVault"
    assert settings.VERSION == "0.1.0"
    assert settings.PORT == 8000
    assert "postgresql+asyncpg://" in settings.async_database_url
    assert "postgresql+psycopg://" in settings.sync_database_url


def test_cors_origins_parsing():
    """Verify comma-separated CORS origin parsing into clean string list."""
    settings = Settings(
        CORS_ORIGINS="http://localhost:3000, https://app.example.com , "
    )
    origins = settings.cors_origin_list
    assert len(origins) == 2
    assert "http://localhost:3000" in origins
    assert "https://app.example.com" in origins


def test_async_database_url_normalization():
    """Verify standard postgresql:// URL is normalized."""
    settings = Settings(DATABASE_URL="postgresql://user:pass@dbhost:5432/testdb")
    expected = "postgresql+asyncpg://user:pass@dbhost:5432/testdb"
    assert settings.async_database_url == expected

    # Legacy postgres:// format
    legacy_settings = Settings(DATABASE_URL="postgres://user:pass@dbhost:5432/testdb")
    assert legacy_settings.async_database_url == expected


def test_sync_database_url_normalization():
    """Verify asyncpg and standard URLs are converted to psycopg sync URL."""
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://user:pass@dbhost:5432/testdb"
    )
    expected = "postgresql+psycopg://user:pass@dbhost:5432/testdb"
    assert settings.sync_database_url == expected

    # Legacy postgres:// format
    legacy_settings = Settings(DATABASE_URL="postgres://user:pass@dbhost:5432/testdb")
    assert legacy_settings.sync_database_url == expected


def test_settings_caching():
    """Verify get_settings returns the singleton cached instance."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
