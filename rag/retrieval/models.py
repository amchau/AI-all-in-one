from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class SourceDocument:
    doc_id: str
    title: str
    doc_type: str
    policy_id: str | None
    product: str
    effective_date: date
    version: str
    acl: str


class RagQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=5, max_length=1200)
    policy_id: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    loss_date: date
    guidance_as_of: date | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    mode: Literal["dense", "hybrid", "hybrid_rerank"] = "dense"


class Citation(BaseModel):
    ref: str
    chunk_id: str
    doc_id: str
    title: str
    section: str | None
    clause: str | None
    page: int


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    ref: str
    doc_id: str
    title: str
    section: str | None
    clause: str | None
    page: int
    score: float
    text: str
    dense_score: float | None = None
    hybrid_score: float | None = None
    rerank_score: float | None = None

    def citation(self) -> Citation:
        return Citation(
            ref=self.ref,
            chunk_id=self.chunk_id,
            doc_id=self.doc_id,
            title=self.title,
            section=self.section,
            clause=self.clause,
            page=self.page,
        )


@dataclass(frozen=True)
class GroundedAnswer:
    status: str
    answer: str
    citations: list[Citation]
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class RagQueryResult:
    answer: GroundedAnswer
    chunks: list[RetrievedChunk]
    model: str
    latency_ms: int
    mode: Literal["dense", "hybrid", "hybrid_rerank"] = "dense"