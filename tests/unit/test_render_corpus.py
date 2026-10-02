from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

import pytest

from scripts.render_corpus import CorpusError, load_corpus, parse_document, render_corpus


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPOSITORY_ROOT / "data"


def test_corpus_has_eight_documents_with_expected_types() -> None:
    documents = load_corpus(CORPUS_DIR)

    assert len(documents) == 8
    assert Counter(document.metadata["doc_type"] for document in documents) == {
        "policy": 3,
        "endorsement": 2,
        "procedure": 2,
        "regulation": 1,
    }
    assert len({document.metadata["doc_id"] for document in documents}) == 8


def test_parser_rejects_missing_required_metadata(tmp_path: Path) -> None:
    document_path = tmp_path / "incomplete.md"
    document_path.write_text(
        "---\ndoc_id: TEST-001\ntitle: Incomplete\n---\n# Body\n",
        encoding="utf-8",
    )

    with pytest.raises(CorpusError, match="missing required metadata"):
        parse_document(document_path)


def test_parser_rejects_unsupported_document_type(tmp_path: Path) -> None:
    document_path = tmp_path / "unsupported.md"
    document_path.write_text(
        "---\n"
        "doc_id: TEST-001\n"
        "title: Unsupported\n"
        "doc_type: memo\n"
        "product: home\n"
        "policy_id: null\n"
        "version: '1.0'\n"
        "effective_date: '2026-01-01'\n"
        "acl: internal\n"
        "---\n# Body\n",
        encoding="utf-8",
    )

    with pytest.raises(CorpusError, match="unsupported doc_type"):
        parse_document(document_path)


def test_parser_rejects_non_string_document_type(tmp_path: Path) -> None:
    document_path = tmp_path / "invalid-type.md"
    document_path.write_text(
        "---\n"
        "doc_id: TEST-001\n"
        "title: Invalid type\n"
        "doc_type: []\n"
        "product: home\n"
        "policy_id: null\n"
        "version: '1.0'\n"
        "effective_date: '2026-01-01'\n"
        "acl: internal\n"
        "---\n# Body\n",
        encoding="utf-8",
    )

    with pytest.raises(CorpusError, match="doc_type must be a string"):
        parse_document(document_path)


def test_parser_rejects_noncanonical_date_format(tmp_path: Path) -> None:
    document_path = tmp_path / "invalid-date.md"
    document_path.write_text(
        "---\n"
        "doc_id: TEST-001\n"
        "title: Invalid date\n"
        "doc_type: procedure\n"
        "product: all\n"
        "policy_id: null\n"
        "version: '1.0'\n"
        "effective_date: '20250101'\n"
        "acl: internal\n"
        "---\n# Body\n",
        encoding="utf-8",
    )

    with pytest.raises(CorpusError, match="YYYY-MM-DD format"):
        parse_document(document_path)


def test_rendered_pdfs_are_valid_and_reproducible(tmp_path: Path) -> None:
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"

    first_pdfs = render_corpus(CORPUS_DIR, first_output)
    second_pdfs = render_corpus(CORPUS_DIR, second_output)

    assert len(first_pdfs) == 8
    assert all(path.read_bytes().startswith(b"%PDF-") for path in first_pdfs)
    assert all(b"%%EOF" in path.read_bytes()[-32:] for path in first_pdfs)
    first_hashes = {path.name: sha256(path.read_bytes()).hexdigest() for path in first_pdfs}
    second_hashes = {path.name: sha256(path.read_bytes()).hexdigest() for path in second_pdfs}
    assert first_hashes == second_hashes

    first_manifest = (first_output / "manifest.json").read_bytes()
    second_manifest = (second_output / "manifest.json").read_bytes()
    assert first_manifest == second_manifest
    manifest = json.loads(first_manifest)
    assert len(manifest["documents"]) == 8
    assert {item["metadata"]["doc_id"] for item in manifest["documents"]} == {
        path.stem for path in first_pdfs
    }