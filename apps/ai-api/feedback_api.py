"""Strict private feedback endpoints, distinct from workflow dispositions."""

import logging
import re
from typing import Self
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

from feedback_store import FeedbackReceipt, FeedbackStore, Rating, ReasonTag

logger = logging.getLogger(__name__)


class FeedbackRequest(BaseModel):
    """Immutable strict JSON boundary; JSON UUID strings are explicitly supported."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    rating: Rating
    reason_tags: tuple[ReasonTag, ...] = Field(default=(), max_length=5)
    note: str | None = Field(default=None, max_length=500)
    workflow_id: UUID | None = None
    trace_id: str | None = None

    @field_validator("reason_tags")
    @classmethod
    def unique_reasons(cls, value: tuple[ReasonTag, ...]) -> tuple[ReasonTag, ...]:
        if len(set(value)) != len(value):
            raise ValueError("Invalid feedback reasons")
        return value

    @field_validator("trace_id")
    @classmethod
    def valid_trace(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if re.fullmatch(r"[0-9a-fA-F]{32}", value) is None or int(value, 16) == 0:
            raise ValueError("Invalid feedback reference")
        return value.lower()

    @model_validator(mode="after")
    def exclusive_reference(self) -> Self:
        if self.workflow_id is not None and self.trace_id is not None:
            raise ValueError("Invalid feedback reference")
        return self


def _unavailable() -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Feedback service unavailable"})


def create_feedback_router(store: FeedbackStore) -> APIRouter:
    """Parent includes router; summary minimum five remains a provisional policy."""
    router = APIRouter(prefix="/v1/feedback", tags=["feedback"])

    @router.post("", status_code=201, response_model=FeedbackReceipt)
    async def create_feedback(request: Request) -> FeedbackReceipt | JSONResponse:
        try:
            payload = FeedbackRequest.model_validate_json(await request.body())
        except (ValueError, TypeError):
            return JSONResponse(status_code=422, content={"detail": "Invalid feedback request"})
        try:
            receipt = await run_in_threadpool(store.create, **payload.model_dump())
        except Exception as error:
            logger.error("Feedback write failed (%s)", type(error).__name__)
            return _unavailable()
        return receipt if receipt is not None else _unavailable()

    return router