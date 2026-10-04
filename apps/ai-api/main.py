from __future__ import annotations

import os
import time
from pathlib import Path
from threading import Lock
from contextlib import asynccontextmanager
from datetime import date
import logging
from typing import Any, Literal

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from qdrant_client import QdrantClient

from rag.ingestion.embed import LiteLLMEmbedder
from rag.ingestion.sparse import FastEmbedSparseEncoder
from rag.retrieval.generation import LiteLLMAnswerGenerator
from rag.retrieval.models import (
    Citation,
    RagQueryInput,
    RagQueryResult,
    RetrievedChunk,
)
from rag.retrieval.registry import PostgresSourceRegistry
from rag.retrieval.rerank import TeiReranker
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
    sparse_model: str = "Qdrant/bm25"
    reranker_url: str = "http://reranker.ai-platform.svc.cluster.local:8080"
    reranker_model: str = "BAAI/bge-reranker-base"


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
_sparse_encoder_lock = Lock()
_sparse_encoders: dict[str, FastEmbedSparseEncoder] = {}


class InvestigateRequest(BaseModel):
    claim_id: str = Field(min_length=1)
    prompt: str = Field(min_length=5)


class InvestigateResponse(BaseModel):
    claim_id: str
    model: str
    answer: str
    latency_ms: int
    dependencies: dict[str, Any]


class ClaimsInvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    claim_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    policy_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    loss_date: date
    guidance_as_of: date | None = None
    narrative: str = Field(min_length=5, max_length=1000)


class InvestigationFindingResponse(BaseModel):
    text: str
    citations: list[Citation]


class InvestigationEvidenceResponse(BaseModel):
    chunk_id: str
    ref: str
    title: str
    section: str | None
    clause: str | None
    page: int
    text: str


class ClaimsInvestigationResponse(BaseModel):
    claim_id: str
    policy_id: str
    loss_date: date
    guidance_as_of: date
    status: Literal["answered", "insufficient_evidence"]
    summary: str
    summary_citations: list[Citation]
    findings: list[InvestigationFindingResponse]
    unresolved_questions: list[str]
    evidence: list[InvestigationEvidenceResponse]
    model: str
    latency_ms: int
    trace_id: str | None


class RagChunkResponse(BaseModel):
    chunk_id: str
    ref: str
    doc_id: str
    title: str
    section: str | None
    clause: str | None
    page: int
    score: float
    dense_score: float | None
    hybrid_score: float | None
    rerank_score: float | None
    text: str


class RagQueryResponse(BaseModel):
    mode: Literal["dense", "hybrid", "hybrid_rerank"]
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


def sanitize_server_request_span(span: Any, scope: dict[str, Any]) -> None:
    if not span.is_recording():
        return
    path = str(scope.get("path") or "/")
    scheme = str(scope.get("scheme") or "http")
    raw_headers = scope.get("headers", [])
    headers = {
        name.decode("latin-1").lower() if isinstance(name, bytes) else str(name).lower():
        value.decode("latin-1") if isinstance(value, bytes) else str(value)
        for name, value in raw_headers
    }
    host = headers.get("host")
    if not host:
        server = scope.get("server")
        if isinstance(server, tuple) and server:
            host = str(server[0])
            if len(server) > 1 and server[1] is not None:
                host = f"{host}:{server[1]}"
    safe_url = f"{scheme}://{host}{path}" if host else path
    for name, value in {
        "http.target": path,
        "http.url": safe_url,
        "http.request.target": path,
        "url.full": safe_url,
        "url.path": path,
        "url.query": "",
    }.items():
        span.set_attribute(name, value)


app = FastAPI(title="AI API", version="0.1.0", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(
    app,
    server_request_hook=sanitize_server_request_span,
)


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    _request: Request,
    error: RequestValidationError,
) -> JSONResponse:
    safe_errors: list[dict[str, Any]] = []
    location_roots = {"body", "query", "path", "header", "cookie"}
    known_fields = {
        "claim_id",
        "policy_id",
        "loss_date",
        "guidance_as_of",
        "narrative",
        "question",
        "top_k",
        "mode",
        "prompt",
    }
    for validation_error in error.errors():
        safe_error = {
            key: value
            for key, value in validation_error.items()
            if key not in {"input", "ctx", "url"}
        }
        location = validation_error.get("loc", ())
        safe_error["loc"] = [
            part
            if (
                (index == 0 and part in location_roots)
                or isinstance(part, int)
                or (isinstance(part, str) and part in known_fields)
            )
            else "field"
            for index, part in enumerate(location)
        ]
        safe_errors.append(safe_error)
    return JSONResponse(
        status_code=422,
        content={"detail": safe_errors},
    )


