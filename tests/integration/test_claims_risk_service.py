from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVICE_PATH = ROOT / "apps" / "claims-risk-service" / "main.py"
ARTIFACT_PATH = ROOT / "artifacts" / "claims-risk" / "model.json"
METADATA_PATH = ROOT / "artifacts" / "claims-risk" / "metadata.json"
sys.path.insert(0, str(ROOT))


def _load_service():
    spec = importlib.util.spec_from_file_location("claims_risk_service_integration", SERVICE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_promoted_model_is_ready_and_returns_advisory_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert ARTIFACT_PATH.is_file()
    assert METADATA_PATH.is_file()
    monkeypatch.setenv("MODEL_PATH", str(ARTIFACT_PATH))
    monkeypatch.setenv("MODEL_METADATA_PATH", str(METADATA_PATH))
    service = _load_service()
    app = service.create_app()

    with TestClient(app) as client:
        assert client.get("/readyz").status_code == 200
        response = client.post(
            "/v1/claims/risk-assessments",
            json={
                "assessment_complete": True,
                "features": {
                    "duplicate_document_count": 3,
                    "date_inconsistency_count": 0,
                    "missing_required_evidence_count": 0,
                    "prior_open_claim_count": 0,
                    "estimate_limit_ratio": 0.5,
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["model_version"].startswith("stage5-")
    assert response.json()["priority_band"] in {"routine_review", "priority_review", None}
    assert response.json()["handler_triage_required"] == (response.json()["priority_band"] is None)
    assert response.json()["trace_id"]
    assert "probability" not in response.json()
