from __future__ import annotations

import time
from contextlib import asynccontextmanager
import logging
from typing import Any

import httpx
import psycopg
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from qdrant_client import QdrantClient
from minio import Minio


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "ai-api"
    otel_exporter_otlp_endpoint: str = "http://otel-collector.ai-platform.svc.cluster.local:4318/v1/traces"

    litellm_url: str = "http://litellm.ai-platform.svc.cluster.local:4000"
    litellm_model: str = "gpt-oss-20b"
    litellm_master_key: str = ""

    postgres_dsn: str | None = None
    postgres_host: str = "postgres.ai-platform.svc.cluster.local"
    postgres_port: int = 5432
    postgres_db: str = "platform"
    postgres_user: str = "app"
    postgres_password: str = ""
    qdrant_url: str = "http://qdrant.ai-platform.svc.cluster.local:6333"
    minio_endpoint: str = "minio.ai-platform.svc.cluster.local:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_secure: bool = False


settings = Settings()
logger = logging.getLogger("ai-api")
logging.basicConfig(level=logging.INFO)


def setup_tracing() -> None:
    resource = Resource.create({"service.name": settings.service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        )
    )
    trace.set_tracer_provider(provider)


setup_tracing()
tracer = trace.get_tracer(__name__)
HTTPXClientInstrumentor().instrument()


class InvestigateRequest(BaseModel):
    claim_id: str = Field(min_length=1)
    prompt: str = Field(min_length=5)


class InvestigateResponse(BaseModel):
    claim_id: str
    model: str
    answer: str
    latency_ms: int
    dependencies: dict[str, Any]


@asynccontextmanager
async def lifespan(_: FastAPI):
    required = {
        "postgres_password": settings.postgres_password,
        "minio_access_key": settings.minio_access_key,
        "minio_secret_key": settings.minio_secret_key,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required settings: {', '.join(missing)}")
    yield


app = FastAPI(title="AI API", version="0.1.0", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)


def get_postgres_dsn() -> str:
    if settings.postgres_dsn:
        return settings.postgres_dsn
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def postgres_health() -> dict[str, Any]:
    with tracer.start_as_current_span("dependency.postgres"):
        start = time.perf_counter()
        try:
            with psycopg.connect(get_postgres_dsn(), connect_timeout=2) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            return {"ok": True, "latency_ms": int((time.perf_counter() - start) * 1000)}
        except Exception as exc:
            logger.exception("postgres dependency check failed")
            return {"ok": False, "error": "unavailable"}


def qdrant_health() -> dict[str, Any]:
    with tracer.start_as_current_span("dependency.qdrant"):
        start = time.perf_counter()
        try:
            client = QdrantClient(url=settings.qdrant_url, timeout=2)
            client.get_collections()
            return {"ok": True, "latency_ms": int((time.perf_counter() - start) * 1000)}
        except Exception as exc:
            logger.exception("qdrant dependency check failed")
            return {"ok": False, "error": "unavailable"}


def minio_health() -> dict[str, Any]:
    with tracer.start_as_current_span("dependency.minio"):
        start = time.perf_counter()
        try:
            client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
            _ = list(client.list_buckets())
            return {"ok": True, "latency_ms": int((time.perf_counter() - start) * 1000)}
        except Exception as exc:
            logger.exception("minio dependency check failed")
            return {"ok": False, "error": "unavailable"}


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    deps = {
        "postgres": postgres_health(),
        "qdrant": qdrant_health(),
        "minio": minio_health(),
    }
    overall = all(item.get("ok") for item in deps.values())
    return {"ok": overall, "dependencies": deps}


@app.post("/v1/investigate", response_model=InvestigateResponse)
async def investigate(req: InvestigateRequest) -> InvestigateResponse:
    with tracer.start_as_current_span("investigate"):
        start = time.perf_counter()
        payload = {
            "model": settings.litellm_model,
            "messages": [
                {"role": "system", "content": "You are a claim investigation assistant."},
                {"role": "user", "content": req.prompt},
            ],
            "temperature": 0.1,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                headers = {}
                if settings.litellm_master_key:
                    headers["Authorization"] = f"Bearer {settings.litellm_master_key}"
                response = await client.post(
                    f"{settings.litellm_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
            except Exception as exc:
                logger.exception("litellm request failed")
                raise HTTPException(status_code=502, detail="LiteLLM request failed") from exc

        data = response.json()
        try:
            answer = data["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.exception("unexpected litellm response shape")
            raise HTTPException(status_code=502, detail="LiteLLM response invalid") from exc

        deps = {
            "postgres": postgres_health(),
            "qdrant": qdrant_health(),
            "minio": minio_health(),
        }

        return InvestigateResponse(
            claim_id=req.claim_id,
            model=settings.litellm_model,
            answer=answer,
            latency_ms=int((time.perf_counter() - start) * 1000),
            dependencies=deps,
        )
