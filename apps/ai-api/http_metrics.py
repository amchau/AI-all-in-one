"""Record low-cardinality HTTP server metrics for the API."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics._internal.exemplar import AlwaysOffExemplarFilter
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource


_KNOWN_METHODS = frozenset(
    {"CONNECT", "DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT", "TRACE"}
)


def normalize_method(method: str) -> str:
    """Bound method labels so arbitrary request methods cannot grow cardinality."""
    normalized = method.upper()
    return normalized if normalized in _KNOWN_METHODS else "_OTHER"


class HttpServerMetrics:
    """Record request counts and durations using bounded attributes."""

    def __init__(self, meter: Meter) -> None:
        self._request_count = meter.create_counter(
            "http.server.request.count",
            unit="{request}",
            description="Number of HTTP server requests",
        )
        self._request_duration = meter.create_histogram(
            "http.server.request.duration",
            unit="s",
            description="HTTP server request duration",
        )

    def record(
        self,
        *,
        method: str,
        route_template: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        attributes = {
            "http.request.method": normalize_method(method),
            "http.route": route_template,
            "http.response.status_code": min(max(status_code, 100), 599),
        }
        self._request_count.add(1, attributes)
        self._request_duration.record(duration_seconds, attributes)


class HttpMetricsMiddleware:
    """Record request metrics after the router resolves a bounded route template."""

    def __init__(self, app: Any, *, metrics: HttpServerMetrics) -> None:
        self._app = app
        self._metrics = metrics

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        started = time.perf_counter()
        status_code = 500

        async def record_status(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 500))
            await send(message)

        try:
            await self._app(scope, receive, record_status)
        finally:
            route = scope.get("route")
            route_template = getattr(route, "path", "_unmatched")
            self._metrics.record(
                method=str(scope.get("method", "_OTHER")),
                route_template=route_template,
                status_code=status_code,
                duration_seconds=time.perf_counter() - started,
            )


def configure_metrics(
    endpoint: str | None,
    service_name: str,
) -> tuple[MeterProvider, HttpServerMetrics]:
    """Export API metrics over OTLP/HTTP using only bounded service identity."""
    metric_readers = (
        [
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=endpoint),
            )
        ]
        if endpoint
        else []
    )
    provider = MeterProvider(
        resource=Resource.create({"service.name": service_name}),
        metric_readers=metric_readers,
        exemplar_filter=AlwaysOffExemplarFilter(),
    )
    return provider, HttpServerMetrics(provider.get_meter(service_name))