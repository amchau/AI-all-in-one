from datetime import date
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest
from psycopg.conninfo import conninfo_to_dict

API_MODULE_DIR = Path(__file__).resolve().parents[2] / "apps" / "ai-api"
sys.path.insert(0, str(API_MODULE_DIR))
with patch.dict(os.environ, {"AI_API_ENV_FILE": ""}), patch(
    "opentelemetry.sdk.trace.TracerProvider.add_span_processor"
):
    import main
from rag.retrieval.models import (
    Citation,
    GroundedAnswer,
    GroundedFinding,
    GroundedInvestigation,
    RagQueryResult,
    RetrievedChunk,
)


@pytest.fixture
def api_client(monkeypatch):
    monkeypatch.setattr(main.settings, "postgres_query_password", "test-db-password")
    monkeypatch.setattr(main.settings, "postgres_workflow_password", "test-workflow-password")
    monkeypatch.setattr(main.settings, "litellm_master_key", "test-litellm-key")

    class NoOpWorkflowWorker:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    monkeypatch.setattr(main, "create_workflow_store", lambda: object())
    monkeypatch.setattr(main, "WorkflowWorker", NoOpWorkflowWorker)
    with TestClient(main.app) as client:
        yield client


def test_rag_query_returns_validated_citations_and_chunks(api_client, monkeypatch) -> None:
    citation = Citation(
        ref="C1",
        chunk_id="chunk-1",
        doc_id="POL-HOME-002-v2",
        title="Home Policy",
        section="4",
        clause="4.2",
        page=3,
    )
    chunk = RetrievedChunk(
        chunk_id="chunk-1",
        ref="C1",
        doc_id="POL-HOME-002-v2",
        title="Home Policy",
        section="4",
        clause="4.2",
        page=3,
        score=0.82,
        text="Flood damage is covered subject to limits.",
        dense_score=0.82,
    )
    result = RagQueryResult(
        answer=GroundedAnswer(
            status="answered",
            answer="Flood damage is covered subject to limits. [C1]",
            citations=[citation],
        ),
        chunks=[chunk],
        model="gpt-oss-20b",
        latency_ms=120,
    )
    monkeypatch.setattr(main, "execute_rag_query", lambda request: result)

    response = api_client.post(
        "/v1/rag/query",
        json={
            "question": "Is flood damage covered?",
            "policy_id": "HOME-002",
            "loss_date": "2025-03-01",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "answered"
    assert payload["answer"].endswith("[C1]")
    assert payload["citations"][0]["page"] == 3
    assert payload["chunks"][0]["chunk_id"] == "chunk-1"
    assert payload["chunks"][0]["ref"] == "C1"
    assert payload["mode"] == "dense"
    assert payload["chunks"][0]["score"] == 0.82
    assert payload["chunks"][0]["dense_score"] == 0.82
    assert payload["chunks"][0]["hybrid_score"] is None
    assert payload["chunks"][0]["rerank_score"] is None
    assert isinstance(payload["trace_id"], str)
    assert re.fullmatch(r"[0-9a-f]{32}", payload["trace_id"])


def test_rag_query_accepts_hybrid_mode(api_client, monkeypatch) -> None:
    result = RagQueryResult(
        answer=GroundedAnswer(status="insufficient_evidence", answer="", citations=[]),
        chunks=[],
        model="gpt-oss-20b",
        latency_ms=120,
        mode="hybrid",
    )
    monkeypatch.setattr(main, "execute_rag_query", lambda request: result)

    response = api_client.post(
        "/v1/rag/query",
        json={
            "question": "Is flood damage covered?",
            "policy_id": "HOME-002",
            "loss_date": "2025-03-01",
            "mode": "hybrid",
        },
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "hybrid"


def test_rag_query_serializes_rerank_score_fields(api_client, monkeypatch) -> None:
    citation = Citation(
        ref="C1",
        chunk_id="chunk-1",
        doc_id="POL-HOME-002-v2",
        title="Home Policy",
        section="4",
        clause="4.2",
        page=3,
    )
    chunk = RetrievedChunk(
        chunk_id="chunk-1",
        ref="C1",
        doc_id="POL-HOME-002-v2",
        title="Home Policy",
        section="4",
        clause="4.2",
        page=3,
        score=0.9,
        text="Flood extension wording.",
        hybrid_score=0.04,
        rerank_score=0.9,
    )
    result = RagQueryResult(
        answer=GroundedAnswer(
            status="answered",
            answer="Flood extension applies. [C1]",
            citations=[citation],
        ),
        chunks=[chunk],
        model="gpt-oss-20b",
        latency_ms=120,
        mode="hybrid_rerank",
    )
    monkeypatch.setattr(main, "execute_rag_query", lambda request: result)

    response = api_client.post(
        "/v1/rag/query",
        json={
            "question": "Is flood damage covered?",
            "policy_id": "HOME-002",
            "loss_date": "2025-03-01",
            "mode": "hybrid_rerank",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "hybrid_rerank"
    assert payload["chunks"][0]["score"] == 0.9
    assert payload["chunks"][0]["hybrid_score"] == 0.04
    assert payload["chunks"][0]["rerank_score"] == 0.9


def test_rag_query_sanitizes_dependency_errors(api_client, monkeypatch) -> None:
    def fail(request):
        raise main.QueryDependencyError("provider secret or SQL detail")

    monkeypatch.setattr(main, "execute_rag_query", fail)
    response = api_client.post(
        "/v1/rag/query",
        json={
            "question": "Is flood damage covered?",
            "policy_id": "HOME-002",
            "loss_date": "2025-03-01",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "RAG query dependency failed"
    assert "provider secret" not in response.text


def test_postgres_dsn_safely_encodes_reserved_password_characters(monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "postgres_query_password", "p@ss/word#=x")
    monkeypatch.setattr(main.settings, "postgres_host", "localhost")
    monkeypatch.setattr(main.settings, "postgres_port", 5432)
    monkeypatch.setattr(main.settings, "postgres_db", "platform")

    parsed = conninfo_to_dict(main.get_postgres_dsn())

    assert parsed["user"] == "rag_query"
    assert parsed["password"] == "p@ss/word#=x"


def test_settings_repr_masks_credentials(monkeypatch) -> None:
    secrets = {
        "litellm_master_key": "test-litellm-secret",
        "postgres_query_password": "test-postgres-secret",
    }
    for name, value in secrets.items():
        monkeypatch.setattr(main.settings, name, value)

    settings_repr = repr(main.settings)

    for value in secrets.values():
        assert value not in settings_repr


def test_healthz_returns_service_unavailable_when_dependency_is_down(
    api_client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(main, "postgres_health", lambda: {"ok": False})
    monkeypatch.setattr(main, "qdrant_health", lambda: {"ok": True})
    monkeypatch.setattr(main, "litellm_health", lambda: {"ok": True})

    response = api_client.get("/healthz")

    assert response.status_code == 503
    assert response.json()["ok"] is False


def test_livez_does_not_probe_external_dependencies(api_client, monkeypatch) -> None:
    def dependency_unavailable():
        raise AssertionError("liveness must not call dependency checks")

    monkeypatch.setattr(main, "postgres_health", dependency_unavailable)
    monkeypatch.setattr(main, "qdrant_health", dependency_unavailable)
    monkeypatch.setattr(main, "litellm_health", dependency_unavailable)

    response = api_client.get("/livez")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_postgres_readiness_checks_rag_registry_access(monkeypatch) -> None:
    queries: list[str] = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, query: str) -> None:
            queries.append(query)

        def fetchone(self) -> tuple[int]:
            return (1,)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self) -> Cursor:
            return Cursor()

    monkeypatch.setattr(main, "get_postgres_dsn", lambda: "test-conninfo")
    monkeypatch.setattr(main.psycopg, "connect", lambda *args, **kwargs: Connection())

    health = main.postgres_health()

    assert health["ok"] is True
    assert queries == [
        "SELECT id, title, doc_type, product, policy_id, version, effective_date, acl "
        "FROM rag.documents LIMIT 0"
    ]


def test_qdrant_readiness_checks_server_without_requiring_ingested_collection(
    monkeypatch,
) -> None:
    class Client:
        def __init__(self, *, url: str, timeout: int) -> None:
            assert url == "http://qdrant:6333"
            assert timeout == 2

        def get_collections(self):
            return SimpleNamespace(collections=[])

        def close(self) -> None:
            return None

    monkeypatch.setattr(main.settings, "qdrant_url", "http://qdrant:6333")
    monkeypatch.setattr(main, "QdrantClient", Client)

    assert main.qdrant_health()["ok"] is True


def test_investigate_route_keeps_working_without_minio_credentials(
    api_client,
    monkeypatch,
) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "Investigation summary"}}]}

    class AsyncClient:
        def __init__(self, *, timeout: int) -> None:
            assert timeout == 30

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *args, **kwargs) -> Response:
            return Response()

    monkeypatch.setattr(main.httpx, "AsyncClient", AsyncClient)
    monkeypatch.setattr(main, "postgres_health", lambda: {"ok": True})
    monkeypatch.setattr(main, "qdrant_health", lambda: {"ok": True})
    monkeypatch.setattr(main, "litellm_health", lambda: {"ok": True})

    response = api_client.post(
        "/v1/investigate",
        json={"claim_id": "CL-123", "prompt": "Summarize the claim."},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "Investigation summary"
    assert set(response.json()["dependencies"]) == {"postgres", "qdrant", "litellm"}


def test_structured_investigation_returns_cited_brief_and_trace_id(
    api_client,
    monkeypatch,
) -> None:
    citation = Citation(
        ref="C1",
        chunk_id="chunk-1",
        doc_id="POL-HOME-002-v2",
        title="Home Policy",
        section="4",
        clause="4.2",
        page=3,
    )
    chunk = RetrievedChunk(
        chunk_id="chunk-1",
        ref="C1",
        doc_id="POL-HOME-002-v2",
        title="Home Policy",
        section="4",
        clause="4.2",
        page=3,
        score=0.82,
        text="Flood damage is covered subject to the stated limits.",
    )
    investigation = GroundedInvestigation(
        status="answered",
        summary="Flood cover is subject to limits.",
        summary_refs=("C1",),
        findings=(
            GroundedFinding(
                text="The policy limits flood cover.",
                refs=("C1",),
            ),
        ),
        unresolved_questions=("What is the estimated repair cost?",),
        citations=[citation],
    )
    result = SimpleNamespace(
        investigation=investigation,
        chunks=[chunk],
        model="gpt-oss-20b",
        latency_ms=120,
        mode="hybrid_rerank",
    )
    monkeypatch.setattr(
        main,
        "execute_rag_investigation",
        lambda request: result,
        raising=False,
    )

    response = api_client.post(
        "/v1/investigations",
        json={
            "claim_id": "CL-123",
            "policy_id": "HOME-002",
            "loss_date": "2025-03-01",
            "narrative": "Flood water entered the ground floor overnight.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["claim_id"] == "CL-123"
    assert payload["status"] == "answered"
    assert payload["summary"] == "Flood cover is subject to limits."
    assert payload["summary_citations"][0]["ref"] == "C1"
    assert payload["findings"][0]["citations"][0]["chunk_id"] == "chunk-1"
    assert payload["evidence"][0]["text"] == chunk.text
    assert payload["unresolved_questions"] == ["What is the estimated repair cost?"]
    assert re.fullmatch(r"[0-9a-f]{32}", payload["trace_id"])


@pytest.mark.parametrize(
    "extra_fields",
    [
        {"mode": "dense"},
        {"top_k": 20},
    ],
)
def test_structured_investigation_does_not_accept_retrieval_overrides(
    api_client,
    extra_fields: dict[str, object],
) -> None:
    payload = {
        "claim_id": "CL-123",
        "policy_id": "HOME-002",
        "loss_date": "2025-03-01",
        "narrative": "Flood water entered the ground floor overnight.",
        **extra_fields,
    }

    response = api_client.post("/v1/investigations", json=payload)

    assert response.status_code == 422


def test_investigation_validation_errors_do_not_echo_claim_narrative(api_client) -> None:
    private_marker = "CLAIM-NARRATIVE-DO-NOT-ECHO"
    response = api_client.post(
        "/v1/investigations",
        json={
            "claim_id": "CL-123",
            "policy_id": "HOME-002",
            "loss_date": "2025-03-01",
            "narrative": private_marker + ("x" * 1000),
        },
    )

    assert response.status_code == 422
    assert private_marker not in response.text
    errors = response.json()["detail"]
    assert any(error["loc"] == ["body", "narrative"] for error in errors)
    assert all("input" not in error and "ctx" not in error for error in errors)


def test_investigation_validation_errors_redact_unknown_field_names(api_client) -> None:
    private_field = "CLAIM-SECRET-FIELD-NAME"
    response = api_client.post(
        "/v1/investigations",
        json={
            "claim_id": "CL-123",
            "policy_id": "HOME-002",
            "loss_date": "2025-03-01",
            "narrative": "Flood water entered the ground floor overnight.",
            private_field: "private-value",
        },
    )

    assert response.status_code == 422
    assert private_field not in response.text
    assert "private-value" not in response.text
    errors = response.json()["detail"]
    assert any("field" in error["loc"] for error in errors)


def test_fastapi_server_span_redacts_query_string() -> None:
    class RecordingSpan:
        def __init__(self) -> None:
            self.attributes: dict[str, object] = {}

        def is_recording(self) -> bool:
            return True

        def set_attribute(self, name: str, value: object) -> None:
            self.attributes[name] = value

    span = RecordingSpan()
    main.sanitize_server_request_span(
        span,
        {
            "path": "/v1/investigations",
            "query_string": b"claim=CLAIM-NARRATIVE-SECRET",
            "scheme": "http",
            "headers": [(b"host", b"api.local:8000")],
        },
    )

    assert span.attributes["http.target"] == "/v1/investigations"
    assert span.attributes["http.url"] == "http://api.local:8000/v1/investigations"
    assert span.attributes["url.query"] == ""
    assert "CLAIM-NARRATIVE-SECRET" not in repr(span.attributes)


def test_investigation_dependency_errors_remain_distinct_from_abstention(
    api_client,
    monkeypatch,
) -> None:
    def fail(request):
        raise main.QueryDependencyError("private provider detail")

    monkeypatch.setattr(main, "execute_rag_investigation", fail)
    response = api_client.post(
        "/v1/investigations",
        json={
            "claim_id": "CL-123",
            "policy_id": "HOME-002",
            "loss_date": "2025-03-01",
            "narrative": "Flood water entered the ground floor overnight.",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Claims investigation dependency failed"
    assert "private provider detail" not in response.text


def test_execute_rag_investigation_fixes_mode_and_top_k(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def execute(request, *, structured_investigation: bool = False):
        captured["request"] = request
        captured["structured_investigation"] = structured_investigation
        return SimpleNamespace()

    monkeypatch.setattr(main, "execute_rag_query", execute)
    request = main.ClaimsInvestigationRequest(
        claim_id="CL-123",
        policy_id="HOME-002",
        loss_date=date(2025, 3, 1),
        narrative="Flood water entered the ground floor overnight.",
    )

    main.execute_rag_investigation(request)

    rag_request = captured["request"]
    assert rag_request.policy_id == "HOME-002"
    assert rag_request.loss_date == date(2025, 3, 1)
    assert rag_request.guidance_as_of is None
    assert rag_request.mode == "hybrid_rerank"
    assert rag_request.top_k == 5
    assert "Flood water entered the ground floor overnight." in rag_request.question
    assert "Do not determine whether this specific claim is covered;" in rag_request.question
    assert captured["structured_investigation"] is True


def test_litellm_health_checks_readiness_endpoint(monkeypatch) -> None:
    requests: list[tuple[str, dict[str, str]]] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

    class Client:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 2.0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url: str, *, headers: dict[str, str]) -> Response:
            requests.append((url, headers))
            return Response()

    monkeypatch.setattr(main.settings, "litellm_url", "http://litellm:4000/")
    monkeypatch.setattr(main.settings, "litellm_master_key", "test-litellm-key")
    monkeypatch.setattr(main.httpx, "Client", Client)

    health = main.litellm_health()

    assert health["ok"] is True
    assert requests == [
        (
            "http://litellm:4000/health/readiness",
            {"Authorization": "Bearer test-litellm-key"},
        )
    ]