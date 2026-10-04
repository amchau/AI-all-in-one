from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import httpx
import psycopg
import pytest
from minio import Minio
from qdrant_client import QdrantClient, models

from rag.ingestion.embed import LiteLLMEmbedder
from rag.ingestion.manifest import load_manifest
from rag.ingestion.pipeline import ingest_documents
from rag.ingestion.registry import PostgresRegistry
from rag.ingestion.sparse import FastEmbedSparseEncoder
from rag.ingestion.settings import IngestionSettings
from rag.ingestion.store import MinioPdfStore, QdrantDenseStore, object_key_for


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INGESTION_INTEGRATION") != "1",
    reason="set RUN_INGESTION_INTEGRATION=1 with local service endpoints to run",
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = REPOSITORY_ROOT / "data" / "generated"


def _postgres_dsn(settings: IngestionSettings) -> str:
    from psycopg.conninfo import make_conninfo

    password = os.getenv("POSTGRES_INGEST_PASSWORD", "")
    if not password:
        raise ValueError("POSTGRES_INGEST_PASSWORD is required for this integration test")
    return make_conninfo(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user="rag_ingest",
        password=password,
        connect_timeout=5,
    )


def test_running_stack_ingests_and_second_run_is_noop() -> None:
    settings = IngestionSettings.from_environment()
    ingestion_password = os.getenv("POSTGRES_INGEST_PASSWORD", "")
    settings = replace(
        settings,
        postgres_dsn=None,
        postgres_user="rag_ingest",
        postgres_password=ingestion_password,
    )
    settings.validate()
    documents = load_manifest(GENERATED_DIR)
    document_ids = [str(document.metadata["doc_id"]) for document in documents]
    dsn = _postgres_dsn(settings)
    registry = PostgresRegistry(dsn)
    qdrant_client = QdrantClient(url=settings.qdrant_url, timeout=20)
    minio_client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )

    try:
        with httpx.Client(timeout=httpx.Timeout(30.0)) as http_client:
            dependencies = {
                "registry": registry,
                "pdf_store": MinioPdfStore(minio_client),
                "vector_store": QdrantDenseStore(qdrant_client),
                "embedder": LiteLLMEmbedder(
                    client=http_client,
                    base_url=settings.litellm_url,
                    master_key=settings.litellm_master_key,
                    model=settings.embedding_model,
                ),
                "sparse_embedder": FastEmbedSparseEncoder(
                    model_name=settings.sparse_model,
                ),
                "sparse_model": settings.sparse_model,
                "embedding_model": settings.embedding_model,
            }
            first_summary = ingest_documents(documents, **dependencies)
        assert first_summary.docs_seen == 8

        with psycopg.connect(dsn) as connection:
            repair_target = connection.execute(
                "SELECT id, document_id FROM rag.chunks "
                "WHERE document_id = ANY(%s) ORDER BY document_id, ordinal LIMIT 1",
                (document_ids,),
            ).fetchone()
            target_chunk_count = connection.execute(
                "SELECT COUNT(id) FROM rag.chunks WHERE document_id = %s",
                (repair_target[1],),
            ).fetchone()[0]
        target_point_id = str(repair_target[0])
        qdrant_client.delete(
            collection_name="insurance_docs",
            points_selector=models.PointIdsList(points=[target_point_id]),
            wait=True,
        )
        try:
            repair_summary = ingest_documents(documents, **dependencies)
            assert repair_summary.docs_changed == 1
            assert repair_summary.chunks_written == target_chunk_count
        finally:
            missing_points = qdrant_client.retrieve(
                collection_name="insurance_docs",
                ids=[target_point_id],
                with_payload=False,
                with_vectors=False,
            )
            if not missing_points:
                ingest_documents(documents, **dependencies)

        second_summary = ingest_documents(documents, **dependencies)
        assert second_summary.docs_changed == 0
        assert second_summary.chunks_written == 0
        for document in documents:
            assert MinioPdfStore(minio_client).exists(object_key_for(document))

        with psycopg.connect(dsn) as connection:
            document_count, chunk_count = connection.execute(
                "SELECT (SELECT COUNT(id) FROM rag.documents WHERE id = ANY(%s)), "
                "(SELECT COUNT(id) FROM rag.chunks WHERE document_id = ANY(%s))",
                (document_ids, document_ids),
            ).fetchone()
            registered_chunks = connection.execute(
                "SELECT c.id, c.document_id, c.content_hash, c.page, "
                "d.content_fingerprint, d.acl "
                "FROM rag.chunks c JOIN rag.documents d ON d.id = c.document_id "
                "WHERE c.document_id = ANY(%s)",
                (document_ids,),
            ).fetchall()
        qdrant_count = qdrant_client.count(
            collection_name="insurance_docs",
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="doc_id",
                        match=models.MatchAny(any=document_ids),
                    )
                ]
            ),
            exact=True,
        ).count

        assert document_count == len(document_ids)
        assert chunk_count == qdrant_count
        qdrant_points = qdrant_client.retrieve(
            collection_name="insurance_docs",
            ids=[str(row[0]) for row in registered_chunks],
            with_payload=True,
            with_vectors=True,
        )
        assert {str(point.id) for point in qdrant_points} == {
            str(row[0]) for row in registered_chunks
        }
        registered_by_id = {str(row[0]): row for row in registered_chunks}
        for point in qdrant_points:
            row = registered_by_id[str(point.id)]
            assert set(point.vector) == {"dense", "sparse"}
            assert len(point.vector["dense"]) == 1536
            assert len(point.vector["sparse"].indices) == len(point.vector["sparse"].values)
            assert point.payload["doc_id"] == row[1]
            assert point.payload["content_hash"] == row[2].strip()
            assert point.payload["page"] == row[3]
            assert point.payload["document_fingerprint"] == row[4].strip()
            assert point.payload["acl"] == row[5]
    finally:
        qdrant_client.close()
