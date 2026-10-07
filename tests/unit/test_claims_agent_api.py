"""API contract tests for claims-agent routes and evidence integration."""

from __future__ import annotations

from datetime import date
import os
from pathlib import Path
import sys
from types import SimpleNamespace
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


@pytest.mark.parametrize("risk_status", [200, 503])
def test_hybrid_endpoint_keeps_risk_advisory_separate_and_isolates_failure(
    api_client,
    monkeypatch,
    risk_status: int,
) -> None:
    service_calls = []
    original_client = httpx.Client

    def service_response(request: httpx.Request) -> httpx.Response:
        service_calls.append(request)
        if request.method == "GET" and request.url.path == "/v1/claims/CL-123":
            return httpx.Response(
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
        if request.method == "GET" and request.url.path.endswith("/risk-features"):
            return httpx.Response(
                200,
                json={
                    "claim_id": "CL-123",
                    "assessment_complete": True,
                    "features": {
                        "duplicate_document_count": 0,
                        "date_inconsistency_count": 1,
                        "missing_required_evidence_count": 1,
                        "prior_open_claim_count": 0,
                        "estimate_limit_ratio": 0.5,
                    },
                },
            )
        if request.method == "POST" and request.url.path == "/v1/claims/risk-assessments":
            return httpx.Response(
                risk_status,
                json=(
                    {
                        "priority_band": "priority_review",
                        "handler_triage_required": False,
                        "triage_reason": None,
                        "model_version": "stage5-test",
                        "trace_id": "a" * 32,
                    }
                    if risk_status == 200
                    else {"detail": "sensitive upstream error"}
                ),
            )
        return httpx.Response(404)

    monkeypatch.setattr(
        main.httpx,
        "Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(service_response),
            **kwargs,
        ),
    )
    monkeypatch.setattr(main.settings, "claims_service_url", "http://claims-service")
    monkeypatch.setattr(main.settings, "claims_risk_service_url", "http://claims-risk-service")
    monkeypatch.setattr(
        main,
        "execute_rag_query",
        lambda *args, **kwargs: SimpleNamespace(chunks=[]),
    )
    observed_agent = {}

    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            observed_agent["kwargs"] = kwargs

        def investigate(self, request, *, initial_sources):
            observed_agent["request"] = request
            observed_agent["initial_sources"] = initial_sources
            return AgentInvestigationOutput(
                claim_id=request.claim_id,
                status="answered",
                summary="The claim record reports water damage.",
                summary_source_ids=["claim:CL-123"],
                findings=[],
                unresolved_questions=[],
                sources=initial_sources,
                model="test-model",
                tool_calls=1,
                latency_ms=10,
            )

    monkeypatch.setattr(main, "ClaimsAgent", FakeAgent)
    response = api_client.post(
        "/v1/claims/hybrid-investigations",
        json={"claim_id": "CL-123", "narrative": "Water entered the home overnight."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["investigation"]["summary"] == "The claim record reports water damage."
    assert body["policy_evidence_status"] == "insufficient_evidence"
    if risk_status == 200:
        assert body["risk_assessment"] == {
            "status": "available",
            "priority_band": "priority_review",
            "handler_triage_required": False,
            "triage_reason": None,
            "model_version": "stage5-test",
            "unavailable_reason": None,
        }
    else:
        assert body["risk_assessment"] == {
            "status": "unavailable",
            "priority_band": None,
            "handler_triage_required": None,
            "triage_reason": None,
            "model_version": None,
            "unavailable_reason": "risk_service_unavailable",
        }
    assert len(body["trace_id"]) == 32
    assert len(service_calls) == 3
    risk_request = next(
        request for request in service_calls if request.url.path == "/v1/claims/risk-assessments"
    )
    assert risk_request.read() == (
        b'{"assessment_complete":true,"features":{"duplicate_document_count":0,'
        b'"date_inconsistency_count":1,"missing_required_evidence_count":1,'
        b'"prior_open_claim_count":0,"estimate_limit_ratio":0.5}}'
    )
    assert "risk" not in " ".join(observed_agent["kwargs"].keys()).lower()


@pytest.mark.parametrize("rag_failure", [False, True])
def test_hybrid_endpoint_retrieves_policy_evidence_before_agent(
    api_client,
    monkeypatch,
    rag_failure: bool,
) -> None:
    original_client = httpx.Client
    observed = {}

    def service_response(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/claims/CL-123"
        return httpx.Response(
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

    monkeypatch.setattr(
        main.httpx,
        "Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(service_response),
            **kwargs,
        ),
    )
    monkeypatch.setattr(main.settings, "claims_service_url", "http://claims-service")
    monkeypatch.setattr(main.settings, "claims_risk_service_url", "http://claims-risk-service")

    def fake_rag_query(request, *, structured_investigation=False, retrieval_only=False):
        observed["rag_request"] = request
        observed["retrieval_only"] = retrieval_only
        if rag_failure:
            raise main.QueryDependencyError("private vector-store error")
        return SimpleNamespace(
            chunks=[
                SimpleNamespace(
                    chunk_id="water-clarification-1",
                    doc_id="END-HOME-002-WATER-LIMIT-02",
                    title="Home Water Damage Clarification Endorsement",
                    section="1",
                    clause=None,
                    page=3,
                    text="Sudden accidental escape of water from a fixed installation remains covered.",
                ),
                SimpleNamespace(
                    chunk_id="water-procedure-1",
                    doc_id="PROC-HOME-WATER-EVIDENCE-01",
                    title="Home Water Damage Evidence Procedure",
                    section="3",
                    clause=None,
                    page=2,
                    text="Establish the cause and likely duration from inspection evidence.",
                ),
            ]
        )

    monkeypatch.setattr(main, "execute_rag_query", fake_rag_query)
    monkeypatch.setattr(
        main,
        "assess_claim_risk",
        lambda *args, **kwargs: main.HybridRiskAssessment(
            status="available",
            priority_band="routine_review",
            handler_triage_required=False,
            triage_reason=None,
            model_version="stage5-test",
            unavailable_reason=None,
        ),
    )
    observed["agent_sources"] = []

    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def investigate(self, request, *, initial_sources):
            observed["agent_sources"] = initial_sources
            source = initial_sources[0] if initial_sources else None
            claim_source = main.InvestigationSource(
                source_id="claim:CL-123",
                source_type="claim",
                record_id="CL-123",
                label="Synthetic claim record CL-123",
                facts={"reported_event": "Water entered after a reported pipe failure."},
            )
            policy_source = main.InvestigationSource(
                source_id="policy:HOME-002",
                source_type="policy",
                record_id="HOME-002",
                label="Synthetic policy record HOME-002",
                facts={
                    "status": "active",
                    "effective_date": "2024-01-01",
                    "declared_limit": "GBP 250000",
                },
            )
            return AgentInvestigationOutput(
                claim_id=request.claim_id,
                status="answered" if source else "insufficient_evidence",
                summary=(
                    "The water loss is covered during the insured period. No schedule limitations "
                    "are present, and the endorsement allows assessment despite the unknown duration."
                    if source
                    else ""
                ),
                summary_source_ids=(
                    [claim_source.source_id, policy_source.source_id, source.source_id]
                    if source
                    else []
                ),
                findings=[],
                unresolved_questions=[],
                sources=[*initial_sources, claim_source, policy_source] if source else [],
                model="test-model",
                tool_calls=0,
                latency_ms=10,
            )

    monkeypatch.setattr(main, "ClaimsAgent", FakeAgent)
    response = api_client.post(
        "/v1/claims/hybrid-investigations",
        json={
            "claim_id": "CL-123",
            "narrative": "A domestic pipe failed overnight and water damaged the home; duration is unknown.",
            "guidance_as_of": "2026-01-01",
        },
    )

    assert response.status_code == 200
    assert observed["retrieval_only"] is True
    assert observed["rag_request"].policy_id == "HOME-002"
    assert "domestic pipe failed overnight" in observed["rag_request"].question
    assert observed["rag_request"].loss_date == date(2025, 3, 1)
    assert observed["rag_request"].guidance_as_of == date(2026, 1, 1)
    assert observed["rag_request"].mode == "hybrid_rerank"
    assert observed["rag_request"].top_k == 8
    if rag_failure:
        assert observed["agent_sources"] == []
        assert response.json()["policy_evidence_status"] == "unavailable"
        assert response.json()["policy_evidence_unavailable_reason"] == "retrieval_dependency_failed"
        assert response.json()["investigation"]["status"] == "insufficient_evidence"
    else:
        sources_by_document = {
            source.facts["doc_id"]: source for source in observed["agent_sources"]
        }
        assert set(sources_by_document) == {
            "END-HOME-002-WATER-LIMIT-02",
            "PROC-HOME-WATER-EVIDENCE-01",
        }
        assert response.json()["policy_evidence_status"] == "retrieved"
        assert response.json()["policy_evidence_unavailable_reason"] is None
        investigation = response.json()["investigation"]
        assert investigation["status"] == "insufficient_evidence"
        assert investigation["summary"] == ""
        assert investigation["summary_source_ids"] == []
        assert investigation["findings"] == []
        assert investigation["unresolved_questions"] == [
            "Does the policy schedule list the applicable endorsement and limits?",
            "What expiry or lapse information confirms the policy was in force on the loss date?",
            "What evidence establishes the cause and duration of the reported water damage?",
        ]


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


@pytest.mark.parametrize(
    "unsafe_summary",
    [
        "The policy schedule does not list repair costs, so those are not covered.",
        "The claim is covered under the policy's escape of water clause.",
        "The endorsement states that the claim will be assessed on available evidence.",
    ],
)
def test_hybrid_evidence_guard_abstains_on_unsupported_policy_claims(
    unsafe_summary: str,
) -> None:
    policy_evidence = main.InvestigationSource(
        source_id="policy_evidence:water-clarification",
        source_type="policy_evidence",
        record_id="water-clarification",
        label="Home Water Damage Clarification Endorsement, section 3",
        facts={
            "doc_id": "END-HOME-002-WATER-LIMIT-02",
            "text": "Assess cause and duration from evidence; do not require rejection when uncertain.",
        },
    )
    policy_record = main.InvestigationSource(
        source_id="policy:HOME-002",
        source_type="policy",
        record_id="HOME-002",
        label="Synthetic policy record HOME-002",
        facts={"status": "active", "effective_date": "2024-01-01"},
    )
    investigation = AgentInvestigationOutput(
        claim_id="CL-123",
        status="answered",
        summary=unsafe_summary,
        summary_source_ids=[policy_evidence.source_id, policy_record.source_id],
        findings=[],
        unresolved_questions=[],
        sources=[policy_evidence, policy_record],
        model="test-model",
        tool_calls=0,
        latency_ms=1,
    )

    result = main.enforce_hybrid_evidence_constraints(investigation)

    assert result.status == "insufficient_evidence"
    assert result.summary == ""
    assert result.summary_source_ids == []
    assert result.findings == []
    assert result.unresolved_questions == [
        "Does the policy schedule list the applicable endorsement and limits?",
        "What expiry or lapse information confirms the policy was in force on the loss date?",
        "What evidence establishes the cause and duration of the reported water damage?",
    ]


def test_hybrid_evidence_guard_keeps_flood_extension_applicability_unresolved() -> None:
    flood_evidence = main.InvestigationSource(
        source_id="policy_evidence:flood-extension",
        source_type="policy_evidence",
        record_id="flood-extension",
        label="Home Flood Extension Endorsement, section 1",
        facts={
            "doc_id": "END-HOME-002-FLOOD-EXT-01",
            "text": (
                "This synthetic endorsement applies only when it is listed on the HOME-002 schedule. "
                "It replaces clause 4.2 for direct flood losses."
            ),
        },
    )
    policy_record = main.InvestigationSource(
        source_id="policy:HOME-002",
        source_type="policy",
        record_id="HOME-002",
        label="Synthetic policy record HOME-002",
        facts={"status": "active", "effective_date": "2024-01-01"},
    )
    investigation = AgentInvestigationOutput(
        claim_id="CL-123",
        status="answered",
        summary="The flood extension applies to surface-water losses on this claim.",
        summary_source_ids=[flood_evidence.source_id, policy_record.source_id],
        findings=[],
        unresolved_questions=[],
        sources=[flood_evidence, policy_record],
        model="test-model",
        tool_calls=0,
        latency_ms=1,
    )

    result = main.enforce_hybrid_evidence_constraints(investigation)

    assert result.status == "insufficient_evidence"
    assert result.summary == ""
    assert result.summary_source_ids == []
    assert result.findings == []
    assert "Does the policy schedule list the applicable endorsement and limits?" in result.unresolved_questions


def test_hybrid_flood_route_abstains_when_extension_schedule_is_missing(
    api_client,
    monkeypatch,
) -> None:
    original_client = httpx.Client

    def service_response(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/claims/CL-123"
        return httpx.Response(
            200,
            json={
                "claim_id": "CL-123",
                "policy_id": "HOME-002",
                "customer_id": "CUST-123",
                "loss_date": "2025-03-01",
                "reported_event": "Water entered after a reported pipe failure.",
                "status": "under_review",
            },
        )

    monkeypatch.setattr(
        main.httpx,
        "Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(service_response),
            **kwargs,
        ),
    )
    monkeypatch.setattr(main.settings, "claims_service_url", "http://claims-service")
    observed = {}

    def fake_rag_query(request, *, retrieval_only=False):
        observed["request"] = request
        assert retrieval_only is True
        return SimpleNamespace(
            chunks=[
                SimpleNamespace(
                    chunk_id="flood-extension-1",
                    doc_id="END-HOME-002-FLOOD-EXT-01",
                    title="Home Flood Extension Endorsement",
                    section="1",
                    clause=None,
                    page=1,
                    text=(
                        "This extension applies only when listed on the HOME-002 schedule. "
                        "It replaces clause 4.2 for direct flood losses."
                    ),
                )
            ]
        )

    monkeypatch.setattr(main, "execute_rag_query", fake_rag_query)
    monkeypatch.setattr(
        main,
        "assess_claim_risk",
        lambda *args, **kwargs: main.HybridRiskAssessment(
            status="available",
            priority_band="routine_review",
            handler_triage_required=False,
            triage_reason=None,
            model_version="stage5-test",
            unavailable_reason=None,
        ),
    )

    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            pass

        def investigate(self, request, *, initial_sources):
            source_id = initial_sources[0].source_id
            return AgentInvestigationOutput(
                claim_id=request.claim_id,
                status="answered",
                summary="The flood extension applies to direct surface-water losses.",
                summary_source_ids=[source_id],
                findings=[],
                unresolved_questions=[],
                sources=initial_sources,
                model="test-model",
                tool_calls=0,
                latency_ms=1,
            )

    monkeypatch.setattr(main, "ClaimsAgent", FakeAgent)
    response = api_client.post(
        "/v1/claims/hybrid-investigations",
        json={
            "claim_id": "CL-123",
            "narrative": "Surface-water runoff entered the home and caused direct flood damage.",
            "guidance_as_of": "2026-01-01",
        },
    )

    assert response.status_code == 200
    assert observed["request"].top_k == 8
    body = response.json()
    assert body["policy_evidence_status"] == "retrieved"
    assert body["investigation"]["status"] == "insufficient_evidence"
    assert body["investigation"]["summary"] == ""
    assert body["investigation"]["findings"] == []
    assert "Does the policy schedule list the applicable endorsement and limits?" in (
        body["investigation"]["unresolved_questions"]
    )


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

    def fake_query(request, *, retrieval_only=False):
        captured["request"] = request
        captured["retrieval_only"] = retrieval_only
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
    assert captured["retrieval_only"] is True
    assert "Water entered the home overnight." in request.question


def test_agent_rag_evidence_uses_requested_guidance_date(monkeypatch) -> None:
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

    def fake_query(request, *, retrieval_only=False):
        captured["request"] = request
        captured["retrieval_only"] = retrieval_only
        return type("Result", (), {"chunks": []})()

    monkeypatch.setattr(main, "execute_rag_query", fake_query)
    monkeypatch.setattr(main.settings, "claims_service_url", "http://claims-service:8080")

    main.execute_agent_rag_evidence(
        client,
        "CL-123",
        "HOME-002",
        "Water entered the home overnight.",
        date(2026, 1, 1),
    )

    assert captured["request"].guidance_as_of == date(2026, 1, 1)
    assert captured["retrieval_only"] is True


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


def test_policy_evidence_retrieval_maps_ranked_chunks_to_sources(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        main,
        "execute_rag_query",
        lambda request, **kwargs: captured.update(request=request, **kwargs)
        or type(
            "Result",
            (),
            {
                "chunks": [
                    type(
                        "Chunk",
                        (),
                        {
                            "chunk_id": "chunk-1",
                            "doc_id": "POL-HOME-002-v2",
                            "title": "Home Policy",
                            "section": "4",
                            "clause": "4.2",
                            "page": 3,
                            "text": "Flood damage is covered subject to the stated limit.",
                        },
                    )()
                ]
            },
        )(),
    )
    claim = main.SyntheticClaimContext(
        claim_id="CL-123",
        policy_id="HOME-002",
        customer_id="CUST-123",
        loss_date=date(2025, 3, 1),
        reported_event="Water entered the home.",
        status="under_review",
    )

    with httpx.Client() as client:
        sources, status, reason = main.execute_policy_evidence_retrieval(
            client,
            claim_id="CL-123",
            policy_id="HOME-002",
            narrative="Flood water entered the home overnight.",
            guidance_as_of=date(2026, 1, 1),
            claim_context=claim,
        )

    assert status == "retrieved"
    assert reason is None
    assert sources[0].source_id == "policy_evidence:chunk-1"
    assert sources[0].facts["text"] == "Flood damage is covered subject to the stated limit."
    assert captured["retrieval_only"] is True
    assert captured["request"].mode == "hybrid_rerank"
    assert captured["request"].guidance_as_of == date(2026, 1, 1)


@pytest.mark.parametrize(
    ("result_chunks", "raises_error", "expected_status", "expected_reason"),
    [
        ([], False, "insufficient_evidence", None),
        ([], True, "unavailable", "retrieval_dependency_failed"),
    ],
)
def test_policy_evidence_retrieval_distinguishes_empty_from_failure(
    monkeypatch,
    result_chunks,
    raises_error: bool,
    expected_status: str,
    expected_reason: str | None,
) -> None:
    def fake_query(request, **kwargs):
        if raises_error:
            raise main.QueryDependencyError("private upstream detail")
        return type("Result", (), {"chunks": result_chunks})()

    monkeypatch.setattr(main, "execute_rag_query", fake_query)
    claim = main.SyntheticClaimContext(
        claim_id="CL-123",
        policy_id="HOME-002",
        customer_id="CUST-123",
        loss_date=date(2025, 3, 1),
        reported_event="Water entered the home.",
        status="under_review",
    )

    with httpx.Client() as client:
        sources, status, reason = main.execute_policy_evidence_retrieval(
            client,
            claim_id="CL-123",
            policy_id="HOME-002",
            narrative="Flood water entered the home overnight.",
            claim_context=claim,
        )

    assert sources == []
    assert status == expected_status
    assert reason == expected_reason


def test_policy_evidence_retrieval_marks_source_selection_failure_unavailable(
    monkeypatch,
) -> None:
    def fail_source_selection(*args, **kwargs):
        raise main.NoApplicableBasePolicyError("private source details")

    monkeypatch.setattr(main, "execute_rag_query", fail_source_selection)
    claim = main.SyntheticClaimContext(
        claim_id="CL-123",
        policy_id="HOME-002",
        customer_id="CUST-123",
        loss_date=date(2025, 3, 1),
        reported_event="Water entered the home.",
        status="under_review",
    )

    with httpx.Client() as client:
        sources, status, reason = main.execute_policy_evidence_retrieval(
            client,
            claim_id="CL-123",
            policy_id="HOME-002",
            narrative="Water entered the home overnight.",
            claim_context=claim,
        )

    assert sources == []
    assert status == "unavailable"
    assert reason == "source_selection_failed"
