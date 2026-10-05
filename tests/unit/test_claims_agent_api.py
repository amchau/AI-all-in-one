from __future__ import annotations

from datetime import date
import os
from pathlib import Path
import sys
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx
import pytest

API_MODULE_DIR = Path(__file__).resolve().parents[2] / "apps" / "ai-api"
sys.path.insert(0, str(API_MODULE_DIR))
with patch.dict(os.environ, {"AI_API_ENV_FILE": ""}), patch(
    "opentelemetry.sdk.trace.TracerProvider.add_span_processor"
):
    import main

from agents.claims.models import AgentInvestigationOutput


@pytest.fixture
def api_client(monkeypatch):
    monkeypatch.setattr(main.settings, "postgres_query_password", "test-db-password")
    monkeypatch.setattr(main.settings, "litellm_master_key", "test-litellm-key")
    with TestClient(main.app) as client:
        yield client


def test_agent_endpoint_returns_typed_result_and_trace(api_client, monkeypatch) -> None:
    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def investigate(self, request):
            return AgentInvestigationOutput(
                claim_id=request.claim_id,
                status="insufficient_evidence",
                summary="",
                summary_source_ids=[],
                findings=[],
                unresolved_questions=["What date did the incident occur?"],
                sources=[],
                model="test-model",
                tool_calls=1,
                latency_ms=10,
            )

    monkeypatch.setattr(main, "ClaimsAgent", FakeAgent)
    response = api_client.post(
        "/v1/claims/agent-investigations",
        json={"claim_id": "CL-123", "narrative": "Water entered the home overnight."},
    )

    assert response.status_code == 200
    assert response.json()["claim_id"] == "CL-123"
    assert response.json()["status"] == "insufficient_evidence"
    assert len(response.json()["trace_id"]) == 32


def test_agent_endpoint_sanitizes_dependency_errors(api_client, monkeypatch) -> None:
    class FailingAgent:
        def __init__(self, **kwargs) -> None:
            pass

        def investigate(self, request):
            raise main.AgentDependencyError("provider secret detail")

    monkeypatch.setattr(main, "ClaimsAgent", FailingAgent)
    response = api_client.post(
        "/v1/claims/agent-investigations",
        json={"claim_id": "CL-123", "narrative": "Water entered the home overnight."},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Claims agent dependency failed"
    assert "provider secret" not in response.text


def test_agent_rag_evidence_uses_claim_policy_and_loss_date(monkeypatch) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "claim_id": "CL-123",
                "policy_id": "HOME-002",
                "customer_id": "CUST-123",
                "loss_date": "2025-03-01",
                "reported_event": "Water entered the home.",
                "status": "under_review",
            },
        )
    )
    client = httpx.Client(transport=transport)
    captured = {}

    def fake_query(request):
        captured["request"] = request
        return type("Result", (), {"chunks": []})()

    monkeypatch.setattr(main, "execute_rag_query", fake_query)
    monkeypatch.setattr(main.settings, "claims_service_url", "http://claims-service:8080")

    sources = main.execute_agent_rag_evidence(
        client,
        "CL-123",
        "HOME-002",
        "Water entered the home overnight.",
    )

    request = captured["request"]
    assert sources == []
    assert request.policy_id == "HOME-002"
    assert request.loss_date == date(2025, 3, 1)
    assert request.guidance_as_of == date(2025, 3, 1)
    assert request.mode == "hybrid_rerank"
    assert request.top_k == 5
    assert "Water entered the home overnight." in request.question


def test_agent_rag_evidence_rejects_policy_mismatch(monkeypatch) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "claim_id": "CL-123",
                "policy_id": "HOME-002",
                "customer_id": "CUST-123",
                "loss_date": "2025-03-01",
                "reported_event": "Water entered the home.",
                "status": "under_review",
            },
        )
    )
    client = httpx.Client(transport=transport)
    with pytest.raises(main.AgentOutputError, match="does not match"):
        main.execute_agent_rag_evidence(
            client,
            "CL-123",
            "HOME-OTHER",
            "Water entered the home overnight.",
        )
