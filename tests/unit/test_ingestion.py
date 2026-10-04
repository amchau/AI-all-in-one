from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID

import pytest
from pypdf import PdfWriter
import tiktoken

from rag.ingestion.chunk import chunk_pages
from rag.ingestion.fingerprint import content_fingerprint
from rag.ingestion.manifest import ManifestError, load_manifest
from rag.ingestion.models import PageText
from rag.ingestion.parse import PdfParseError, extract_pdf_pages


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = REPOSITORY_ROOT / "data" / "generated"


def test_manifest_loads_all_pdf_files_and_verifies_hashes() -> None:
    documents = load_manifest(GENERATED_DIR)

    assert len(documents) == 8
    for document in documents:
        assert document.pdf_path.is_file()
        assert sha256(document.pdf_path.read_bytes()).hexdigest() == document.pdf_sha256


def test_manifest_rejects_path_traversal(tmp_path: Path) -> None:
    manifest = {
        "schema_version": 1,
        "documents": [
            {
                "metadata": {
                    "doc_id": "TEST-001",
                    "title": "Test",
                    "doc_type": "policy",
                    "product": "home",
                    "policy_id": "HOME-001",
                    "version": "1.0",
                    "effective_date": "2025-01-01",
                    "acl": "internal",
                },
                "source": "test.md",
                "source_sha256": "a" * 64,
                "pdf": "../outside.pdf",
                "pdf_sha256": "b" * 64,
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ManifestError, match="safe relative filename"):
        load_manifest(tmp_path)


def test_manifest_rejects_pdf_hash_mismatch(tmp_path: Path) -> None:
    pdf_path = tmp_path / "TEST-001.pdf"
    pdf_path.write_bytes(b"not-a-real-pdf")
    manifest = {
        "schema_version": 1,
        "documents": [
            {
                "metadata": {
                    "doc_id": "TEST-001",
                    "title": "Test",
                    "doc_type": "policy",
                    "product": "home",
                    "policy_id": "HOME-001",
                    "version": "1.0",
                    "effective_date": "2025-01-01",
                    "acl": "internal",
                },
                "source": "test.md",
                "source_sha256": "a" * 64,
                "pdf": pdf_path.name,
                "pdf_sha256": "b" * 64,
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ManifestError, match="SHA-256 mismatch"):
        load_manifest(tmp_path)


def test_manifest_rejects_missing_pdf(tmp_path: Path) -> None:
    manifest = {
        "schema_version": 1,
        "documents": [
            {
                "metadata": {
                    "doc_id": "TEST-001",
                    "title": "Test",
                    "doc_type": "policy",
                    "product": "home",
                    "policy_id": "HOME-001",
                    "version": "1.0",
                    "effective_date": "2025-01-01",
                    "acl": "internal",
                },
                "source": "test.md",
                "source_sha256": "a" * 64,
                "pdf": "TEST-001.pdf",
                "pdf_sha256": "b" * 64,
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ManifestError, match="PDF file is missing"):
        load_manifest(tmp_path)


def test_manifest_rejects_invalid_calendar_date(tmp_path: Path) -> None:
    manifest = {
        "schema_version": 1,
        "documents": [
            {
                "metadata": {
                    "doc_id": "TEST-001",
                    "title": "Test",
                    "doc_type": "policy",
                    "product": "home",
                    "policy_id": "HOME-001",
                    "version": "1.0",
                    "effective_date": "2025-99-99",
                    "acl": "internal",
                },
                "source": "test.md",
                "source_sha256": "a" * 64,
                "pdf": "TEST-001.pdf",
                "pdf_sha256": "b" * 64,
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ManifestError, match="valid YYYY-MM-DD date"):
        load_manifest(tmp_path)


def test_pdf_extraction_preserves_one_based_page_order(tmp_path: Path) -> None:
    writer = PdfWriter()
    writer.append(str(GENERATED_DIR / "POL-HOME-002-v2.pdf"))
    writer.append(str(GENERATED_DIR / "POL-MOTOR-001-v1.pdf"))
    pdf_path = tmp_path / "combined.pdf"
    with pdf_path.open("wb") as pdf_file:
        writer.write(pdf_file)

    pages = extract_pdf_pages(pdf_path)

    assert len(pages) >= 2
    assert [page.page for page in pages] == list(range(1, len(pages) + 1))
    assert all(page.text.strip() for page in pages)


def test_pdf_extraction_rejects_documents_without_extractable_text(tmp_path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    pdf_path = tmp_path / "blank.pdf"
    with pdf_path.open("wb") as pdf_file:
        writer.write(pdf_file)

    with pytest.raises(PdfParseError, match="no extractable text"):
        extract_pdf_pages(pdf_path)


def test_all_generated_pdfs_extract_and_chunk_within_token_limit() -> None:
    documents = load_manifest(GENERATED_DIR)
    encoding = tiktoken.get_encoding("cl100k_base")

    for document in documents:
        pages = extract_pdf_pages(document.pdf_path)
        chunks = chunk_pages(str(document.metadata["doc_id"]), pages)

        assert chunks
        assert all(chunk.page >= 1 for chunk in chunks)
        assert all(len(encoding.encode(chunk.text)) <= 400 for chunk in chunks)


def test_chunking_preserves_section_clause_and_start_page() -> None:
    pages = [
        PageText(
            page=1,
            text="1 COVERAGE\n1.1 Flood damage is excluded.\n1.2 Escape of water is covered.",
        ),
        PageText(page=2, text="1.3 Gradual seepage is excluded."),
    ]

    chunks = chunk_pages("POL-HOME-002-v2", pages)

    assert [chunk.clause for chunk in chunks] == ["1.1", "1.2", "1.3"]
    assert all(chunk.section == "1" for chunk in chunks)
    assert [chunk.page for chunk in chunks] == [1, 1, 2]
    assert "Flood damage is excluded" in chunks[0].text
    assert all(UUID(chunk.chunk_id).version == 5 for chunk in chunks)
    assert [chunk.chunk_id for chunk in chunks] == [
        chunk.chunk_id
        for chunk in chunk_pages("POL-HOME-002-v2", pages)
    ]


def test_oversized_clause_is_split_with_bounded_token_overlap() -> None:
    long_clause = "2.1 " + "coverage " * 160
    chunks = chunk_pages(
        "POL-HOME-002-v2",
        [PageText(page=1, text=long_clause)],
        max_tokens=40,
        overlap_tokens=6,
    )
    encoding = tiktoken.get_encoding("cl100k_base")

    assert len(chunks) > 1
    assert all(chunk.token_count <= 40 for chunk in chunks)
    assert all(len(encoding.encode(chunk.text)) == chunk.token_count for chunk in chunks)
    assert all(chunk.clause == "2.1" for chunk in chunks)
    assert "coverage" in chunks[0].text and "coverage" in chunks[1].text


def test_oversized_clause_does_not_emit_overlap_only_tail_chunk() -> None:
    encoding = tiktoken.get_encoding("cl100k_base")
    for token_count, expected_chunks in ((740, 2), (741, 3)):
        clause = next(
            (
                candidate
                for repetitions in range(600, 800)
                if len(
                    encoding.encode(
                        candidate := "2.1 " + ("coverage " * repetitions).rstrip()
                    )
                )
                == token_count
            ),
            None,
        )
        assert clause is not None

        chunks = chunk_pages("POL-HOME-002-v2", [PageText(page=1, text=clause)])

        assert len(chunks) == expected_chunks
        if token_count == 741:
            assert len(encoding.encode(chunks[-1].text)) > 60


def test_chunker_advances_past_whitespace_only_token_windows() -> None:
    chunks = chunk_pages(
        "POL-HOME-002-v2",
        [PageText(page=1, text="1.1 Alpha"), PageText(page=2, text="continuation")],
        max_tokens=1,
        overlap_tokens=0,
    )

    assert chunks
    assert all(chunk.token_count == 1 for chunk in chunks)


def test_unicode_chunking_preserves_source_characters() -> None:
    encoding = tiktoken.get_encoding("cl100k_base")
    source = "1.1 " + "保険内容を確認してください。" * 40
    chunks = chunk_pages(
        "POL-HOME-002-v2",
        [PageText(page=1, text=source)],
        max_tokens=9,
        overlap_tokens=0,
    )

    assert chunks
    assert all("�" not in chunk.text for chunk in chunks)
    assert all(len(encoding.encode(chunk.text)) <= 9 for chunk in chunks)
    assert "".join(chunk.text for chunk in chunks) == source


def test_chunk_page_uses_page_of_first_visible_text_after_boundary() -> None:
    encoding = tiktoken.get_encoding("cl100k_base")
    first_page_line = "1.1 First page line."
    pages = [
        PageText(page=1, text=first_page_line),
        PageText(page=2, text="Second page line."),
    ]
    boundary_tokens = len(encoding.encode(first_page_line))

    chunks = chunk_pages(
        "POL-HOME-002-v2",
        pages,
        max_tokens=boundary_tokens,
        overlap_tokens=0,
    )
    second_page_chunk = next(chunk for chunk in chunks if "Second" in chunk.text)

    assert second_page_chunk.page == 2


def test_document_fingerprint_is_stable_and_tracks_pipeline_identity() -> None:
    document = load_manifest(GENERATED_DIR)[0]
    arguments = {
        "document": document,
        "pipeline_revision": "ingestion-v1",
        "embedding_model": "embed-small",
        "sparse_model": "Qdrant/bm25",
        "vector_schema_revision": "dense-1536-v1",
    }

    first = content_fingerprint(**arguments)
    second = content_fingerprint(**arguments)
    changed_pipeline = content_fingerprint(**{**arguments, "pipeline_revision": "ingestion-v2"})
    changed_model = content_fingerprint(**{**arguments, "embedding_model": "embed-next"})
    changed_sparse_model = content_fingerprint(
        **{**arguments, "sparse_model": "Qdrant/bm25-next"}
    )

    assert first == second
    assert changed_pipeline != first
    assert changed_model != first
    assert changed_sparse_model != first
