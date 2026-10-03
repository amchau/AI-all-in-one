from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

import psycopg

from rag.ingestion.chunk import chunk_pages
from rag.ingestion.manifest import load_manifest
from rag.ingestion.parse import extract_pdf_pages
from rag.ingestion.registry import PostgresRegistry


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = REPOSITORY_ROOT / "data" / "generated"


def test_replace_document_inserts_chunks_with_cursor_executemany() -> None:
    document = load_manifest(GENERATED_DIR)[0]
    chunks = chunk_pages(
        str(document.metadata["doc_id"]),
        extract_pdf_pages(document.pdf_path),
    )
    connection = Mock(spec=psycopg.Connection)
    connection.transaction.return_value = nullcontext()
    cursor_context = Mock()
    cursor = Mock()
    cursor_context.__enter__ = Mock(return_value=cursor)
    cursor_context.__exit__ = Mock(return_value=False)
    connection.cursor.return_value = cursor_context
    registry = PostgresRegistry("postgresql://unused")
    registry._connection = connection

    registry.replace_document(
        document,
        chunks,
        fingerprint="d" * 64,
        embedding_model="embed-small",
        object_key="policy/POL-HOME-002-v2/2.0.pdf",
    )

    cursor.executemany.assert_called_once()
    assert len(cursor.executemany.call_args.args[1]) == len(chunks)


def test_registry_advisory_lock_connection_uses_autocommit() -> None:
    connection = Mock(spec=psycopg.Connection)
    connection_context = Mock()
    connection_context.__enter__ = Mock(return_value=connection)
    connection_context.__exit__ = Mock(return_value=False)
    registry = PostgresRegistry("postgresql://unused")

    with patch("rag.ingestion.registry.psycopg.connect", return_value=connection_context) as connect:
        with registry.locked():
            assert registry._active_connection() is connection

    connect.assert_called_once_with("postgresql://unused", autocommit=True)
