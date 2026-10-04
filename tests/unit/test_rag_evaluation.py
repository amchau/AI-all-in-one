from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import httpx
import pytest

from rag.evaluation import (
    MODES,
    EvaluationCase,
    EvaluationError,
    ExpectedSource,
    aggregate_outcomes,
    failed_outcome,
    load_evaluation_set,
    metric_for_response,
    render_report,
    run_evaluation,
    safe_url_metadata,
    sha256_files,
    validate_evaluation_url,
    validate_expected_chunk_ids,
    validate_output_paths,
)
from rag.ingestion.chunk import chunk_pages
from rag.ingestion.manifest import load_manifest
from rag.ingestion.parse import extract_pdf_pages
from scripts.run_rag_eval import EVALUATOR_SOURCE_PATHS


CORPUS_MANIFEST_SHA256 = "b093b13c2812dbfeccbe8b89caecead69b0e3649b0dfcad40717bcf641a20206"


def _case(
    *,
    case_id: str = "case-1",
    answerable: bool = True,
    relevant_chunk_ids: list[str] | None = None,
) -> EvaluationCase:
    return EvaluationCase(
        case_id=case_id,
        question="Does policy HOME-002 cover sudden water damage?",
        policy_id="HOME-002",
        loss_date=date(2025, 3, 1),
        guidance_as_of=date(2026, 1, 1),
        answerable=answerable,
        relevant_chunk_ids=(
            relevant_chunk_ids if relevant_chunk_ids is not None else ["chunk-a", "chunk-b"]
        ),
        expected_sources=(
            [{"doc_id": "TEST-DOC", "section": "1"}] if answerable else []
        ),
    )


def _response(
    *,
    mode: str = "dense",
    status: str = "answered",
    chunks: list[str] | None = None,
    citations: list[str] | None = None,
) -> dict[str, object]:
    chunk_ids = chunks if chunks is not None else ["chunk-x", "chunk-a", "chunk-b"]
    cited_ids = citations if citations is not None else ["chunk-a"]
    return {
        "mode": mode,
        "status": status,
        "answer": "Water damage is covered. [C1]" if status == "answered" else "",
        "citations": [{"chunk_id": chunk_id, "ref": f"C{index}"} for index, chunk_id in enumerate(cited_ids, 1)],
        "chunks": [{"chunk_id": chunk_id} for chunk_id in chunk_ids],
        "latency_ms": 120,
        "model": "gpt-oss-20b",
        "trace_id": "0123456789abcdef0123456789abcdef",
    }


def test_metrics_use_ranked_chunk_ids_and_citations() -> None:
    outcome = metric_for_response(
        _case(), mode="dense", payload=_response(), client_latency_ms=180
    )

    assert outcome.recall_at_5 == 1.0
    assert outcome.reciprocal_rank == 0.5
    assert outcome.citation_precision == 1.0
    assert outcome.answerability_correct is True
    assert outcome.service_latency_ms == 120
    assert outcome.client_latency_ms == 180


def test_metric_penalizes_irrelevant_and_unreturned_citations() -> None:
    response = _response(citations=["chunk-a", "not-returned", "chunk-x"])

    outcome = metric_for_response(
        _case(), mode="dense", payload=response, client_latency_ms=180
    )

    assert outcome.citation_precision == pytest.approx(1 / 3)
    assert outcome.citation_mapping_errors == 1


@pytest.mark.parametrize("status", [[], {}])
def test_metric_rejects_non_string_status(status: object) -> None:
    response = _response()
    response["status"] = status

    with pytest.raises(EvaluationError, match="response status is invalid"):
        metric_for_response(
            _case(), mode="dense", payload=response, client_latency_ms=180
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("answer", None), ("answer", []), ("model", ""), ("model", None)],
)
def test_metric_rejects_missing_or_invalid_required_response_fields(
    field: str, value: object
) -> None:
    response = _response()
    response[field] = value

    with pytest.raises(EvaluationError, match=f"response {field} is invalid"):
        metric_for_response(
            _case(), mode="dense", payload=response, client_latency_ms=180
        )


