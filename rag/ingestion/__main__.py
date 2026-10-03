from __future__ import annotations

import logging
import sys

import httpx
from minio import Minio
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from psycopg.conninfo import make_conninfo
from qdrant_client import QdrantClient

from rag.ingestion.embed import LiteLLMEmbedder
from rag.ingestion.manifest import load_manifest
from rag.ingestion.pipeline import ingest_documents
from rag.ingestion.registry import PostgresRegistry
from rag.ingestion.settings import IngestionSettings
from rag.ingestion.store import MinioPdfStore, QdrantDenseStore


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rag-ingestion")


def _setup_tracing(endpoint: str) -> TracerProvider:
    provider = TracerProvider(resource=Resource.create({"service.name": "rag-ingestion"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    return provider


def _postgres_dsn(settings: IngestionSettings) -> str:
    if settings.postgres_dsn:
        return settings.postgres_dsn
    return make_conninfo(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        connect_timeout=5,
    )


def run() -> int:
    settings = IngestionSettings.from_environment()
    try:
        settings.validate()
        documents = load_manifest(settings.input_dir)
        provider = _setup_tracing(settings.otel_exporter_otlp_endpoint)
        registry = PostgresRegistry(_postgres_dsn(settings))
        qdrant_client = QdrantClient(url=settings.qdrant_url, timeout=20)
        minio_client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0)) as http_client:
                summary = ingest_documents(
                    documents,
                    registry=registry,
                    pdf_store=MinioPdfStore(minio_client),
                    vector_store=QdrantDenseStore(qdrant_client),
                    embedder=LiteLLMEmbedder(
                        client=http_client,
                        base_url=settings.litellm_url,
                        master_key=settings.litellm_master_key,
                        model=settings.embedding_model,
                    ),
                    embedding_model=settings.embedding_model,
                )
        finally:
            qdrant_client.close()
            provider.force_flush()
            provider.shutdown()
        logger.info(
            "ingestion complete: docs_seen=%d docs_changed=%d chunks_written=%d",
            summary.docs_seen,
            summary.docs_changed,
            summary.chunks_written,
        )
        return 0
    except Exception as error:
        logger.exception("ingestion failed (%s)", type(error).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(run())