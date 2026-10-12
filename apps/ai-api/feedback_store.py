"""Persist private feedback with 30-day retention and provisional aggregate suppression."""

import asyncio
import logging
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from opentelemetry.instrumentation.utils import suppress_instrumentation
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

Rating = Literal["useful", "needs_review", "unable_to_assess"]
ReasonTag = Literal["grounding", "completeness", "relevance", "safety", "other"]
RATINGS: tuple[Rating, ...] = ("useful", "needs_review", "unable_to_assess")
REASON_TAGS: tuple[ReasonTag, ...] = (
    "grounding", "completeness", "relevance", "safety", "other"
)
DELETE_EXPIRED_SQL = """
DELETE FROM ai_feedback.feedback
WHERE created_at <= CURRENT_TIMESTAMP - INTERVAL '30 days'
"""
INSERT_SQL = """
INSERT INTO ai_feedback.feedback
    (feedback_id, rating, reason_tags, note, workflow_id, trace_id)
VALUES (%s, %s, %s, %s, %s, %s)
RETURNING feedback_id, created_at
"""


class FeedbackSettings(BaseModel):
    """Explicit connection values; never load or reuse ambient credentials."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    db: str = Field(min_length=1)
    password: SecretStr


class FeedbackReceipt(BaseModel):
    """Public write acknowledgement without private content or references."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    feedback_id: UUID
    created_at: datetime


class FeedbackStore:
    """Short-lived connections using only the dedicated claims_feedback role."""

    def __init__(self, settings: FeedbackSettings) -> None:
        self.settings = settings

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(
            host=self.settings.host, port=self.settings.port,
            dbname=self.settings.db, user="claims_feedback",
            password=self.settings.password.get_secret_value(),
            connect_timeout=5, options="-c statement_timeout=5000",
            row_factory=dict_row,
        )

    def create(
        self, *, rating: Rating, reason_tags: tuple[ReasonTag, ...] = (),
        note: str | None = None, workflow_id: UUID | None = None,
        trace_id: str | None = None,
    ) -> FeedbackReceipt | None:
        """Delete expired data and insert atomically; never propagate DB errors."""
        try:
            with suppress_instrumentation(), self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(DELETE_EXPIRED_SQL)
                    cursor.execute(INSERT_SQL, (
                        uuid4(), rating, list(reason_tags), note, workflow_id, trace_id
                    ))
                    record = cursor.fetchone()
                    receipt = FeedbackReceipt.model_validate(record)
            return receipt
        except Exception as error:
            logger.error("Feedback write failed (%s)", type(error).__name__)
            return None

    def cleanup_expired(self) -> int | None:
        """Delete expired rows even without writes; return count or safe failure."""
        try:
            with suppress_instrumentation(), self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(DELETE_EXPIRED_SQL)
                    deleted = cursor.rowcount
            return deleted
        except Exception as error:
            logger.error("Feedback cleanup failed (%s)", type(error).__name__)
            return None

async def run_feedback_cleanup(
    store: FeedbackStore, stop: asyncio.Event, *, interval_seconds: float = 3600,
) -> None:
    """Parent lifespan starts this loop and sets stop on shutdown; no model calls."""
    if interval_seconds <= 0:
        raise ValueError("Feedback cleanup interval must be positive")
    while not stop.is_set():
        try:
            await run_in_threadpool(store.cleanup_expired)
        except Exception as error:
            logger.error("Feedback cleanup failed (%s)", type(error).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue