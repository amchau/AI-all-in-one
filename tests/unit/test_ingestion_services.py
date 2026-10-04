from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from rag.ingestion.embed import EmbeddingError, LiteLLMEmbedder
from rag.ingestion.models import Chunk, ManifestDocument
from rag.ingestion.payload import build_qdrant_payload
from rag.ingestion.sparse import FastEmbedSparseEncoder, SparseEncodingError
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


def test_sparse_encoder_uses_passage_and_query_paths_and_sorts_indices() -> None:
    class FakeSparseModel:
        def passage_embed(self, texts: list[str]) -> list[object]:
            assert texts == ["source clause"]
            return [type("Vector", (), {"indices": [7, 1], "values": [0.5, 1.0]})()]

        def query_embed(self, texts: list[str]) -> list[object]:
            assert texts == ["query clause"]
            return [type("Vector", (), {"indices": [9, 2], "values": [1.0, 1.0]})()]

    encoder = FastEmbedSparseEncoder(model_name="Qdrant/bm25", model=FakeSparseModel())

    passage = encoder.embed_passages(["source clause"])[0]
    query = encoder.embed_query("query clause")

    assert passage.indices == [1, 7]
    assert passage.values == [1.0, 0.5]
    assert query.indices == [2, 9]
    assert query.values == [1.0, 1.0]


def test_sparse_encoder_rejects_duplicate_indices() -> None:
    class FakeSparseModel:
        def passage_embed(self, texts: list[str]) -> list[object]:
            return [type("Vector", (), {"indices": [1, 1], "values": [0.5, 1.0]})()]

    encoder = FastEmbedSparseEncoder(model_name="Qdrant/bm25", model=FakeSparseModel())

    with pytest.raises(SparseEncodingError, match="duplicate indices"):
        encoder.embed_passages(["source clause"])


def test_sparse_encoder_rejects_blank_model_name() -> None:
    with pytest.raises(ValueError, match="model name is required"):
        FastEmbedSparseEncoder(model_name=" ", model=object())


def test_sparse_encoder_returns_no_vectors_for_empty_passages() -> None:
    class FakeSparseModel:
        def passage_embed(self, _texts: list[str]) -> list[object]:
            raise AssertionError("empty passage list must not invoke the model")

    encoder = FastEmbedSparseEncoder(model_name="Qdrant/bm25", model=FakeSparseModel())

    assert encoder.embed_passages([]) == []


def test_sparse_encoder_defers_model_initialization(monkeypatch, tmp_path: Path) -> None:
    import fastembed

    initialized: list[str] = []

    class FakeSparseModel:
        def __init__(self, *, model_name: str, cache_dir: str) -> None:
            initialized.append(model_name)
            assert cache_dir == str(tmp_path)

        def passage_embed(self, texts: list[str]) -> list[object]:
            return [type("Vector", (), {"indices": [1], "values": [1.0]})() for _ in texts]

    monkeypatch.setattr(fastembed, "SparseTextEmbedding", FakeSparseModel)
    encoder = FastEmbedSparseEncoder(
        model_name="Qdrant/bm25",
        cache_dir=tmp_path,
    )

    assert initialized == []
    assert len(encoder.embed_passages(["clause"])) == 1
    assert initialized == ["Qdrant/bm25"]


def test_sparse_encoder_wraps_model_errors() -> None:
    class FailedSparseModel:
        def passage_embed(self, _texts: list[str]) -> list[object]:
            raise RuntimeError("private encoder detail")

        def query_embed(self, _texts: list[str]) -> list[object]:
            raise RuntimeError("private encoder detail")

    encoder = FastEmbedSparseEncoder(model_name="Qdrant/bm25", model=FailedSparseModel())

    with pytest.raises(SparseEncodingError, match="passage encoding failed") as passage_error:
        encoder.embed_passages(["source clause"])
    with pytest.raises(SparseEncodingError, match="query encoding failed") as query_error:
        encoder.embed_query("query clause")

    assert "private encoder detail" not in str(passage_error.value)
    assert "private encoder detail" not in str(query_error.value)


def test_sparse_encoder_rejects_mismatched_vector_counts() -> None:
    class FakeSparseModel:
        def passage_embed(self, _texts: list[str]) -> list[object]:
            return []

    encoder = FastEmbedSparseEncoder(model_name="Qdrant/bm25", model=FakeSparseModel())

    with pytest.raises(SparseEncodingError, match="unexpected vector count"):
        encoder.embed_passages(["source clause"])


def test_sparse_encoder_allows_empty_vector_for_queries_without_terms() -> None:
    class FakeSparseModel:
        def query_embed(self, texts: list[str]) -> list[object]:
            return [type("Vector", (), {"indices": [], "values": []})()]

    encoder = FastEmbedSparseEncoder(model_name="Qdrant/bm25", model=FakeSparseModel())

    assert encoder.embed_query("!!!!").indices == []


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
    from qdrant_client import models

    client = QdrantClient(":memory:")
    store = QdrantDenseStore(client, dimensions=2)
    point_id = str(uuid4())
    payload = {"document_fingerprint": "d" * 64, "doc_id": "TEST-001", "page": 1}
    sparse_vector = models.SparseVector(indices=[1, 7], values=[0.5, 0.25])

    try:
        store.ensure_collection()
        store.ensure_collection()
        store.upsert([point_id], [[0.6, 0.8]], [sparse_vector], [payload])

        collection = client.get_collection("insurance_docs")
        assert collection.config.params.vectors["dense"].size == 2
        assert "sparse" in collection.config.params.sparse_vectors
        stored_point = client.retrieve(
            collection_name="insurance_docs",
            ids=[point_id],
            with_payload=True,
            with_vectors=True,
        )[0]
        assert stored_point.vector["dense"] == pytest.approx([0.6, 0.8])
        assert list(stored_point.vector["sparse"].indices) == [1, 7]

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
        store.upsert([point_id], [[0.6, 0.8]], [sparse_vector], [payload])

        store.delete([point_id])

        assert store.point_ids_match([point_id], [payload]) == set()
        assert store.document_point_ids("TEST-001") == set()
    finally:
        client.close()


def test_qdrant_sparse_schema_upgrade_preserves_existing_dense_points() -> None:
    from qdrant_client import QdrantClient
    from qdrant_client import models

    client = QdrantClient(":memory:")
    point_id = str(uuid4())
    client.create_collection(
        collection_name="insurance_docs",
        vectors_config={
            "dense": models.VectorParams(size=2, distance=models.Distance.COSINE)
        },
    )
    client.upsert(
        collection_name="insurance_docs",
        points=[models.PointStruct(id=point_id, vector={"dense": [0.6, 0.8]})],
        wait=True,
    )
    store = QdrantDenseStore(client, dimensions=2)

    try:
        store.ensure_collection()

        collection = client.get_collection("insurance_docs")
        retained_point = client.retrieve(
            collection_name="insurance_docs",
            ids=[point_id],
            with_vectors=True,
        )[0]
        assert "sparse" in collection.config.params.sparse_vectors
        assert retained_point.vector["dense"] == pytest.approx([0.6, 0.8])
    finally:
        client.close()