def get_postgres_dsn() -> str:
    return psycopg.conninfo.make_conninfo(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user="rag_query",
        password=settings.postgres_query_password,
    )


def get_sparse_encoder(model_name: str) -> FastEmbedSparseEncoder:
    with _sparse_encoder_lock:
        encoder = _sparse_encoders.get(model_name)
        if encoder is None:
            encoder = FastEmbedSparseEncoder(
                model_name=model_name,
                cache_dir=Path("/tmp/fastembed"),
            )
            _sparse_encoders[model_name] = encoder
        return encoder


def execute_rag_query(
    request: RagQueryInput,
    *,
    structured_investigation: bool = False,
) -> RagQueryResult:
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
                sparse_embedder=(
                    get_sparse_encoder(settings.sparse_model)
                    if request.mode != "dense"
                    else None
                ),
                qdrant_client=qdrant_client,
                reranker=TeiReranker(
                    client=http_client,
                    base_url=settings.reranker_url,
                    model_name=settings.reranker_model,
                ),
                answer_generator=LiteLLMAnswerGenerator(
                    client=http_client,
                    base_url=settings.litellm_url,
                    master_key=settings.litellm_master_key,
                    model=settings.litellm_model,
                ),
            )
            if structured_investigation:
                return service.query(request, structured_investigation=True)
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
            mode=result.mode,
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
                    dense_score=chunk.dense_score,
                    hybrid_score=chunk.hybrid_score,
                    rerank_score=chunk.rerank_score,
                    text=chunk.text,
                )
                for chunk in result.chunks
            ],
            model=result.model,
            latency_ms=result.latency_ms,
            trace_id=trace_id,
        )


def execute_rag_investigation(request: ClaimsInvestigationRequest) -> RagQueryResult:
    question = (
        "Prepare a non-decisional evidence brief from this unverified claim narrative: "
        f"{request.narrative}"
    )
    rag_request = RagQueryInput(
        question=question,
        policy_id=request.policy_id,
        loss_date=request.loss_date,
        guidance_as_of=request.guidance_as_of,
        top_k=5,
        mode="hybrid_rerank",
    )
    return execute_rag_query(rag_request, structured_investigation=True)


@app.post(
    "/v1/investigations",
    response_model=ClaimsInvestigationResponse,
)
def investigate_claim(request: ClaimsInvestigationRequest) -> ClaimsInvestigationResponse:
    with tracer.start_as_current_span("claims.investigation"):
        try:
            result = execute_rag_investigation(request)
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
            logger.exception("claims investigation dependency failed")
            raise HTTPException(
                status_code=502,
                detail="Claims investigation dependency failed",
            ) from error

        investigation = result.investigation
        if investigation is None:
            raise HTTPException(
                status_code=502,
                detail="Claims investigation response invalid",
            )

        citations_by_ref = {citation.ref: citation for citation in investigation.citations}
        cited_chunk_ids = {
            citation.chunk_id for citation in investigation.citations
        }
        span_context = trace.get_current_span().get_span_context()
        trace_id = f"{span_context.trace_id:032x}" if span_context.is_valid else None
        return ClaimsInvestigationResponse(
            claim_id=request.claim_id,
            policy_id=request.policy_id,
            loss_date=request.loss_date,
            guidance_as_of=request.guidance_as_of or request.loss_date,
            status=investigation.status,
            summary=investigation.summary,
            summary_citations=[
                citations_by_ref[ref] for ref in investigation.summary_refs
            ],
            findings=[
                InvestigationFindingResponse(
                    text=finding.text,
                    citations=[citations_by_ref[ref] for ref in finding.refs],
                )
                for finding in investigation.findings
            ],
            unresolved_questions=list(investigation.unresolved_questions),
            evidence=[
                InvestigationEvidenceResponse(
                    chunk_id=chunk.chunk_id,
                    ref=chunk.ref,
                    title=chunk.title,
                    section=chunk.section,
                    clause=chunk.clause,
                    page=chunk.page,
                    text=chunk.text,
                )
                for chunk in result.chunks
                if chunk.chunk_id in cited_chunk_ids
            ],
            model=result.model,
            latency_ms=result.latency_ms,
            trace_id=trace_id,
        )
