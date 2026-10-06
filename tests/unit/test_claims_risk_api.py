from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from typing import Any

from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVICE_PATH = ROOT / "apps" / "claims-risk-service" / "main.py"
sys.path.insert(0, str(ROOT))


class FakePredictor:
    model_version = "stage5-test"
    threshold = 0.7
    triage_margin = 0.05

    def __init__(self, probability: float) -> None:
        self.probability = probability
        self.calls = 0

    def predict_probability(self, features: Any) -> float:
        self.calls += 1
        return self.probability


class FailingPredictor(FakePredictor):
    def predict_probability(self, features: Any) -> float:
        raise RuntimeError("sensitive feature details must not reach the response")


def _load_service():
    spec = importlib.util.spec_from_file_location("claims_risk_service_test", SERVICE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "assessment_complete": True,
        "features": {
            "duplicate_document_count": 2,
            "date_inconsistency_count": 0,
            "missing_required_evidence_count": 0,
            "prior_open_claim_count": 0,
            "estimate_limit_ratio": 0.5,
        },
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    ("probability", "expected_band"),
    [(0.9, "priority_review"), (0.2, "routine_review")],
)
def test_assessment_returns_priority_without_probability_or_features(
    probability: float,
    expected_band: str,
) -> None:
    service = _load_service()
    predictor = FakePredictor(probability)
    client = TestClient(service.create_app(predictor))

    response = client.post("/v1/claims/risk-assessments", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["priority_band"] == expected_band
    assert body["handler_triage_required"] is False
    assert body["model_version"] == "stage5-test"
    assert "probability" not in body
    assert "features" not in body
    assert predictor.calls == 1


def test_near_threshold_assessment_requires_handler_triage() -> None:
    service = _load_service()
    predictor = FakePredictor(0.72)
    client = TestClient(service.create_app(predictor))

    response = client.post("/v1/claims/risk-assessments", json=_payload())

    assert response.status_code == 200
    assert response.json()["handler_triage_required"] is True
    assert response.json()["priority_band"] is None
    assert response.json()["triage_reason"] == "near_decision_threshold"


def test_incomplete_assessment_is_triaged_without_model_call() -> None:
    service = _load_service()
    predictor = FakePredictor(0.9)
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    client = TestClient(
        service.create_app(predictor, tracer=provider.get_tracer("test"))
    )

    response = client.post(
        "/v1/claims/risk-assessments",
        json=_payload(assessment_complete=False),
    )

    assert response.status_code == 200
    assert response.json()["handler_triage_required"] is True
    assert response.json()["priority_band"] is None
    assert response.json()["triage_reason"] == "assessment_incomplete"
    assert predictor.calls == 0
    assert response.json()["trace_id"]
    assert len(exporter.get_finished_spans()) == 1
    assert exporter.get_finished_spans()[0].attributes["ml.outcome"] == "assessment_incomplete"


def test_unknown_or_out_of_range_fields_are_rejected() -> None:
    service = _load_service()
    client = TestClient(service.create_app(FakePredictor(0.9)))

    extra_field = _payload(customer_id="CUST-123")
    invalid_feature = _payload()
    invalid_feature["features"]["estimate_limit_ratio"] = 2.1
    invalid_completeness = _payload(assessment_complete="false")

    extra_response = client.post("/v1/claims/risk-assessments", json=extra_field)
    range_response = client.post("/v1/claims/risk-assessments", json=invalid_feature)

    assert extra_response.status_code == 422
    assert "CUST-123" not in extra_response.text
    assert range_response.status_code == 422
    assert client.post(
        "/v1/claims/risk-assessments", json=invalid_completeness
    ).status_code == 422


def test_model_failure_is_sanitized_and_traced_without_input_features() -> None:
    service = _load_service()
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    client = TestClient(
        service.create_app(FailingPredictor(0.9), tracer=provider.get_tracer("test"))
    )

    response = client.post("/v1/claims/risk-assessments", json=_payload())

    assert response.status_code == 503
    assert response.json() == {"detail": "Risk assessment unavailable"}
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert set(spans[0].attributes) == {
        "ml.model_version",
        "ml.outcome",
    }
    assert "duplicate_document_count" not in spans[0].attributes


def test_health_endpoints_are_available() -> None:
    service = _load_service()
    client = TestClient(service.create_app(FakePredictor(0.9)))

    assert client.get("/livez").json() == {"ok": True}
    assert client.get("/readyz").json() == {"ok": True}
