"""Contract tests for the synthetic claims service API."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

SERVICE_PATH = Path(__file__).resolve().parents[2] / "apps" / "claims-service" / "main.py"
SPEC = importlib.util.spec_from_file_location("claims_service_app", SERVICE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CLIENT = TestClient(MODULE.app)


def test_claims_service_exposes_typed_synthetic_domain_records() -> None:
    expected = {
        "/v1/claims/CL-123": ("claim_id", "policy_id", "customer_id"),
        "/v1/claims/CL-124": ("claim_id", "policy_id", "customer_id"),
        "/v1/claims/CL-125": ("claim_id", "policy_id", "customer_id"),
        "/v1/policies/HOME-002": ("policy_id", "effective_date", "declared_limit"),
        "/v1/policies/COMM-001": ("policy_id", "effective_date", "declared_limit"),
        "/v1/customers/CUST-123": ("customer_id", "display_name", "contact_status"),
        "/v1/customers/CUST-124": ("customer_id", "display_name", "contact_status"),
    }
    for path, required_keys in expected.items():
        response = CLIENT.get(path)
        assert response.status_code == 200
        assert set(required_keys) <= response.json().keys()

    payments = CLIENT.get("/v1/payments", params={"claim_id": "CL-123"})
    fraud = CLIENT.get("/v1/fraud-signals", params={"claim_id": "CL-123"})
    assert payments.status_code == 200
    assert payments.json()[0]["payment_id"] == "PAY-001"
    assert fraud.status_code == 200
    assert fraud.json()[0]["signal_id"] == "FRD-001"
    assert CLIENT.get("/v1/payments", params={"claim_id": "CL-124"}).json() == []
    assert CLIENT.get("/v1/fraud-signals", params={"claim_id": "CL-124"}).json()[0]["signal_id"] == "FRD-002"
    flood_claim = CLIENT.get("/v1/claims/CL-125").json()
    assert flood_claim["policy_id"] == "HOME-002"
    assert flood_claim["loss_date"] == "2025-03-01"
    assert "surface-water runoff" in flood_claim["reported_event"].casefold()


def test_claims_service_returns_not_found_without_echoing_unknown_id() -> None:
    response = CLIENT.get("/v1/claims/CL-SECRET-UNKNOWN")
    assert response.status_code == 404
    assert response.json() == {"detail": "Claim not found"}
    assert "CL-SECRET-UNKNOWN" not in response.text


def test_claims_service_exposes_fixed_risk_features_for_known_claims() -> None:
    expected = {
        "CL-123": {
            "assessment_complete": True,
            "features": {
                "duplicate_document_count": 0,
                "date_inconsistency_count": 1,
                "missing_required_evidence_count": 1,
                "prior_open_claim_count": 0,
                "estimate_limit_ratio": 0.5,
            },
        },
        "CL-124": {
            "assessment_complete": True,
            "features": {
                "duplicate_document_count": 0,
                "date_inconsistency_count": 0,
                "missing_required_evidence_count": 0,
                "prior_open_claim_count": 0,
                "estimate_limit_ratio": 0.25,
            },
        },
        "CL-125": {
            "assessment_complete": True,
            "features": {
                "duplicate_document_count": 0,
                "date_inconsistency_count": 0,
                "missing_required_evidence_count": 1,
                "prior_open_claim_count": 0,
                "estimate_limit_ratio": 0.5,
            },
        },
    }

    for claim_id, expected_body in expected.items():
        response = CLIENT.get(f"/v1/claims/{claim_id}/risk-features")
        assert response.status_code == 200
        assert response.json() == {"claim_id": claim_id, **expected_body}

    unknown = CLIENT.get("/v1/claims/CL-UNKNOWN/risk-features")
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "Claim not found"}


def test_claims_service_has_no_write_routes() -> None:
    methods = {
        method
        for route in MODULE.app.routes
        for method in getattr(route, "methods", set())
    }
    assert methods == {"GET", "HEAD"}