def test_metric_drops_malformed_trace_id() -> None:
    response = _response()
    response["trace_id"] = "not-a-trace-id"

    outcome = metric_for_response(
        _case(), mode="dense", payload=response, client_latency_ms=180
    )

    assert outcome.trace_id is None


def test_zero_citations_are_reported_as_unavailable_and_counted() -> None:
    outcome = metric_for_response(
        _case(), mode="dense", payload=_response(citations=[]), client_latency_ms=180
    )

    summary = aggregate_outcomes([outcome])

    assert outcome.citation_precision is None
    assert summary.no_citation_count == 1


def test_unanswerable_cases_are_excluded_from_retrieval_metrics() -> None:
    case = _case(answerable=False, relevant_chunk_ids=[])
    outcome = metric_for_response(
        case,
        mode="dense",
        payload=_response(status="insufficient_evidence", citations=[]),
        client_latency_ms=180,
    )

    assert outcome.recall_at_5 is None
    assert outcome.reciprocal_rank is None
    assert outcome.answerability_correct is True


def test_failure_is_not_scored_as_abstention() -> None:
    successful = metric_for_response(
        _case(), mode="dense", payload=_response(), client_latency_ms=180
    )
    failure = failed_outcome(
        _case(case_id="case-2"),
        mode="dense",
        category="http_502",
        http_status=502,
        client_latency_ms=900,
    )
    summary = aggregate_outcomes([successful, failure])

    assert failure.answerability_correct is None
    assert failure.status is None
    assert summary.attempted_count == 2
    assert summary.failure_count == 1
    assert summary.failure_rate == 0.5
    assert summary.answerability_count == 1
    assert summary.median_client_latency_ms == 540
    assert summary.p95_client_latency_ms == 900


def test_dataset_loader_rejects_duplicate_ids_and_missing_relevance(tmp_path) -> None:
    duplicate_dataset = {
        "schema_version": 1,
        "corpus_manifest_sha256": CORPUS_MANIFEST_SHA256,
        "cases": [
            {
                "case_id": "same",
                "question": "Question one?",
                "policy_id": "HOME-002",
                "loss_date": "2025-03-01",
                "answerable": True,
                "relevant_chunk_ids": ["chunk-a"],
                    "expected_sources": [{"doc_id": "TEST-DOC", "section": "1"}],
            },
            {
                "case_id": "same",
                "question": "Question two?",
                "policy_id": "HOME-002",
                "loss_date": "2025-03-01",
                "answerable": True,
                "relevant_chunk_ids": ["chunk-b"],
                    "expected_sources": [{"doc_id": "TEST-DOC", "section": "1"}],
            },
        ],
    }
    path = tmp_path / "golden.yaml"
    path.write_text(json.dumps(duplicate_dataset), encoding="utf-8")

    with pytest.raises(EvaluationError, match="duplicate case_id"):
        load_evaluation_set(path)

    duplicate_dataset["cases"] = [
        {
            "case_id": "no-evidence",
            "question": "Question with no gold evidence?",
            "policy_id": "HOME-002",
            "loss_date": "2025-03-01",
            "answerable": True,
            "relevant_chunk_ids": [],
        }
    ]
    path.write_text(json.dumps(duplicate_dataset), encoding="utf-8")

    with pytest.raises(EvaluationError, match="answerable case requires relevant chunk IDs"):
        load_evaluation_set(path)


def test_runner_sends_one_fixed_top_k_request_per_mode_without_retries() -> None:
    cases = [_case(case_id="case-1"), _case(case_id="case-2")]
    requests: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json=_response(mode=str(body["mode"])))

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        outcomes = run_evaluation(cases, client=client, base_url="http://rag.test")

    assert len(requests) == len(cases) * len(MODES)
    assert [request["mode"] for request in requests[:3]] == list(MODES)
    assert [request["mode"] for request in requests[3:]] == [
        "hybrid",
        "hybrid_rerank",
        "dense",
    ]
    assert all(request["top_k"] == 5 for request in requests)
    assert all(request["policy_id"] == "HOME-002" for request in requests)
    assert all(request["loss_date"] == "2025-03-01" for request in requests)
    assert len(outcomes) == len(requests)


