from __future__ import annotations

from collections.abc import Callable
from math import isfinite
from typing import Any

import httpx


class EmbeddingError(RuntimeError):
    """Raised for failed or invalid LiteLLM embedding responses."""


class LiteLLMEmbedder:
    def __init__(
        self,
        *,
        client: httpx.Client,
        base_url: str,
        master_key: str,
        model: str = "embed-small",
        dimensions: int = 1536,
        batch_size: int = 32,
        usage_callback: Callable[[dict[str, int]], None] | None = None,
    ) -> None:
        if not base_url or not master_key or not model:
            raise ValueError("LiteLLM URL, master key, and model are required")
        if dimensions <= 0 or batch_size <= 0:
            raise ValueError("dimensions and batch_size must be positive")
        self._client = client
        self._url = f"{base_url.rstrip('/')}/embeddings"
        self._master_key = master_key
        self._model = model
        self._dimensions = dimensions
        self._batch_size = batch_size
        self._usage_callback = usage_callback

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        headers = {"Authorization": f"Bearer {self._master_key}"}
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            try:
                response = self._client.post(
                    self._url,
                    headers=headers,
                    json={
                        "model": self._model,
                        "input": batch,
                        "dimensions": self._dimensions,
                        "encoding_format": "float",
                    },
                )
            except httpx.RequestError as error:
                raise EmbeddingError("LiteLLM embeddings request failed") from error
            if response.is_error:
                raise EmbeddingError(
                    f"LiteLLM embeddings request failed with HTTP {response.status_code}"
                )
            try:
                payload: Any = response.json()
            except ValueError as error:
                raise EmbeddingError("LiteLLM returned invalid JSON") from error
            usage = payload.get("usage") if isinstance(payload, dict) else None
            if self._usage_callback is not None and isinstance(usage, dict):
                token_counts = {
                    name: value
                    for name in ("prompt_tokens", "total_tokens")
                    if type(value := usage.get(name)) is int and value >= 0
                }
                if token_counts:
                    self._usage_callback(token_counts)
            vectors.extend(self._parse_batch(payload, len(batch)))
        return vectors

    def _parse_batch(self, payload: Any, expected_count: int) -> list[list[float]]:
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or len(data) != expected_count:
            raise EmbeddingError("LiteLLM returned an unexpected embedding count")
        indexed: dict[int, list[float]] = {}
        for item in data:
            if not isinstance(item, dict):
                raise EmbeddingError("LiteLLM returned an invalid embedding record")
            index = item.get("index")
            raw_vector = item.get("embedding")
            if (
                not isinstance(index, int)
                or index in indexed
                or not isinstance(raw_vector, list)
            ):
                raise EmbeddingError("LiteLLM returned an invalid embedding record")
            if len(raw_vector) != self._dimensions:
                raise EmbeddingError(f"expected {self._dimensions} dimensions from LiteLLM")
            if any(
                not isinstance(value, (int, float)) or not isfinite(value)
                for value in raw_vector
            ):
                raise EmbeddingError("LiteLLM returned a non-numeric embedding")
            indexed[index] = [float(value) for value in raw_vector]
        if set(indexed) != set(range(expected_count)):
            raise EmbeddingError("LiteLLM returned invalid embedding indexes")
        return [indexed[index] for index in range(expected_count)]