"""Verify bounded AI metrics from existing spans without external services."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from opentelemetry.context import Context
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics._internal.exemplar import AlwaysOffExemplarFilter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.trace import Status, StatusCode

API_MODULE_DIR = Path(__file__).resolve().parents[2] / "apps" / "ai-api"
sys.path.insert(0, str(API_MODULE_DIR))

from ai_metrics import AiMetricsSpanProcessor

Telemetry = tuple[AiMetricsSpanProcessor, InMemoryMetricReader]


@pytest.fixture
def telemetry() -> Iterator[Telemetry]:
    reader = InMemoryMetricReader()
    provider = MeterProvider(
        metric_readers=[reader], exemplar_filter=AlwaysOffExemplarFilter()
    )
    processor = AiMetricsSpanProcessor(provider.get_meter("test"))
    yield processor, reader
    processor.shutdown()
    provider.shutdown()


def ended_span(
    name: str,
    attributes: dict[str, Any] | None = None,
    status: StatusCode = StatusCode.UNSET,
    start_time: int | None = 1_000_000_000,
    end_time: int | None = 1_250_000_000,
) -> ReadableSpan:
    return ReadableSpan(
        name=name,
        attributes=attributes,
        status=Status(status),
        start_time=start_time,
        end_time=end_time,
    )


def observed_metrics(reader: InMemoryMetricReader) -> dict[str, list[Any]]:
    data = reader.get_metrics_data()
    if data is None:
        return {}
    return {
        metric.name: list(metric.data.data_points)
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }


@pytest.mark.parametrize(
    ("span_name", "operation"),
    [
        ("investigate", "model.investigate"),
        ("claims_agent.model", "model.chat"),
        ("claims_agent.run", "agent.run"),
        ("claims.agent_investigation", "claims.agent_investigation"),
        ("claims.hybrid_investigation", "claims.hybrid_investigation"),
        ("claims.investigation", "claims.investigation"),
        ("rag.query", "rag.query"),
        ("rag.source_resolution", "rag.source_resolution"),
        ("rag.embed", "rag.embed"),
        ("rag.sparse_embed", "rag.sparse_embed"),
        ("rag.search", "rag.search"),
        ("rag.rerank", "rag.rerank"),
        ("rag.generate", "model.generate"),
        ("claims.risk_advisory", "risk.advisory"),
        ("claims.workflow_create", "workflow.create"),
        ("claims.workflow_read", "workflow.read"),
        ("claims.workflow_disposition", "workflow.disposition"),
        ("claims.workflow_resume", "workflow.resume"),
        ("claims.workflow_stage6", "workflow.investigate"),
    ],
)
def test_existing_spans_have_fixed_operations(
    telemetry: Telemetry,
    span_name: str,
    operation: str,
) -> None:
    processor, reader = telemetry
    processor.on_end(ended_span(span_name))
    metrics = observed_metrics(reader)
    count = metrics["ai.operation.count"][0]
    duration = metrics["ai.operation.duration"][0]
    assert count.value == duration.count == 1
    assert duration.sum == 0.25
    assert dict(count.attributes) == dict(duration.attributes) == {
        "ai.operation": operation,
        "ai.outcome": "ok",
        "ai.model": "_other",
    }


@pytest.mark.parametrize(
    "tool_name",
    ["get_claim", "get_policy", "get_customer", "list_payments",
     "list_fraud_signals", "get_policy_evidence"],
)
def test_allowlisted_tools_are_distinct_operations(telemetry: Telemetry, tool_name: str) -> None:
    processor, reader = telemetry
    processor.on_end(ended_span("claims_agent.tool", {"tool.name": tool_name}))
    point = observed_metrics(reader)["ai.operation.count"][0]
    assert point.attributes["ai.operation"] == f"tool.{tool_name}"


@pytest.mark.parametrize(
    ("span_name", "attribute", "model"),
    [
        ("claims_agent.model", "llm.model", "gpt-oss-20b"),
        ("claims_agent.run", "agent.model", "gpt-oss-20b"),
        ("rag.generate", "rag.model", "gpt-oss-20b"),
        ("rag.embed", "rag.embedding_model", "embed-small"),
        ("rag.sparse_embed", "rag.sparse_model", "Qdrant/bm25"),
        ("rag.rerank", "rag.reranker_model", "BAAI/bge-reranker-base"),
    ],
)
def test_known_models_are_preserved(
    telemetry: Telemetry, span_name: str, attribute: str, model: str,
) -> None:
    processor, reader = telemetry
    processor.on_end(ended_span(span_name, {attribute: model}))
    assert observed_metrics(reader)["ai.operation.count"][0].attributes["ai.model"] == model


@pytest.mark.parametrize("unknown", ["private-model-CL-123", "", ("gpt-oss-20b",), True, 42])
def test_unknown_values_never_become_labels(telemetry: Telemetry, unknown: object) -> None:
    processor, reader = telemetry
    attributes = {
        "llm.model": unknown,
        "llm.status": unknown,
        "tool.name": unknown,
        "tool.status": unknown,
        "ml.model_version": "private-version-CL-123",
        "workflow.id": "private-workflow-123",
        "claim.id": "CL-123",
        "question": "private narrative",
        "rag.candidate_doc_ids": ("private-document",),
    }
    processor.on_end(ended_span("claims_agent.model", attributes))
    processor.on_end(ended_span("claims_agent.tool", attributes))
    processor.on_end(ended_span("claims.risk_advisory", attributes))
    points = observed_metrics(reader)["ai.operation.count"]
    assert len(points) == 3
    for point in points:
        assert set(point.attributes) == {"ai.operation", "ai.outcome", "ai.model"}
        assert point.attributes["ai.model"] == "_other"
        assert point.attributes["ai.outcome"] == "_other" if point.attributes["ai.operation"] != "risk.advisory" else point.attributes["ai.outcome"] == "ok"
    assert {point.attributes["ai.operation"] for point in points} == {
        "model.chat", "tool._other", "risk.advisory",
    }
    assert "private" not in repr(points)
    assert "CL-123" not in repr(points)


@pytest.mark.parametrize(
    ("span_name", "attributes", "outcome"),
    [
        ("claims_agent.model", {"llm.status": "error"}, "error"),
        ("claims_agent.model", {"llm.status": "invalid_response"}, "invalid_response"),
        ("claims_agent.tool", {"tool.status": "error"}, "error"),
        ("claims_agent.tool", {"tool.status": "rejected"}, "rejected"),
        ("claims_agent.tool", {"tool.status": "started"}, "_other"),
        ("claims.risk_advisory", {"ml.outcome": "available"}, "available"),
        ("claims.risk_advisory", {"ml.outcome": "unavailable"}, "unavailable"),
        ("claims.workflow_stage6", {"workflow.outcome": "awaiting_human_review"}, "awaiting_human_review"),
        ("claims.workflow_stage6", {"workflow.outcome": "stage6_response_invalid"}, "stage6_response_invalid"),
        ("claims.workflow_stage6", {"workflow.outcome": "stage6_dependency_failed"}, "stage6_dependency_failed"),
        ("claims.hybrid_investigation", {"ml.advisory_status": "unavailable"}, "partial"),
        ("claims.hybrid_investigation", {"rag.policy_evidence_status": "unavailable"}, "partial"),
        ("claims.hybrid_investigation", {"rag.policy_evidence_status": "insufficient_evidence"}, "partial"),
    ],
)
def test_caught_failures_and_partial_results_are_not_success(
    telemetry: Telemetry, span_name: str, attributes: dict[str, str], outcome: str,
) -> None:
    processor, reader = telemetry
    processor.on_end(ended_span(span_name, attributes))
    assert observed_metrics(reader)["ai.operation.count"][0].attributes["ai.outcome"] == outcome


def test_sdk_error_overrides_claimed_success_and_unrelated_status_is_ignored(telemetry: Telemetry) -> None:
    processor, reader = telemetry
    processor.on_end(ended_span("claims_agent.model", {"llm.status": "ok"}, StatusCode.ERROR))
    processor.on_end(ended_span("rag.search", {"llm.status": "error"}, StatusCode.OK))
    assert {point.attributes["ai.outcome"] for point in observed_metrics(reader)["ai.operation.count"]} == {"error", "ok"}


@pytest.mark.parametrize(
    ("span_name", "prefix"),
    [("claims_agent.model", "llm"), ("rag.generate", "llm"), ("rag.embed", "embedding")],
)
def test_actual_tokens_are_separate_not_summed_with_total(
    telemetry: Telemetry, span_name: str, prefix: str,
) -> None:
    processor, reader = telemetry
    processor.on_end(ended_span(span_name, {
        f"{prefix}.prompt_tokens": 7,
        f"{prefix}.completion_tokens": 3,
        f"{prefix}.total_tokens": 10,
    }))
    metrics = observed_metrics(reader)
    for field, expected in (("prompt", 7), ("completion", 3), ("total", 10)):
        points = metrics[f"ai.token.{field}.count"]
        assert len(points) == 1
        assert points[0].value == expected
        assert points[0].attributes == metrics["ai.operation.count"][0].attributes


@pytest.mark.parametrize("invalid", [None, -1, True, False, "12", 1.5, float("nan"), float("inf"), (12,)])
def test_invalid_usage_is_not_exported(telemetry: Telemetry, invalid: object) -> None:
    processor, reader = telemetry
    processor.on_end(ended_span("claims_agent.model", {
        "llm.prompt_tokens": invalid,
        "llm.completion_tokens": invalid,
        "llm.total_tokens": invalid,
    }))
    assert set(observed_metrics(reader)) == {"ai.operation.count", "ai.operation.duration"}


def test_zero_usage_is_actual_and_missing_usage_is_not_invented(telemetry: Telemetry) -> None:
    processor, reader = telemetry
    processor.on_end(ended_span("rag.embed", {"embedding.prompt_tokens": 0}))
    metrics = observed_metrics(reader)
    assert metrics["ai.token.prompt.count"][0].value == 0
    assert "ai.token.total.count" not in metrics
    assert "ai.token.completion.count" not in metrics


def test_parent_and_unrelated_spans_do_not_duplicate_usage(telemetry: Telemetry) -> None:
    processor, reader = telemetry
    attributes = {"llm.total_tokens": 10, "embedding.total_tokens": 10}
    for name in ("claims_agent.run", "claims.hybrid_investigation", "rag.query", "claims_agent.tool", "claims.risk_advisory", "claims.workflow_stage6", "HTTP POST", "llm.arbitrary"):
        processor.on_end(ended_span(name, attributes))
    processor.on_end(ended_span("claims_agent.model", attributes))
    points = observed_metrics(reader)["ai.token.total.count"]
    assert len(points) == 1
    assert points[0].value == 10


@pytest.mark.parametrize(("start_time", "end_time"), [(None, 10), (10, None), (10, 9)])
def test_invalid_timestamps_count_but_do_not_emit_latency(
    telemetry: Telemetry, start_time: int | None, end_time: int | None,
) -> None:
    processor, reader = telemetry
    processor.on_end(ended_span("rag.search", start_time=start_time, end_time=end_time))
    metrics = observed_metrics(reader)
    assert metrics["ai.operation.count"][0].value == 1
    assert "ai.operation.duration" not in metrics


def test_zero_duration_is_valid(telemetry: Telemetry) -> None:
    processor, reader = telemetry
    processor.on_end(ended_span("rag.search", start_time=0, end_time=0))
    assert observed_metrics(reader)["ai.operation.duration"][0].sum == 0


def test_unknown_span_names_and_large_private_payload_are_ignored(telemetry: Telemetry) -> None:
    processor, reader = telemetry
    for index in range(10_000):
        processor.on_end(ended_span(f"rag.search.private-{index}", {"text": "private"}))
    assert observed_metrics(reader) == {}


def test_real_sdk_nested_spans_concurrency_and_lifecycle(telemetry: Telemetry) -> None:
    processor, reader = telemetry
    provider = TracerProvider()
    provider.add_span_processor(processor)
    tracer = provider.get_tracer("test")

    def run() -> None:
        with tracer.start_as_current_span("claims_agent.run", context=Context()):
            with tracer.start_as_current_span("claims_agent.model") as span:
                span.set_attribute("llm.total_tokens", 10)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: run(), range(20)))
    assert provider.force_flush(timeout_millis=1000) is True
    metrics = observed_metrics(reader)
    assert sum(point.value for point in metrics["ai.operation.count"]) == 40
    assert metrics["ai.token.total.count"][0].value == 200
    assert all(not point.exemplars for points in metrics.values() for point in points)
    processor.on_start(Mock(), parent_context=Context())
    processor.shutdown()
    processor.shutdown()
    assert processor.force_flush(timeout_millis=1) is True
    processor.on_end(ended_span("rag.search"))
    assert sum(point.value for point in observed_metrics(reader)["ai.operation.count"]) == 40
    provider.shutdown()


def test_instrument_failure_does_not_break_span_end_or_log_private_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    meter = Mock()
    meter.create_counter.return_value.add.side_effect = RuntimeError("private narrative")
    processor = AiMetricsSpanProcessor(meter)
    processor.on_end(ended_span("claims_agent.model"))
    assert "AI metrics recording failed" in caplog.text
    assert "private narrative" not in caplog.text
    processor.shutdown()