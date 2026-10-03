from __future__ import annotations

from math import isfinite
from typing import Any

from qdrant_client import models

from rag.retrieval.models import RetrievedChunk, SourceDocument


def search_dense(
    client: Any,
    query_vector: list[float],
    eligible_documents: list[SourceDocument],
    *,
    top_k: int,
) -> list[RetrievedChunk]:
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")
    documents_by_id = {
        document.doc_id: document for document in eligible_documents
    }
    if not documents_by_id:
        return []

    response = client.query_points(
        collection_name="insurance_docs",
        query=query_vector,
        using="dense",
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="doc_id",
                    match=models.MatchAny(any=list(documents_by_id)),
                )
            ]
        ),
        limit=top_k,
        with_payload=True,
        with_vectors=False,
    )
    chunks: list[RetrievedChunk] = []
    for point in response.points:
        payload = point.payload
        if not isinstance(payload, dict):
            continue
        doc_id = payload.get("doc_id")
        if not isinstance(doc_id, str):
            continue
        document = documents_by_id.get(doc_id)
        page = payload.get("page")
        score = point.score
        text = payload.get("text")
        section = payload.get("section")
        clause = payload.get("clause")
        if (
            document is None
            or type(page) is not int
            or page < 1
            or isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not isfinite(score)
            or not isinstance(text, str)
            or not text.strip()
            or (section is not None and not isinstance(section, str))
            or (clause is not None and not isinstance(clause, str))
        ):
            continue
        chunks.append(
            RetrievedChunk(
                chunk_id=str(point.id),
                ref=f"C{len(chunks) + 1}",
                doc_id=document.doc_id,
                title=document.title,
                section=section,
                clause=clause,
                page=page,
                score=float(score),
                text=text,
            )
        )
    return chunks