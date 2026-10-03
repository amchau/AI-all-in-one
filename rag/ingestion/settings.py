from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict


@dataclass(frozen=True)
class IngestionSettings:
    input_dir: Path
    litellm_url: str
    litellm_master_key: str
    embedding_model: str
    postgres_dsn: str | None
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    qdrant_url: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_secure: bool
    otel_exporter_otlp_endpoint: str

    @classmethod
    def from_environment(cls) -> IngestionSettings:
        minio_secure_value = os.getenv("MINIO_SECURE", "false").lower()
        if minio_secure_value not in {"true", "false"}:
            raise ValueError("MINIO_SECURE must be true or false")
        postgres_dsn = os.getenv("POSTGRES_DSN") or None
        return cls(
            input_dir=Path(os.getenv("INGESTION_INPUT_DIR", "/app/data/generated")),
            litellm_url=os.getenv(
                "LITELLM_URL", "http://litellm.ai-platform.svc.cluster.local:4000"
            ),
            litellm_master_key=os.getenv("LITELLM_MASTER_KEY", ""),
            embedding_model=os.getenv("LITELLM_EMBEDDING_MODEL", "embed-small"),
            postgres_dsn=postgres_dsn,
            postgres_host=os.getenv(
                "POSTGRES_HOST", "postgres.ai-platform.svc.cluster.local"
            ),
            postgres_port=(
                5432
                if postgres_dsn is not None
                else int(os.getenv("POSTGRES_PORT", "5432"))
            ),
            postgres_db=os.getenv("POSTGRES_DB", "platform"),
            postgres_user=os.getenv("POSTGRES_USER", "app"),
            postgres_password=os.getenv("POSTGRES_PASSWORD", ""),
            qdrant_url=os.getenv(
                "QDRANT_URL", "http://qdrant.ai-platform.svc.cluster.local:6333"
            ),
            minio_endpoint=os.getenv("MINIO_ENDPOINT", "minio.ai-platform.svc.cluster.local:9000"),
            minio_access_key=os.getenv("MINIO_ACCESS_KEY", ""),
            minio_secret_key=os.getenv("MINIO_SECRET_KEY", ""),
            minio_secure=minio_secure_value == "true",
            otel_exporter_otlp_endpoint=os.getenv(
                "OTEL_EXPORTER_OTLP_ENDPOINT",
                "http://otel-collector.ai-platform.svc.cluster.local:4318/v1/traces",
            ),
        )

    def validate(self) -> None:
        required = {
            "LITELLM_MASTER_KEY": self.litellm_master_key,
            "MINIO_ACCESS_KEY": self.minio_access_key,
            "MINIO_SECRET_KEY": self.minio_secret_key,
        }
        if self.postgres_dsn is None:
            required["POSTGRES_PASSWORD"] = self.postgres_password
        elif not conninfo_to_dict(self.postgres_dsn).get("password", "").strip():
            raise ValueError("POSTGRES_DSN must include a password")
        required.update(
            {
                "LITELLM_URL": self.litellm_url,
                "LITELLM_EMBEDDING_MODEL": self.embedding_model,
                "QDRANT_URL": self.qdrant_url,
                "MINIO_ENDPOINT": self.minio_endpoint,
            }
        )
        missing = [key for key, value in required.items() if not value.strip()]
        if missing:
            raise ValueError(f"missing required settings: {', '.join(missing)}")
        if self.postgres_dsn is None:
            missing_database = [
                key
                for key, value in {
                    "POSTGRES_HOST": self.postgres_host,
                    "POSTGRES_DB": self.postgres_db,
                    "POSTGRES_USER": self.postgres_user,
                }.items()
                if not value.strip()
            ]
            if missing_database:
                raise ValueError(
                    f"missing required settings: {', '.join(missing_database)}"
                )
        if self.postgres_dsn is None and (self.postgres_port < 1 or self.postgres_port > 65535):
            raise ValueError("POSTGRES_PORT must be between 1 and 65535")