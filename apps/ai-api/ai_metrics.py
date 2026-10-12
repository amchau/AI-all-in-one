"""Derive bounded operational metrics from ended, allowlisted AI spans."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from threading import Event
from types import MappingProxyType

from opentelemetry.context import Context
from opentelemetry.metrics import Meter
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor
from opentelemetry.trace import StatusCode

logger = logging.getLogger(__name__)

_OPERATIONS = MappingProxyType({
    "investigate": "model.investigate",
    "claims_agent.model": "model.chat",
    "claims_agent.run": "agent.run",
    "claims.agent_investigation": "claims.agent_investigation",
    "claims.hybrid_investigation": "claims.hybrid_investigation",
    "claims.investigation": "claims.investigation",
    "rag.query": "rag.query",
    "rag.source_resolution": "rag.source_resolution",
    "rag.embed": "rag.embed",
    "rag.sparse_embed": "rag.sparse_embed",
    "rag.search": "rag.search",
    "rag.rerank": "rag.rerank",
    "rag.generate": "model.generate",
    "claims.risk_advisory": "risk.advisory",
    "claims.workflow_create": "workflow.create",
    "claims.workflow_read": "workflow.read",
    "claims.workflow_disposition": "workflow.disposition",
    "claims.workflow_resume": "workflow.resume",
    "claims.workflow_stage6": "workflow.investigate",
})
_TOOLS = frozenset({
    "get_claim", "get_policy", "get_customer", "list_payments",
    "list_fraud_signals", "get_policy_evidence",
})
_MODELS = frozenset({
    "gpt-oss-20b", "embed-small", "Qdrant/bm25", "BAAI/bge-reranker-base",
})
_MODEL_ATTRIBUTES = MappingProxyType({
    "claims_agent.model": "llm.model",
    "claims_agent.run": "agent.model",
    "rag.generate": "rag.model",
    "rag.embed": "rag.embedding_model",
    "rag.sparse_embed": "rag.sparse_model",
    "rag.rerank": "rag.reranker_model",
})
_OUTCOME_ATTRIBUTES = MappingProxyType({
    "claims_agent.model": ("llm.status", frozenset({"ok", "error", "invalid_response"})),
    "claims_agent.tool": ("tool.status", frozenset({"ok", "error", "rejected"})),
    "claims.risk_advisory": ("ml.outcome", frozenset({"available", "unavailable"})),
    "claims.workflow_stage6": (
        "workflow.outcome",
        frozenset({"awaiting_human_review", "stage6_response_invalid", "stage6_dependency_failed"}),
    ),
})
_TOKEN_PREFIXES = MappingProxyType({
    "claims_agent.model": "llm",
    "rag.generate": "llm",
    "rag.embed": "embedding",
})
_TOKEN_FIELDS = ("prompt", "completion", "total")
_MEASUREMENT_CONTEXT = Context()
_NANOSECONDS_PER_SECOND = 1_000_000_000


def _operation(name: str, attributes: Mapping[str, object]) -> str | None:
    if name == "claims_agent.tool":
        tool = attributes.get("tool.name")
        return f"tool.{tool}" if isinstance(tool, str) and tool in _TOOLS else "tool._other"
    return _OPERATIONS.get(name)


def _outcome(span: ReadableSpan, attributes: Mapping[str, object]) -> str:
    if span.status.status_code is StatusCode.ERROR:
        return "error"
    outcome_spec = _OUTCOME_ATTRIBUTES.get(span.name)
    if outcome_spec is not None:
        attribute, allowed = outcome_spec
        value = attributes.get(attribute)
        if value is not None:
            return value if isinstance(value, str) and value in allowed else "_other"
    if span.name == "claims.hybrid_investigation" and (
        attributes.get("ml.advisory_status") == "unavailable"
        or attributes.get("rag.policy_evidence_status") in ("unavailable", "insufficient_evidence")
    ):
        return "partial"
    return "ok"


class AiMetricsSpanProcessor(SpanProcessor):
    """Record local measurements only; the supplied Meter's provider owns export.

    Counts describe operations, not unique investigations: parent and child
    operations are distinct series. Only model/embedding owning spans supply
    tokens. Prompt, completion, and total are separate counters; never sum total
    with its components. Missing usage is neither estimated nor filled with zero.
    Only operation, outcome, and approved model labels are exported, without
    trace exemplars. Sampling or dropped spans limits observed operation counts.
    """

    def __init__(self, meter: Meter) -> None:
        self._closed = Event()
        self._count = meter.create_counter(
            "ai.operation.count", unit="{operation}",
            description="Ended allowlisted AI operations by bounded outcome",
        )
        self._duration = meter.create_histogram(
            "ai.operation.duration", unit="s",
            description="Duration of ended allowlisted AI operations",
        )
        self._tokens = MappingProxyType({
            field: meter.create_counter(
                f"ai.token.{field}.count", unit="{token}",
                description=f"Reported {field} tokens on owning spans; total overlaps components",
            )
            for field in _TOKEN_FIELDS
        })

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        """No start-time state is retained; ended spans carry their timestamps."""

    def on_end(self, span: ReadableSpan) -> None:
        """Record only fixed dimensions; telemetry failures cannot break callers."""
        if self._closed.is_set():
            return
        try:
            source = span.attributes or {}
            operation = _operation(span.name, source)
            if operation is None:
                return
            model_key = _MODEL_ATTRIBUTES.get(span.name)
            model = source.get(model_key) if model_key is not None else None
            attributes = {
                "ai.operation": operation,
                "ai.outcome": _outcome(span, source),
                "ai.model": model if isinstance(model, str) and model in _MODELS else "_other",
            }
            self._count.add(1, attributes, context=_MEASUREMENT_CONTEXT)
            if span.start_time is not None and span.end_time is not None and span.end_time >= span.start_time:
                self._duration.record(
                    (span.end_time - span.start_time) / _NANOSECONDS_PER_SECOND,
                    attributes, context=_MEASUREMENT_CONTEXT,
                )
            self._record_tokens(span.name, source, attributes)
        except Exception:
            logger.warning("AI metrics recording failed")

    def _record_tokens(
        self, name: str, source: Mapping[str, object], attributes: dict[str, str],
    ) -> None:
        prefix = _TOKEN_PREFIXES.get(name)
        if prefix is None:
            return
        for field, counter in self._tokens.items():
            count = source.get(f"{prefix}.{field}_tokens")
            if type(count) is int and count >= 0:
                counter.add(count, attributes, context=_MEASUREMENT_CONTEXT)

    def shutdown(self) -> None:
        """Stop recording without shutting down the externally owned MeterProvider."""
        self._closed.set()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """No processor buffer exists; flush the MeterProvider separately."""
        return True