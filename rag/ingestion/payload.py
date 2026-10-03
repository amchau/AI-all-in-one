from __future__ import annotations

from rag.ingestion.models import Chunk, ManifestDocument


def build_qdrant_payload(
    document: ManifestDocument,
    chunk: Chunk,
    fingerprint: str,
) -> dict[str, str | int | None]:
    metadata = document.metadata
    return {
        "doc_id": str(metadata["doc_id"]),
        "doc_type": str(metadata["doc_type"]),
        "product": str(metadata["product"]),
        "policy_id": metadata["policy_id"],
        "version": str(metadata["version"]),
        "effective_date": str(metadata["effective_date"]),
        "acl": str(metadata["acl"]),
        "section": chunk.section,
        "clause": chunk.clause,
        "page": chunk.page,
        "content_hash": chunk.content_hash,
        "document_fingerprint": fingerprint,
        "token_count": chunk.token_count,
        "text": chunk.text,
    }