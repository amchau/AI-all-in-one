from __future__ import annotations

from dataclasses import replace
from math import isfinite
from typing import Any, Protocol

import httpx

from rag.retrieval.models import RetrievedChunk


class Reranker(Protocol):
    model_name: str

    def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]: ...


class RerankingError(RuntimeError):
    """Raised when the reranker fails or returns invalid ranking data."""


class TeiReranker:
    def __init__(
        self,
        *,
        client: httpx.Client,
        base_url: str,
        model_name: str = "BAAI/bge-reranker-base",
    ) -> None:
        if not base_url.strip() or not model_name.strip():
            raise ValueError("reranker URL and model name are required")
        self._client = client
        self._url = f"{base_url.rstrip('/')}/rerank"
        self.model_name = model_name

    def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if not chunks:
            return []
        try:
            response = self._client.post(
                self._url,
                json={
                    "query": query,
                    "texts": [chunk.text for chunk in chunks],
                    "raw_scores": False,
                    "truncate": True,
                },
            )
        except httpx.RequestError as error:
            raise RerankingError("TEI reranker request failed") from error
        if response.is_error:
            raise RerankingError(
                f"TEI reranker request failed with HTTP {response.status_code}"
            )
        try:
            payload: Any = response.json()
        except ValueError as error:
            raise RerankingError("TEI reranker returned invalid JSON") from error
        if not isinstance(payload, list) or len(payload) != len(chunks):
            raise RerankingError("TEI reranker returned an invalid ranking")

        scores: dict[int, float] = {}
        for item in payload:
            if not isinstance(item, dict):
                raise RerankingError("TEI reranker returned an invalid ranking")
            index = item.get("index")
            score = item.get("score")
            if (
                type(index) is not int
                or index < 0
                or index >= len(chunks)
                or index in scores
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not isfinite(score)
            ):
                raise RerankingError("TEI reranker returned an invalid ranking")
            scores[index] = float(score)
        if set(scores) != set(range(len(chunks))):
            raise RerankingError("TEI reranker returned an invalid ranking")

        ranked = [
            (
                index,
                replace(
                    chunk,
                    score=scores[index],
                    hybrid_score=(
                        chunk.hybrid_score
                        if chunk.hybrid_score is not None
                        else chunk.score
                    ),
                    rerank_score=scores[index],
                ),
            )
            for index, chunk in enumerate(chunks)
        ]
        return [chunk for _, chunk in sorted(ranked, key=lambda item: (-item[1].score, item[0]))]