def test_runner_records_http_and_transport_failures_without_retry() -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(
            502,
            json={
                "detail": "RAG query dependency failed",
                "trace_id": "fedcba9876543210fedcba9876543210",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        outcomes = run_evaluation([_case()], client=client, base_url="http://rag.test")

    assert calls == ["/v1/rag/query"] * len(MODES)
    assert len(outcomes) == len(MODES)
    assert all(outcome.failure_category == "http_502" for outcome in outcomes)
    assert all(
        outcome.trace_id == "fedcba9876543210fedcba9876543210"
        for outcome in outcomes
    )


@pytest.mark.parametrize(
    ("header_name", "header_value", "expected_trace_id"),
    [
        (
            "traceparent",
            "00-fedcba9876543210fedcba9876543210-0123456789abcdef-01",
            "fedcba9876543210fedcba9876543210",
        ),
        ("x-trace-id", "fedcba9876543210fedcba9876543210", "fedcba9876543210fedcba9876543210"),
        ("traceparent", "bad-fedcba9876543210fedcba9876543210-badspan-zz", None),
    ],
)
def test_http_failure_trace_headers_are_validated(
    header_name: str,
    header_value: str,
    expected_trace_id: str | None,
) -> None:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502,
            json={"detail": "RAG query dependency failed"},
            headers={header_name: header_value},
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        outcomes = run_evaluation([_case()], client=client, base_url="http://rag.test")

    assert all(outcome.trace_id == expected_trace_id for outcome in outcomes)


def test_runner_marks_malformed_success_payload_as_failure() -> None:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "answered"},
            headers={"x-trace-id": "0123456789abcdef0123456789abcdef"},
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        outcomes = run_evaluation([_case()], client=client, base_url="http://rag.test")

    assert all(outcome.failure_category == "invalid_response" for outcome in outcomes)
    assert all(
        outcome.trace_id == "0123456789abcdef0123456789abcdef"
        for outcome in outcomes
    )


def test_runner_classifies_timeout_without_retry() -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        raise httpx.ReadTimeout("request timed out", request=request)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        outcomes = run_evaluation([_case()], client=client, base_url="http://rag.test")

    assert calls == ["/v1/rag/query"] * len(MODES)
    assert all(outcome.failure_category == "timeout" for outcome in outcomes)


def test_runner_rejects_invalid_base_url() -> None:
    with httpx.Client() as client, pytest.raises(EvaluationError, match="absolute HTTP"):
        run_evaluation([_case()], client=client, base_url="not-a-url")


@pytest.mark.parametrize(
    "url",
    [
        "http://user:password@rag.test",
        "https://rag.test/api?token=secret",
        "https://rag.test/#secret",
    ],
)
def test_evaluation_url_rejects_credentials_and_secrets(url: str) -> None:
    with pytest.raises(EvaluationError, match="must not contain credentials"):
        validate_evaluation_url(url)


def test_evaluation_url_rejects_invalid_port() -> None:
    with pytest.raises(EvaluationError, match="valid port"):
        validate_evaluation_url("http://rag.test:bogus")


def test_report_url_metadata_hides_path_and_credentials() -> None:
    metadata = safe_url_metadata("https://rag.test/private-prefix-secret")

    assert metadata["api_origin"] == "https://rag.test"
    assert metadata["api_base_path_sha256"]
    assert "private-prefix-secret" not in str(metadata)


def test_output_paths_cannot_collide_with_each_other_or_sources(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    report = repository / "docs/eval/report.md"
    results = repository / "docs/eval/results.json"

    validate_output_paths(
        report,
        results,
        repository_root=repository,
        protected_paths=[repository / "tests/evaluation/golden.yaml"],
    )
    with pytest.raises(EvaluationError, match="must be different"):
        validate_output_paths(
            report,
            report,
            repository_root=repository,
            protected_paths=[],
        )
    with pytest.raises(EvaluationError, match="must not contain one another"):
        validate_output_paths(
            report,
            report / "nested.json",
            repository_root=repository,
            protected_paths=[],
        )
    with pytest.raises(EvaluationError, match="must be files under docs/eval"):
        validate_output_paths(
            repository / "docs/eval",
            results,
            repository_root=repository,
            protected_paths=[],
        )
    with pytest.raises(EvaluationError, match="protected input"):
        validate_output_paths(
            repository / "tests/evaluation/golden.yaml",
            results,
            repository_root=repository,
            protected_paths=[repository / "tests/evaluation/golden.yaml"],
        )
    with pytest.raises(EvaluationError, match="inside the repository must be under"):
        validate_output_paths(
            repository / "README.md",
            results,
            repository_root=repository,
            protected_paths=[],
        )


def test_expected_chunk_labels_must_exist_in_corpus() -> None:
    golden_path = Path(__file__).resolve().parents[1] / "evaluation" / "golden.yaml"
    dataset = load_evaluation_set(golden_path)
    corpus_root = golden_path.parents[2] / "data/generated"
    chunk_locations = {
        chunk.chunk_id: (chunk.document_id, chunk.section, chunk.clause)
        for document in load_manifest(corpus_root)
        for chunk in chunk_pages(
            str(document.metadata["doc_id"]),
            extract_pdf_pages(document.pdf_path),
        )
    }

    validate_expected_chunk_ids(dataset.cases, chunk_locations)
    with pytest.raises(EvaluationError, match="unknown corpus chunk IDs"):
        validate_expected_chunk_ids(
            dataset.cases,
            {
                chunk_id: location
                for chunk_id, location in chunk_locations.items()
                if chunk_id != "266a4326-46d4-53f6-aaf3-e403f26b4184"
            },
        )
    mismatched_case = dataset.cases[0].model_copy(
        update={
            "expected_sources": [
                ExpectedSource(doc_id="WRONG-DOC", section="1")
            ]
        }
    )
    with pytest.raises(EvaluationError, match="do not match annotated source locations"):
        validate_expected_chunk_ids([mismatched_case], chunk_locations)


def test_source_digest_changes_when_evaluator_file_changes(tmp_path: Path) -> None:
    source = tmp_path / "rag" / "evaluation.py"
    source.parent.mkdir()
    source.write_text("version one", encoding="utf-8")
    first_digest = sha256_files([source], root=tmp_path)
    source.write_text("version two", encoding="utf-8")

    assert sha256_files([source], root=tmp_path) != first_digest


def test_evaluator_digest_includes_corpus_id_generation_sources() -> None:
    relative_sources = {
        path.relative_to(Path(__file__).resolve().parents[2]).as_posix()
        for path in EVALUATOR_SOURCE_PATHS
    }

    assert {
        "rag/ingestion/chunk.py",
        "rag/ingestion/parse.py",
        "rag/ingestion/manifest.py",
        "apps/ai-api/requirements.txt",
        "rag/retrieval/models.py",
        "tests/evaluation/requirements.txt",
        "rag/retrieval/models.py",
    } <= relative_sources


def test_report_discloses_latency_denominators_and_gold_answerability() -> None:
    outcome = metric_for_response(
        _case(), mode="dense", payload=_response(), client_latency_ms=180
    )
    summary = aggregate_outcomes([outcome])

    report = render_report(
        summaries=[summary],
        outcomes=[outcome],
        metadata={"dataset_case_count": 1},
    )

    assert "Client latency includes all attempts" in report
    assert "Gold answerable" in report
    assert "0123456789abcdef0123456789abcdef" in report
    assert "Water damage is covered" not in report


def test_checked_in_golden_set_is_pinned_and_has_temporal_boundary_cases() -> None:
    golden_path = Path(__file__).resolve().parents[1] / "evaluation" / "golden.yaml"

    dataset = load_evaluation_set(golden_path)

    assert dataset.corpus_manifest_sha256 == CORPUS_MANIFEST_SHA256
    assert len(dataset.cases) == 35
    unanswerable_cases = [case for case in dataset.cases if not case.answerable]
    assert len(unanswerable_cases) == 6
    assert {case.policy_id for case in unanswerable_cases} == {
        "HOME-002",
        "MOTOR-001",
        "COMM-001",
    }
    assert {case.loss_date.isoformat() for case in dataset.cases} >= {
        "2025-01-31",
        "2025-02-01",
    }