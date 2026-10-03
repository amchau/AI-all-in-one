from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
import logging
from typing import Any, Literal

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, Response
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

from rag.ingestion.embed import LiteLLMEmbedder
from rag.retrieval.generation import LiteLLMAnswerGenerator
from rag.retrieval.models import (
    Citation,
    RagQueryInput,
    RagQueryResult,
    RetrievedChunk,
)
from rag.retrieval.registry import PostgresSourceRegistry
from rag.retrieval.service import QueryDependencyError, RagQueryService
from rag.retrieval.sources import (
    AmbiguousBasePolicyError,
    NoApplicableBasePolicyError,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("AI_API_ENV_FILE", ".env") or None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "ai-api"
    otel_exporter_otlp_endpoint: str = "http://otel-collector.ai-platform.svc.cluster.local:4318/v1/traces"

    litellm_url: str = "http://litellm.ai-platform.svc.cluster.local:4000"
    litellm_model: str = "gpt-oss-20b"
    litellm_master_key: str = Field(default="", repr=False)

    postgres_host: str = "postgres.ai-platform.svc.cluster.local"
    postgres_port: int = 5432
    postgres_db: str = "platform"
    postgres_query_password: str = Field(default="", repr=False)
    qdrant_url: str = "http://qdrant.ai-platform.svc.cluster.local:6333"
    embedding_model: str = "embed-small"


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


class RagChunkResponse(BaseModel):
    chunk_id: str
    ref: str
    doc_id: str
    title: str
    section: str | None
    clause: str | None
    page: int
    score: float
    text: str


class RagQueryResponse(BaseModel):
    status: Literal["answered", "insufficient_evidence"]
    answer: str
    citations: list[Citation]
    chunks: list[RagChunkResponse]
    model: str
    latency_ms: int
    trace_id: str | None


@asynccontextmanager
async def lifespan(_: FastAPI):
    required = {
        "postgres_query_password": settings.postgres_query_password,
        "litellm_master_key": settings.litellm_master_key,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required settings: {', '.join(missing)}")
    yield


app = FastAPI(title="AI API", version="0.1.0", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)


def get_postgres_dsn() -> str:
    return psycopg.conninfo.make_conninfo(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user="rag_query",
        password=settings.postgres_query_password,
    )


def execute_rag_query(request: RagQueryInput) -> RagQueryResult:
    def record_embedding_usage(token_counts: dict[str, int]) -> None:
        span = trace.get_current_span()
        if span.is_recording():
            for name, count in token_counts.items():
                span.set_attribute(f"embedding.{name}", count)

    with httpx.Client(timeout=httpx.Timeout(30.0)) as http_client:
        qdrant_client = QdrantClient(url=settings.qdrant_url, timeout=20)
        try:
            service = RagQueryService(
                source_repository=PostgresSourceRegistry(get_postgres_dsn()),
                embedder=LiteLLMEmbedder(
                    client=http_client,
                    base_url=settings.litellm_url,
                    master_key=settings.litellm_master_key,
                    model=settings.embedding_model,
                    usage_callback=record_embedding_usage,
                ),
                qdrant_client=qdrant_client,
                answer_generator=LiteLLMAnswerGenerator(
                    client=http_client,
                    base_url=settings.litellm_url,
                    master_key=settings.litellm_master_key,
                    model=settings.litellm_model,
                ),
            )
            return service.query(request)
        finally:
            qdrant_client.close()


def postgres_health() -> dict[str, Any]:
    with tracer.start_as_current_span("dependency.postgres"):
        start = time.perf_counter()
        try:
            with psycopg.connect(get_postgres_dsn(), connect_timeout=2) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, title, doc_type, product, policy_id, version, "
                        "effective_date, acl FROM rag.documents LIMIT 0"
                    )
                    cur.fetchone()
            return {"ok": True, "latency_ms": int((time.perf_counter() - start) * 1000)}
        except Exception as exc:
            logger.exception("postgres dependency check failed")
            return {"ok": False, "error": "unavailable"}


def qdrant_health() -> dict[str, Any]:
    with tracer.start_as_current_span("dependency.qdrant"):
        start = time.perf_counter()
        client: QdrantClient | None = None
        try:
            client = QdrantClient(url=settings.qdrant_url, timeout=2)
            client.get_collections()
            return {"ok": True, "latency_ms": int((time.perf_counter() - start) * 1000)}
        except Exception as exc:
            logger.exception("qdrant dependency check failed")
            return {"ok": False, "error": "unavailable"}
        finally:
            if client is not None:
                client.close()


def litellm_health() -> dict[str, Any]:
    with tracer.start_as_current_span("dependency.litellm"):
        start = time.perf_counter()
        try:
            with httpx.Client(timeout=2.0) as client:
                response = client.get(
                    f"{settings.litellm_url.rstrip('/')}/health/readiness",
                    headers={"Authorization": f"Bearer {settings.litellm_master_key}"},
                )
                response.raise_for_status()
            return {"ok": True, "latency_ms": int((time.perf_counter() - start) * 1000)}
        except Exception as exc:
            logger.exception("litellm dependency check failed")
            return {"ok": False, "error": "unavailable"}


@app.get("/healthz")
def healthz(response: Response) -> dict[str, Any]:
    deps = {
        "postgres": postgres_health(),
        "qdrant": qdrant_health(),
        "litellm": litellm_health(),
    }
    overall = all(item.get("ok") for item in deps.values())
    if not overall:
        response.status_code = 503
    return {"ok": overall, "dependencies": deps}


@app.get("/livez")
def livez() -> dict[str, bool]:
    return {"ok": True}


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
            "litellm": litellm_health(),
        }

        return InvestigateResponse(
            claim_id=req.claim_id,
            model=settings.litellm_model,
            answer=answer,
            latency_ms=int((time.perf_counter() - start) * 1000),
            dependencies=deps,
        )


@app.post("/v1/rag/query", response_model=RagQueryResponse)
def rag_query(request: RagQueryInput) -> RagQueryResponse:
    with tracer.start_as_current_span("rag.query"):
        try:
            result = execute_rag_query(request)
        except AmbiguousBasePolicyError as error:
            raise HTTPException(
                status_code=409,
                detail="Applicable policy version is ambiguous",
            ) from error
        except NoApplicableBasePolicyError as error:
            raise HTTPException(
                status_code=404,
                detail="No applicable policy version found",
            ) from error
        except QueryDependencyError as error:
            logger.exception("RAG query dependency failed")
            raise HTTPException(
                status_code=502,
                detail="RAG query dependency failed",
            ) from error

        span_context = trace.get_current_span().get_span_context()
        trace_id = f"{span_context.trace_id:032x}" if span_context.is_valid else None
        return RagQueryResponse(
            status=result.answer.status,
            answer=result.answer.answer,
            citations=result.answer.citations,
            chunks=[
                RagChunkResponse(
                    chunk_id=chunk.chunk_id,
                    ref=chunk.ref,
                    doc_id=chunk.doc_id,
                    title=chunk.title,
                    section=chunk.section,
                    clause=chunk.clause,
                    page=chunk.page,
                    score=chunk.score,
                    text=chunk.text,
                )
                for chunk in result.chunks
            ],
            model=result.model,
            latency_ms=result.latency_ms,
            trace_id=trace_id,
        )
