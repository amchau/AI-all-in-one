from __future__ import annotations

from hashlib import sha256
import json

from rag.ingestion.chunk import TOKENIZER_NAME
from rag.ingestion.models import ManifestDocument


PARSER_REVISION = "pypdf-text-v1"
CHUNKER_REVISION = "section-clause-v1"


def content_fingerprint(
    document: ManifestDocument,
    *,
    pipeline_revision: str,
    embedding_model: str,
    vector_schema_revision: str,
    sparse_model: str = "none",
) -> str:
    """Fingerprint all inputs that determine the persisted chunks and vectors."""
    if not pipeline_revision or not embedding_model or not vector_schema_revision or not sparse_model:
        raise ValueError("pipeline, embedding, sparse, and vector schema identities are required")
    value = {
        "metadata": dict(document.metadata),
        "source_sha256": document.source_sha256,
        "pdf_sha256": document.pdf_sha256,
        "parser_revision": PARSER_REVISION,
        "chunker_revision": CHUNKER_REVISION,
        "pipeline_revision": pipeline_revision,
        "tokenizer": TOKENIZER_NAME,
        "embedding_model": embedding_model,
        "sparse_model": sparse_model,
        "vector_schema_revision": vector_schema_revision,
    }
    canonical = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()