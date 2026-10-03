from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from rag.ingestion.embed import EmbeddingError, LiteLLMEmbedder
from rag.ingestion.models import Chunk, ManifestDocument
from rag.ingestion.payload import build_qdrant_payload
from rag.ingestion.store import QdrantDenseStore, object_key_for


def test_embedder_batches_and_preserves_input_order() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.2, 0.3]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handle))
    embedder = LiteLLMEmbedder(
        client=client,
        base_url="http://litellm:4000/",
        master_key="test-secret",
        model="embed-small",
        dimensions=2,
        batch_size=2,
    )

    vectors = embedder.embed_texts(["first", "second"])

    assert vectors == [[0.1, 0.2], [0.2, 0.3]]
    assert len(requests) == 1
    assert requests[0].url == "http://litellm:4000/embeddings"
    assert requests[0].headers["authorization"] == "Bearer test-secret"
    assert json.loads(requests[0].content) == {
        "model": "embed-small",
        "input": ["first", "second"],
        "dimensions": 2,
        "encoding_format": "float",
    }
    client.close()


def test_embedder_rejects_wrong_dimension_without_exposing_response_body() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"data": [{"index": 0, "embedding": [0.1]}]},
            )
        )
    )
    embedder = LiteLLMEmbedder(
        client=client,
        base_url="http://litellm:4000",
        master_key="test-secret",
        model="embed-small",
        dimensions=2,
    )

    with pytest.raises(EmbeddingError, match="expected 2 dimensions") as error:
        embedder.embed_texts(["text"])

    assert "test-secret" not in str(error.value)
    client.close()


def test_embedder_sanitizes_litellm_http_errors() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429, text="sensitive upstream response")
        )
    )
    embedder = LiteLLMEmbedder(
        client=client,
        base_url="http://litellm:4000",
        master_key="test-secret",
        model="embed-small",
        dimensions=2,
    )

    with pytest.raises(EmbeddingError, match="HTTP 429") as error:
        embedder.embed_texts(["text"])

    assert "sensitive upstream response" not in str(error.value)
    client.close()


def test_embedder_reports_sanitized_token_usage_when_callback_is_configured() -> None:
    usage: list[dict[str, int]] = []
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "data": [{"index": 0, "embedding": [0.1, 0.2]}],
                    "usage": {
                        "prompt_tokens": 3,
                        "total_tokens": 3,
                        "completion_tokens": True,
                    },
                },
            )
        )
    )
    embedder = LiteLLMEmbedder(
        client=client,
        base_url="http://litellm:4000",
        master_key="test-secret",
        model="embed-small",
        dimensions=2,
        usage_callback=usage.append,
    )

    assert embedder.embed_texts(["query"]) == [[0.1, 0.2]]
    assert usage == [{"prompt_tokens": 3, "total_tokens": 3}]
    client.close()


def test_qdrant_payload_contains_metadata_and_chunk_lineage() -> None:
    document = ManifestDocument(
        metadata={
            "doc_id": "POL-HOME-002-v2",
            "title": "Home Policy",
            "doc_type": "policy",
            "product": "home",
            "policy_id": "HOME-002",
            "version": "2.0",
            "effective_date": "2025-01-01",
            "acl": "internal",
        },
        source="policies/home.md",
        source_sha256="a" * 64,
        pdf_name="POL-HOME-002-v2.pdf",
        pdf_sha256="b" * 64,
        pdf_path=Path("POL-HOME-002-v2.pdf"),
    )
    chunk = Chunk(
        chunk_id="00000000-0000-0000-0000-000000000001",
        document_id="POL-HOME-002-v2",
        ordinal=0,
        section="4",
        clause="4.2",
        page=3,
        token_count=12,
        content_hash="c" * 64,
        text="Water damage clause.",
    )

    payload = build_qdrant_payload(document, chunk, "d" * 64)

    assert payload == {
        "doc_id": "POL-HOME-002-v2",
        "doc_type": "policy",
        "product": "home",
        "policy_id": "HOME-002",
        "version": "2.0",
        "effective_date": "2025-01-01",
        "acl": "internal",
        "section": "4",
        "clause": "4.2",
        "page": 3,
        "content_hash": "c" * 64,
        "document_fingerprint": "d" * 64,
        "token_count": 12,
        "text": "Water damage clause.",
    }


def test_minio_object_key_uses_validated_document_identity() -> None:
    document = ManifestDocument(
        metadata={
            "doc_id": "POL-HOME-002-v2",
            "title": "Home Policy",
            "doc_type": "policy",
            "product": "home",
            "policy_id": "HOME-002",
            "version": "2.0",
            "effective_date": "2025-01-01",
            "acl": "internal",
        },
        source="policies/home.md",
        source_sha256="a" * 64,
        pdf_name="POL-HOME-002-v2.pdf",
        pdf_sha256="b" * 64,
        pdf_path=Path("POL-HOME-002-v2.pdf"),
    )

    assert object_key_for(document) == "policy/POL-HOME-002-v2/2.0.pdf"


def test_qdrant_dense_store_ensures_named_vector_and_reconciles_points() -> None:
    from qdrant_client import QdrantClient

    client = QdrantClient(":memory:")
    store = QdrantDenseStore(client, dimensions=2)
    point_id = str(uuid4())
    payload = {"document_fingerprint": "d" * 64, "doc_id": "TEST-001", "page": 1}

    try:
        store.ensure_collection()
        store.ensure_collection()
        store.upsert([point_id], [[0.1, 0.2]], [payload])

        assert store.point_ids_match([point_id], [payload]) == {point_id}
        assert store.document_point_ids("TEST-001") == {point_id}
        assert store.point_ids_match(
            [point_id], [{**payload, "document_fingerprint": "e" * 64}]
        ) == set()
        client.set_payload(
            collection_name="insurance_docs",
            payload={"page": True},
            points=[point_id],
            wait=True,
        )
        assert store.point_ids_match([point_id], [payload]) == set()
        client.delete_payload(
            collection_name="insurance_docs",
            keys=["page"],
            points=[point_id],
            wait=True,
        )
        assert store.point_ids_match([point_id], [payload]) == set()
        client.set_payload(
            collection_name="insurance_docs",
            payload={"unexpected": "stale"},
            points=[point_id],
            wait=True,
        )
        assert store.point_ids_match([point_id], [payload]) == set()
        store.upsert([point_id], [[0.1, 0.2]], [payload])

        store.delete([point_id])

        assert store.point_ids_match([point_id], [payload]) == set()
        assert store.document_point_ids("TEST-001") == set()
    finally:
        client.close()
