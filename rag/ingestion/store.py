from __future__ import annotations

from io import BytesIO
from pathlib import PurePosixPath
import re
from typing import Any

from rag.ingestion.models import ManifestDocument
from rag.ingestion.sparse import SparseVectorData


_PATH_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def object_key_for(document: ManifestDocument) -> str:
    """Return the stable MinIO key defined by the Stage 2 data model."""
    metadata = document.metadata
    components = (
        str(metadata["doc_type"]),
        str(metadata["doc_id"]),
        str(metadata["version"]),
    )
    if any(_PATH_COMPONENT.fullmatch(value) is None for value in components):
        raise ValueError("document identity contains an unsafe object-key component")
    return PurePosixPath(components[0], components[1], f"{components[2]}.pdf").as_posix()


class MinioPdfStore:
    def __init__(self, client: Any, bucket: str = "documents") -> None:
        self._client = client
        self._bucket = bucket

    def ensure_bucket(self) -> None:
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    def exists(self, object_key: str) -> bool:
        from minio.error import S3Error

        try:
            self._client.stat_object(self._bucket, object_key)
            return True
        except S3Error as error:
            if error.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                return False
            raise

    def upload(self, document: ManifestDocument, object_key: str) -> None:
        content = document.pdf_path.read_bytes()
        self._client.put_object(
            self._bucket,
            object_key,
            BytesIO(content),
            length=len(content),
            content_type="application/pdf",
        )


class QdrantDenseStore:
    def __init__(
        self,
        client: Any,
        collection: str = "insurance_docs",
        dimensions: int = 1536,
    ) -> None:
        self._client = client
        self._collection = collection
        self._dimensions = dimensions

    def ensure_collection(self) -> None:
        from qdrant_client import models

        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config={
                    "dense": models.VectorParams(
                        size=self._dimensions,
                        distance=models.Distance.COSINE,
                    )
                },
                sparse_vectors_config={
                    "sparse": models.SparseVectorParams(
                        modifier=models.Modifier.IDF,
                    )
                },
            )
            return

        collection = self._client.get_collection(self._collection)
        vectors = collection.config.params.vectors
        if not isinstance(vectors, dict) or "dense" not in vectors:
            raise RuntimeError("Qdrant collection lacks the required named dense vector")
        dense = vectors["dense"]
        if dense.size != self._dimensions or dense.distance.value != "Cosine":
            raise RuntimeError("Qdrant dense vector configuration does not match ingestion")
        sparse_vectors = collection.config.params.sparse_vectors or {}
        if "sparse" not in sparse_vectors:
            self._client.create_vector_name(
                collection_name=self._collection,
                vector_name="sparse",
                vector_name_config=models.SparseVectorNameConfig(
                    sparse=models.SparseVectorConfig(
                        modifier=models.Modifier.IDF,
                    ),
                ),
            )
            collection = self._client.get_collection(self._collection)
            sparse_vectors = collection.config.params.sparse_vectors or {}
        sparse = sparse_vectors.get("sparse")
        if sparse is None or sparse.modifier != models.Modifier.IDF:
            raise RuntimeError("Qdrant sparse vector configuration does not match ingestion")

    def point_ids_match(
        self,
        point_ids: list[str],
        payloads: list[dict[str, str | int | None]],
    ) -> set[str]:
        if not point_ids:
            return set()
        if len(point_ids) != len(payloads):
            raise ValueError("Qdrant point IDs and expected payloads must have equal lengths")
        points = self._client.retrieve(
            collection_name=self._collection,
            ids=point_ids,
            with_payload=True,
            with_vectors=False,
        )
        expected_by_id = dict(zip(point_ids, payloads, strict=True))
        matching_ids: set[str] = set()
        for point in points:
            point_id = str(point.id)
            actual_payload = dict(point.payload or {})
            expected_payload = expected_by_id[point_id]
            if actual_payload.keys() != expected_payload.keys():
                continue
            if all(
                type(actual_payload[key]) is type(expected_payload[key])
                and actual_payload[key] == expected_payload[key]
                for key in expected_payload
            ):
                matching_ids.add(point_id)
        return matching_ids

    def document_point_ids(self, document_id: str) -> set[str]:
        from qdrant_client import models

        scroll_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="doc_id",
                    match=models.MatchValue(value=document_id),
                )
            ]
        )
        point_ids: set[str] = set()
        offset: Any = None
        while True:
            points, offset = self._client.scroll(
                collection_name=self._collection,
                scroll_filter=scroll_filter,
                limit=256,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            point_ids.update(str(point.id) for point in points)
            if offset is None:
                return point_ids

    def upsert(
        self,
        point_ids: list[str],
        vectors: list[list[float]],
        sparse_vectors: list[SparseVectorData],
        payloads: list[dict[str, Any]],
    ) -> None:
        from qdrant_client import models

        if not (len(point_ids) == len(vectors) == len(sparse_vectors) == len(payloads)):
            raise ValueError("Qdrant point IDs, vectors, sparse vectors, and payloads must have equal lengths")
        if not point_ids:
            return
        points = [
            models.PointStruct(
                id=point_id,
                vector={
                    "dense": vector,
                    "sparse": models.SparseVector(
                        indices=sparse_vector.indices,
                        values=sparse_vector.values,
                    ),
                },
                payload=payload,
            )
            for point_id, vector, sparse_vector, payload in zip(
                point_ids,
                vectors,
                sparse_vectors,
                payloads,
                strict=True,
            )
        ]
        self._client.upsert(collection_name=self._collection, points=points, wait=True)

    def delete(self, point_ids: list[str]) -> None:
        from qdrant_client import models

        if point_ids:
            self._client.delete(
                collection_name=self._collection,
                points_selector=models.PointIdsList(points=point_ids),
                wait=True,
            )