"""Tests for bounded HTTP server metric dimensions."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

API_MODULE_DIR = Path(__file__).resolve().parents[2] / "apps" / "ai-api"
sys.path.insert(0, str(API_MODULE_DIR))

from http_metrics import HttpMetricsMiddleware, HttpServerMetrics, normalize_method


def test_http_metrics_use_route_templates_and_bounded_methods() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    metrics = HttpServerMetrics(provider.get_meter("test"))

    metrics.record(
        method="PURGE",
        route_template="/v1/claims/{claim_id}",
        status_code=200,
        duration_seconds=0.25,
    )

    metric_data = reader.get_metrics_data()
    assert metric_data is not None
    observed = {
        metric.name: metric.data.data_points[0]
        for resource_metrics in metric_data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    }

    assert observed["http.server.request.count"].value == 1
    assert observed["http.server.request.duration"].sum == 0.25
    attributes = dict(observed["http.server.request.count"].attributes)
    assert attributes == {
        "http.request.method": "_OTHER",
        "http.route": "/v1/claims/{claim_id}",
        "http.response.status_code": 200,
    }
    assert "CL-123" not in repr(attributes)


def test_normalize_method_maps_unrecognized_values_to_other() -> None:
    assert normalize_method("GET") == "GET"
    assert normalize_method("made-up-user-method") == "_OTHER"


def test_asgi_middleware_records_route_template_and_response_status() -> None:
    recorded: list[dict[str, Any]] = []

    async def app(scope, _receive, send) -> None:
        scope["route"] = SimpleNamespace(path="/v1/claims/{claim_id}")
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message: dict[str, Any]) -> None:
        return None

    middleware = HttpMetricsMiddleware(
        app,
        metrics=SimpleNamespace(record=lambda **values: recorded.append(values)),
    )
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/v1/claims/CL-123",
    }

    asyncio.run(middleware(scope, receive, send))

    assert len(recorded) == 1
    assert recorded[0]["route_template"] == "/v1/claims/{claim_id}"
    assert recorded[0]["status_code"] == 404
    assert "CL-123" not in repr(recorded)


def test_asgi_middleware_uses_constant_for_unmatched_paths() -> None:
    recorded: list[dict[str, Any]] = []

    async def app(_scope, _receive, _send) -> None:
        return None

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message: dict[str, Any]) -> None:
        return None

    middleware = HttpMetricsMiddleware(
        app,
        metrics=SimpleNamespace(record=lambda **values: recorded.append(values)),
    )
    asyncio.run(
        middleware(
            {"type": "http", "method": "GET", "path": "/private/CL-123"},
            receive,
            send,
        )
    )

    assert recorded[0]["route_template"] == "_unmatched"
    assert "CL-123" not in repr(recorded)


def test_asgi_middleware_passes_non_http_scopes_without_metrics() -> None:
    recorded: list[dict[str, Any]] = []
    handled: list[str] = []

    async def app(scope, _receive, _send) -> None:
        handled.append(scope["type"])

    async def receive() -> dict[str, Any]:
        return {"type": "lifespan", "event": "lifespan.startup"}

    async def send(_message: dict[str, Any]) -> None:
        return None

    middleware = HttpMetricsMiddleware(
        app,
        metrics=SimpleNamespace(record=lambda **values: recorded.append(values)),
    )
    asyncio.run(middleware({"type": "lifespan"}, receive, send))

    assert handled == ["lifespan"]
    assert recorded == []


def test_asgi_middleware_records_server_error_when_app_raises() -> None:
    recorded: list[dict[str, Any]] = []

    async def app(_scope, _receive, _send) -> None:
        raise RuntimeError("private failure detail")

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message: dict[str, Any]) -> None:
        return None

    middleware = HttpMetricsMiddleware(
        app,
        metrics=SimpleNamespace(record=lambda **values: recorded.append(values)),
    )

    with pytest.raises(RuntimeError, match="private failure detail"):
        asyncio.run(
            middleware(
                {"type": "http", "method": "GET", "path": "/unmatched"},
                receive,
                send,
            )
        )

    assert recorded[0]["status_code"] == 500
    assert recorded[0]["route_template"] == "_unmatched"
    assert "private failure detail" not in repr(recorded)