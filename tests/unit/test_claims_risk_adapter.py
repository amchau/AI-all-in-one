"""Tests for the claims-agent adapter to Stage 5 risk services."""

from __future__ import annotations

import httpx
import pytest

from agents.claims.risk import assess_claim_risk


def _feature_payload() -> dict[str, object]:
    return {
        "claim_id": "CL-123",
        "assessment_complete": True,
        "features": {
            "duplicate_document_count": 0,
            "date_inconsistency_count": 1,
            "missing_required_evidence_count": 1,
            "prior_open_claim_count": 0,
            "estimate_limit_ratio": 0.5,
        },
    }


def test_risk_adapter_passes_fixture_features_and_returns_advisory() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=_feature_payload())
        return httpx.Response(
            200,
            json={
                "priority_band": "routine_review",
                "handler_triage_required": False,
                "triage_reason": None,
                "model_version": "stage5-test",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = assess_claim_risk(
            client,
            claim_id="CL-123",
            claims_service_url="http://claims-service",
            risk_service_url="http://risk-service",
        )

    assert result.status == "available"
    assert result.priority_band == "routine_review"
    assert [request.method for request in requests] == ["GET", "POST"]
    assert requests[1].read() == (
        b'{"assessment_complete":true,"features":{"duplicate_document_count":0,'
        b'"date_inconsistency_count":1,"missing_required_evidence_count":1,'
        b'"prior_open_claim_count":0,"estimate_limit_ratio":0.5}}'
    )


@pytest.mark.parametrize(
    ("feature_status", "risk_status", "expected_reason"),
    [
        (503, 200, "feature_service_unavailable"),
        (200, 503, "risk_service_unavailable"),
    ],
)
def test_risk_adapter_isolates_service_failures(
    feature_status: int,
    risk_status: int,
    expected_reason: str,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            if feature_status != 200:
                return httpx.Response(feature_status)
            return httpx.Response(200, json=_feature_payload())
        return httpx.Response(risk_status)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = assess_claim_risk(
            client,
            claim_id="CL-123",
            claims_service_url="http://claims-service",
            risk_service_url="http://risk-service",
        )

    assert result.status == "unavailable"
    assert result.unavailable_reason == expected_reason
    assert result.priority_band is None


def test_risk_adapter_marks_inconsistent_success_response_invalid() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=_feature_payload())
        return httpx.Response(
            200,
            json={
                "priority_band": None,
                "handler_triage_required": False,
                "triage_reason": None,
                "model_version": "stage5-test",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = assess_claim_risk(
            client,
            claim_id="CL-123",
            claims_service_url="http://claims-service",
            risk_service_url="http://risk-service",
        )

    assert result.status == "unavailable"
    assert result.unavailable_reason == "invalid_response"