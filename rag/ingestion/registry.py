from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
import uuid

import psycopg

from rag.ingestion.chunk import Chunk
from rag.ingestion.models import ManifestDocument
from rag.ingestion.pipeline import DocumentState


_ADVISORY_LOCK_KEY = 822251042


class PostgresRegistry:
    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise ValueError("PostgreSQL connection settings are required")
        self._dsn = dsn
        self._connection: psycopg.Connection | None = None

    @contextmanager
    def locked(self) -> Iterator[None]:
        if self._connection is not None:
            raise RuntimeError("registry lock is already held")
        with psycopg.connect(self._dsn, autocommit=True) as connection:
            connection.execute("SELECT pg_advisory_lock(%s)", (_ADVISORY_LOCK_KEY,))
            self._connection = connection
            try:
                yield None
            finally:
                self._connection = None
                connection.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_LOCK_KEY,))

    def start_run(self, docs_seen: int) -> str:
        run_id = str(uuid.uuid4())
        connection = self._active_connection()
        with connection.transaction():
            connection.execute(
                "INSERT INTO rag.ingestion_runs (id, status, docs_seen) "
                "VALUES (%s, 'running', %s)",
                (run_id, docs_seen),
            )
        return run_id

    def get_document(self, document_id: str) -> DocumentState | None:
        connection = self._active_connection()
        with connection.transaction():
            row = connection.execute(
                "SELECT content_fingerprint, object_key "
                "FROM rag.documents WHERE id = %s",
                (document_id,),
            ).fetchone()
            if row is None:
                return None
            chunk_rows = connection.execute(
                "SELECT id FROM rag.chunks WHERE document_id = %s ORDER BY ordinal",
                (document_id,),
            ).fetchall()
        return DocumentState(
            fingerprint=str(row[0]),
            chunk_ids=tuple(str(chunk_row[0]) for chunk_row in chunk_rows),
            object_key=str(row[1]),
        )

    def replace_document(
        self,
        document: ManifestDocument,
        chunks: list[Chunk],
        fingerprint: str,
        embedding_model: str,
        object_key: str,
    ) -> None:
        metadata = document.metadata
        document_id = str(metadata["doc_id"])
        connection = self._active_connection()
        with connection.transaction():
            connection.execute(
                """INSERT INTO rag.documents (
                    id, title, doc_type, product, policy_id, version, effective_date,
                    acl, source_path, source_sha256, pdf_sha256, content_fingerprint,
                    embedding_model, object_key
                ) VALUES (
                    %(id)s, %(title)s, %(doc_type)s, %(product)s, %(policy_id)s,
                    %(version)s, %(effective_date)s, %(acl)s, %(source_path)s,
                    %(source_sha256)s, %(pdf_sha256)s, %(content_fingerprint)s,
                    %(embedding_model)s, %(object_key)s
                ) ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    doc_type = EXCLUDED.doc_type,
                    product = EXCLUDED.product,
                    policy_id = EXCLUDED.policy_id,
                    version = EXCLUDED.version,
                    effective_date = EXCLUDED.effective_date,
                    acl = EXCLUDED.acl,
                    source_path = EXCLUDED.source_path,
                    source_sha256 = EXCLUDED.source_sha256,
                    pdf_sha256 = EXCLUDED.pdf_sha256,
                    content_fingerprint = EXCLUDED.content_fingerprint,
                    embedding_model = EXCLUDED.embedding_model,
                    object_key = EXCLUDED.object_key,
                    updated_at = NOW()""",
                {
                    "id": document_id,
                    "title": metadata["title"],
                    "doc_type": metadata["doc_type"],
                    "product": metadata["product"],
                    "policy_id": metadata["policy_id"],
                    "version": metadata["version"],
                    "effective_date": metadata["effective_date"],
                    "acl": metadata["acl"],
                    "source_path": document.source,
                    "source_sha256": document.source_sha256,
                    "pdf_sha256": document.pdf_sha256,
                    "content_fingerprint": fingerprint,
                    "embedding_model": embedding_model,
                    "object_key": object_key,
                },
            )
            connection.execute("DELETE FROM rag.chunks WHERE document_id = %s", (document_id,))
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO rag.chunks (
                        id, document_id, ordinal, section, clause, page, token_count, content_hash
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    [
                        (
                            chunk.chunk_id,
                            document_id,
                            chunk.ordinal,
                            chunk.section,
                            chunk.clause,
                            chunk.page,
                            chunk.token_count,
                            chunk.content_hash,
                        )
                        for chunk in chunks
                    ],
                )

    def finish_run(
        self,
        run_id: str,
        docs_seen: int,
        docs_changed: int,
        chunks_written: int,
    ) -> None:
        connection = self._active_connection()
        with connection.transaction():
            connection.execute(
                """UPDATE rag.ingestion_runs
                   SET status = 'succeeded', finished_at = NOW(), docs_seen = %s,
                       docs_changed = %s, chunks_written = %s, error_category = NULL
                   WHERE id = %s""",
                (docs_seen, docs_changed, chunks_written, run_id),
            )

    def fail_run(self, run_id: str, error_category: str) -> None:
        connection = self._active_connection()
        with connection.transaction():
            connection.execute(
                """UPDATE rag.ingestion_runs
                   SET status = 'failed', finished_at = NOW(), error_category = %s
                   WHERE id = %s""",
                (error_category[:120], run_id),
            )

    def _active_connection(self) -> psycopg.Connection:
        if self._connection is None:
            raise RuntimeError("registry operations require the ingestion lock")
        return self._connection
