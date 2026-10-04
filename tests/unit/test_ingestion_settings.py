from __future__ import annotations

import pytest

from rag.ingestion.settings import IngestionSettings


def test_postgres_dsn_does_not_require_separate_password(monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://ingest:embedded@db/platform")
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.setenv("LITELLM_MASTER_KEY", "test-key")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "test-access")
    monkeypatch.setenv("MINIO_SECRET_KEY", "test-secret")

    settings = IngestionSettings.from_environment()

    settings.validate()


def test_postgres_dsn_ignores_invalid_fallback_port(monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://ingest:embedded@db/platform")
    monkeypatch.setenv("POSTGRES_PORT", "not-a-port")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "test-key")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "test-access")
    monkeypatch.setenv("MINIO_SECRET_KEY", "test-secret")

    settings = IngestionSettings.from_environment()

    settings.validate()


def test_postgres_dsn_requires_password_for_password_auth(monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://ingest@db/platform")
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.setenv("LITELLM_MASTER_KEY", "test-key")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "test-access")
    monkeypatch.setenv("MINIO_SECRET_KEY", "test-secret")

    settings = IngestionSettings.from_environment()

    with pytest.raises(ValueError, match="POSTGRES_DSN must include a password"):
        settings.validate()


def test_minio_secure_rejects_invalid_boolean(monkeypatch) -> None:
    monkeypatch.setenv("MINIO_SECURE", "treu")

    with pytest.raises(ValueError, match="MINIO_SECURE must be true or false"):
        IngestionSettings.from_environment()


def test_sparse_model_is_configurable_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("SPARSE_MODEL", "Qdrant/bm25-test")

    settings = IngestionSettings.from_environment()

    assert settings.sparse_model == "Qdrant/bm25-test"


def test_settings_reject_whitespace_only_required_secret(monkeypatch) -> None:
    monkeypatch.setenv("LITELLM_MASTER_KEY", "   ")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "test-access")
    monkeypatch.setenv("MINIO_SECRET_KEY", "test-secret")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-password")

    settings = IngestionSettings.from_environment()

    with pytest.raises(ValueError, match="LITELLM_MASTER_KEY"):
        settings.validate()
