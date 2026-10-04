from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class SparseVectorData:
    indices: list[int]
    values: list[float]


class SparseEncodingError(RuntimeError):
    """Raised when the sparse encoder returns invalid data."""


class FastEmbedSparseEncoder:
    def __init__(
        self,
        *,
        model_name: str,
        cache_dir: Path = Path("/tmp/fastembed"),
        model: Any | None = None,
    ) -> None:
        if not model_name.strip():
            raise ValueError("sparse model name is required")
        self._model = model
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._model_lock = Lock()
        self.model_name = model_name

    def _get_model(self) -> Any:
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    from fastembed import SparseTextEmbedding

                    self._model = SparseTextEmbedding(
                        model_name=self._model_name,
                        cache_dir=str(self._cache_dir),
                    )
        return self._model

    def embed_passages(self, texts: list[str]) -> list[SparseVectorData]:
        if not texts:
            return []
        try:
            embeddings = list(self._get_model().passage_embed(texts))
            return self._convert(embeddings, len(texts))
        except SparseEncodingError:
            raise
        except Exception as error:
            raise SparseEncodingError("sparse passage encoding failed") from error

    def embed_query(self, text: str) -> SparseVectorData:
        try:
            embeddings = list(self._get_model().query_embed([text]))
            return self._convert(embeddings, 1)[0]
        except SparseEncodingError:
            raise
        except Exception as error:
            raise SparseEncodingError("sparse query encoding failed") from error

    @staticmethod
    def _convert(embeddings: list[Any], expected_count: int) -> list[SparseVectorData]:
        if len(embeddings) != expected_count:
            raise SparseEncodingError("sparse encoder returned an unexpected vector count")
        converted: list[SparseVectorData] = []
        for embedding in embeddings:
            raw_indices = getattr(embedding, "indices", None)
            raw_values = getattr(embedding, "values", None)
            if raw_indices is None or raw_values is None:
                raise SparseEncodingError("sparse encoder returned an invalid vector")
            try:
                pairs = sorted(
                    (int(index), float(value))
                    for index, value in zip(raw_indices, raw_values, strict=True)
                )
            except (TypeError, ValueError) as error:
                raise SparseEncodingError("sparse encoder returned an invalid vector") from error
            if any(index < 0 or not isfinite(value) for index, value in pairs):
                raise SparseEncodingError("sparse encoder returned an invalid vector")
            indices = [index for index, _ in pairs]
            if len(indices) != len(set(indices)):
                raise SparseEncodingError("sparse encoder returned duplicate indices")
            converted.append(
                SparseVectorData(
                    indices=indices,
                    values=[value for _, value in pairs],
                )
            )
        return converted