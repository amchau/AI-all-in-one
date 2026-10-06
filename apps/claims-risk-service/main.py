from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import math
import os
from pathlib import Path
import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Tracer
from pydantic import BaseModel, ConfigDict, Field

from ml.claims_risk.dataset import ClaimRiskFeatures
from ml.claims_risk.predictor import RiskPredictor, load_predictor

logger = logging.getLogger(__name__)


class AssessmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    assessment_complete: bool
    features: ClaimRiskFeatures


class AssessmentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    priority_band: Literal["routine_review", "priority_review"] | None
    handler_triage_required: bool
    triage_reason: Literal[
        "assessment_incomplete",
        "near_decision_threshold",
    ] | None
    model_version: str
    trace_id: str | None = None


class HealthResponse(BaseModel):
    ok: bool


def create_app(
    predictor: RiskPredictor | None = None,
    tracer: Tracer | None = None,
    configure_otel: bool = False,
) -> FastAPI:
    active_tracer = tracer or _create_tracer(configure_otel)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.predictor = predictor
        if app.state.predictor is None:
            try:
                app.state.predictor = _load_default_predictor()
            except HTTPException:
                logger.error("risk model failed to load; service remains unready")
        yield

    app = FastAPI(
        title="Synthetic Claims Risk Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.predictor = predictor

    @app.exception_handler(RequestValidationError)
    async def invalid_request_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid assessment request"},
        )

    @app.get("/livez", response_model=HealthResponse)
    def livez() -> HealthResponse:
        return HealthResponse(ok=True)

    @app.get("/readyz", response_model=HealthResponse)
    def readyz() -> HealthResponse:
        if app.state.predictor is None:
            raise HTTPException(status_code=503, detail="Model is unavailable")
        return HealthResponse(ok=True)

    @app.post("/v1/claims/risk-assessments", response_model=AssessmentOutput)
    def assess_claim(request: AssessmentInput) -> AssessmentOutput:
        if not request.assessment_complete:
            model_version = (
                app.state.predictor.model_version
                if app.state.predictor is not None
                else "unavailable"
            )
            with active_tracer.start_as_current_span(
                "ml.claims_risk.inference",
                kind=SpanKind.INTERNAL,
            ) as span:
                span.set_attribute("ml.model_version", model_version)
                span.set_attribute("ml.outcome", "assessment_incomplete")
                response = AssessmentOutput(
                    priority_band=None,
                    handler_triage_required=True,
                    triage_reason="assessment_incomplete",
                    model_version=model_version,
                )
                return response.model_copy(update={"trace_id": _current_trace_id()})
        active_predictor = app.state.predictor
        if active_predictor is None:
            raise HTTPException(status_code=503, detail="Risk assessment unavailable")
        started_at = time.perf_counter()
        outcome = "scored"
        with active_tracer.start_as_current_span(
            "ml.claims_risk.inference",
            kind=SpanKind.INTERNAL,
        ) as span:
            try:
                probability = active_predictor.predict_probability(request.features)
                if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
                    raise ValueError("predictor returned invalid probability")
            except Exception as error:
                span.set_attribute("ml.model_version", active_predictor.model_version)
                span.set_attribute("ml.outcome", "dependency_error")
                logger.error("risk inference failed: %s", type(error).__name__)
                raise HTTPException(status_code=503, detail="Risk assessment unavailable") from error

            if abs(probability - active_predictor.threshold) <= active_predictor.triage_margin:
                outcome = "handler_triage"
                response = AssessmentOutput(
                    priority_band=None,
                    handler_triage_required=True,
                    triage_reason="near_decision_threshold",
                    model_version=active_predictor.model_version,
                )
            else:
                priority_band = (
                    "priority_review"
                    if probability >= active_predictor.threshold
                    else "routine_review"
                )
                response = AssessmentOutput(
                    priority_band=priority_band,
                    handler_triage_required=False,
                    triage_reason=None,
                    model_version=active_predictor.model_version,
                )
            latency_ms = round((time.perf_counter() - started_at) * 1000)
            span.set_attribute("ml.model_version", active_predictor.model_version)
            span.set_attribute("ml.latency_ms", latency_ms)
            span.set_attribute("ml.outcome", outcome)
            return response.model_copy(update={"trace_id": _current_trace_id()})

    return app


def _create_tracer(configure_otel: bool) -> Tracer:
    if configure_otel and not isinstance(trace.get_tracer_provider(), TracerProvider):
        resource = Resource.create({"service.name": "claims-risk-service"})
        provider = TracerProvider(resource=resource)
        exporter_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if exporter_endpoint:
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=exporter_endpoint))
            )
        trace.set_tracer_provider(provider)
    return trace.get_tracer("claims-risk-service")


def _model_paths() -> tuple[Path, Path]:
    model_path = Path(os.getenv("MODEL_PATH", "/app/model/model.json"))
    metadata_path = Path(os.getenv("MODEL_METADATA_PATH", "/app/model/metadata.json"))
    return model_path, metadata_path


def _load_default_predictor() -> RiskPredictor:
    model_path, metadata_path = _model_paths()
    try:
        return load_predictor(model_path, metadata_path)
    except ValueError as error:
        raise HTTPException(status_code=503, detail="Risk assessment unavailable") from error


def _current_trace_id() -> str | None:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return f"{span_context.trace_id:032x}"


app = create_app(configure_otel=True)
