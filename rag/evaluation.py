from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from math import ceil
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
import yaml

from rag.retrieval.models import RagQueryInput


MODES: tuple[Literal["dense", "hybrid", "hybrid_rerank"], ...] = (
    "dense",
    "hybrid",
    "hybrid_rerank",
)
TOP_K = 5
EVALUATION_PATH = "/v1/rag/query"


class EvaluationError(ValueError):
    """Raised when the evaluation set or a successful API response is invalid."""


class ExpectedSource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    doc_id: str = Field(min_length=1)
    section: str | None = None
    clause: str | None = None

    def location(self) -> tuple[str, str | None, str | None]:
        return self.doc_id, self.section, self.clause


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=5, max_length=1200)
    policy_id: str = Field(min_length=1, max_length=80)
    loss_date: date
    guidance_as_of: date | None = None
    answerable: bool
    relevant_chunk_ids: list[str]
    expected_sources: list[ExpectedSource] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_query_and_labels(self) -> EvaluationCase:
        if any(not chunk_id.strip() for chunk_id in self.relevant_chunk_ids):
            raise ValueError("relevant_chunk_ids must contain non-empty IDs")
        if len(self.relevant_chunk_ids) != len(set(self.relevant_chunk_ids)):
            raise ValueError("relevant_chunk_ids must be unique")
        if self.answerable and not self.relevant_chunk_ids:
            raise ValueError("answerable case requires relevant chunk IDs")
        if self.answerable and not self.expected_sources:
            raise ValueError("answerable case requires expected source locations")
        if not self.answerable and self.expected_sources:
            raise ValueError("unanswerable case cannot have expected source locations")
        source_locations = [source.location() for source in self.expected_sources]
        if len(source_locations) != len(set(source_locations)):
            raise ValueError("expected source locations must be unique")
        RagQueryInput(
            question=self.question,
            policy_id=self.policy_id,
            loss_date=self.loss_date,
            guidance_as_of=self.guidance_as_of,
            top_k=TOP_K,
            mode="dense",
        )
        return self


class EvaluationSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    corpus_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases: list[EvaluationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case_ids(self) -> EvaluationSet:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("duplicate case_id in evaluation set")
        return self


@dataclass(frozen=True)
class EvaluationOutcome:
    case_id: str
    mode: str
    succeeded: bool
    http_status: int | None
    failure_category: str | None
    status: str | None
    expected_answerable: bool
    answerability_correct: bool | None
    retrieved_chunk_ids: list[str]
    cited_chunk_ids: list[str]
    recall_at_5: float | None
    reciprocal_rank: float | None
    citation_precision: float | None
    relevant_citation_count: int
    citation_count: int
    citation_mapping_errors: int
    service_latency_ms: int | None
    client_latency_ms: int
    trace_id: str | None
    model: str | None


@dataclass(frozen=True)
class ModeSummary:
    mode: str
    attempted_count: int
    success_count: int
    failure_count: int
    failure_rate: float
    answerability_count: int
    answerability_accuracy: float | None
    retrieval_case_count: int
    mean_recall_at_5: float | None
    mean_mrr: float | None
    citation_precision: float | None
    citation_count: int
    no_citation_count: int
    citation_mapping_errors: int
    median_client_latency_ms: float | None
    p95_client_latency_ms: int | None
    median_service_latency_ms: float | None
    p95_service_latency_ms: int | None
    failure_categories: dict[str, int]


def load_evaluation_set(path: Path) -> EvaluationSet:
    try:
        raw_data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return EvaluationSet.model_validate(raw_data)
    except ValidationError as error:
        details = "; ".join(
            item["msg"] for item in error.errors(include_url=False)
        )
        raise EvaluationError(f"invalid evaluation set: {details}") from error
    except (OSError, yaml.YAMLError, TypeError) as error:
        detail = str(error).splitlines()[0] if str(error) else "invalid data"
        raise EvaluationError(f"invalid evaluation set: {detail}") from error


def validate_evaluation_url(base_url: str) -> str:
    parsed_url = urlsplit(base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
        raise EvaluationError("base_url must be an absolute HTTP(S) URL")
    try:
        port = parsed_url.port
    except ValueError as error:
        raise EvaluationError("base_url must use a valid port") from error
    if port is not None and not 1 <= port <= 65535:
        raise EvaluationError("base_url must use a valid port")
    if parsed_url.username or parsed_url.password or parsed_url.query or parsed_url.fragment:
        raise EvaluationError(
            "base_url must not contain credentials, query parameters, or a fragment"
        )
    return base_url.rstrip("/")


def safe_url_metadata(base_url: str) -> dict[str, str]:
    parsed_url = urlsplit(validate_evaluation_url(base_url))
    path_digest = sha256(parsed_url.path.encode("utf-8")).hexdigest()
    return {
        "api_origin": f"{parsed_url.scheme}://{parsed_url.netloc}",
        "api_base_path_sha256": path_digest,
    }


def validate_expected_chunk_ids(
    cases: list[EvaluationCase],
    chunk_locations: Mapping[str, tuple[str, str | None, str | None]],
) -> None:
    unknown_ids = {
        case.case_id: sorted(set(case.relevant_chunk_ids) - chunk_locations.keys())
        for case in cases
        if set(case.relevant_chunk_ids) - chunk_locations.keys()
    }
    if unknown_ids:
        raise EvaluationError(
            f"golden set references unknown corpus chunk IDs: {unknown_ids}"
        )
    mismatched_locations = {}
    for case in cases:
        if not case.answerable:
            continue
        actual_locations = {
            chunk_locations[chunk_id] for chunk_id in case.relevant_chunk_ids
        }
        expected_locations = {source.location() for source in case.expected_sources}
        if actual_locations != expected_locations:
            mismatched_locations[case.case_id] = {
                "expected": sorted(str(location) for location in expected_locations),
                "actual": sorted(str(location) for location in actual_locations),
            }
    if mismatched_locations:
        raise EvaluationError(
            "golden set chunk IDs do not match annotated source locations: "
            f"{mismatched_locations}"
        )


def validate_output_paths(
    report_path: Path,
    results_path: Path,
    *,
    repository_root: Path,
    protected_paths: list[Path],
) -> tuple[Path, Path]:
    root = repository_root.resolve()
    report = report_path.resolve()
    results = results_path.resolve()
    evaluation_directory = (root / "docs/eval").resolve()
    for output_path in (report, results):
        if output_path == evaluation_directory or (
            output_path.exists() and output_path.is_dir()
        ):
            raise EvaluationError("output paths must be files under docs/eval")
    if report == results:
        raise EvaluationError("report and results paths must be different")
    if report.is_relative_to(results) or results.is_relative_to(report):
        raise EvaluationError("report and results paths must not contain one another")

    protected = {path.resolve() for path in protected_paths}
    if protected & {report, results}:
        raise EvaluationError("output path collides with a protected input or source file")

    for output_path in (report, results):
        if output_path.is_relative_to(root) and not output_path.is_relative_to(
            evaluation_directory
        ):
            raise EvaluationError(
                "output paths inside the repository must be under docs/eval"
            )
    return report, results


def sha256_files(paths: list[Path], *, root: Path) -> str:
    root_path = root.resolve()
    if not paths:
        raise ValueError("at least one file is required for a source digest")
    digest = sha256()
    for path in sorted(item.resolve() for item in paths):
        relative_path = path.relative_to(root_path).as_posix()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    if not relevant_ids:
        raise ValueError("relevant_ids must not be empty")
    return len(set(retrieved_ids[:k]) & relevant_ids) / len(relevant_ids)


def reciprocal_rank(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    if not relevant_ids:
        raise ValueError("relevant_ids must not be empty")
    for rank, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def _valid_trace_id(value: Any) -> str | None:
    if (
        isinstance(value, str)
        and len(value) == 32
        and value != "0" * 32
        and all(character in "0123456789abcdef" for character in value)
    ):
        return value
    return None


def _response_trace_id(response: httpx.Response) -> str | None:
    header_trace_id = _valid_trace_id(response.headers.get("x-trace-id"))
    if header_trace_id:
        return header_trace_id

    traceparent = response.headers.get("traceparent", "").split("-")
    if len(traceparent) == 4 and traceparent[0] == "00":
        traceparent_id = _valid_trace_id(traceparent[1])
        parent_id = traceparent[2]
        flags = traceparent[3]
        if (
            traceparent_id
            and len(parent_id) == 16
            and parent_id != "0" * 16
            and all(character in "0123456789abcdef" for character in parent_id)
            and len(flags) == 2
            and all(character in "0123456789abcdef" for character in flags)
        ):
            return traceparent_id

    try:
        payload = response.json()
    except ValueError:
        return None
    return _valid_trace_id(payload.get("trace_id")) if isinstance(payload, dict) else None


def _require_id_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise EvaluationError(f"response {field_name} must be a list")
    ids: list[str] = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("chunk_id"), str):
            raise EvaluationError(f"response {field_name} contains an invalid chunk")
        ids.append(item["chunk_id"])
    return ids


def metric_for_response(
    case: EvaluationCase,
    *,
    mode: str,
    payload: Mapping[str, Any],
    client_latency_ms: int,
) -> EvaluationOutcome:
    if mode not in MODES or payload.get("mode") != mode:
        raise EvaluationError("response mode does not match request mode")
    status = payload.get("status")
    if not isinstance(status, str) or status not in {
        "answered",
        "insufficient_evidence",
    }:
        raise EvaluationError("response status is invalid")
    answer = payload.get("answer")
    if not isinstance(answer, str):
        raise EvaluationError("response answer is invalid")
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        raise EvaluationError("response model is invalid")
    if type(payload.get("latency_ms")) is not int or payload["latency_ms"] < 0:
        raise EvaluationError("response latency_ms is invalid")

    retrieved_ids = _require_id_list(payload.get("chunks"), "chunks")
    cited_ids = _require_id_list(payload.get("citations"), "citations")
    returned_id_set = set(retrieved_ids)
    relevant_ids = set(case.relevant_chunk_ids)
    relevant_citation_count = sum(
        cited_id in relevant_ids and cited_id in returned_id_set for cited_id in cited_ids
    )
    citation_count = len(cited_ids)
    citation_precision = (
        relevant_citation_count / citation_count if citation_count else None
    )
    retrieval_scores = (
        (
            recall_at_k(retrieved_ids, relevant_ids, TOP_K),
            reciprocal_rank(retrieved_ids, relevant_ids),
        )
        if case.answerable
        else (None, None)
    )
    trace_id = _valid_trace_id(payload.get("trace_id"))

    return EvaluationOutcome(
        case_id=case.case_id,
        mode=mode,
        succeeded=True,
        http_status=200,
        failure_category=None,
        status=status,
        expected_answerable=case.answerable,
        answerability_correct=(status == "answered") == case.answerable,
        retrieved_chunk_ids=retrieved_ids,
        cited_chunk_ids=cited_ids,
        recall_at_5=retrieval_scores[0],
        reciprocal_rank=retrieval_scores[1],
        citation_precision=citation_precision,
        relevant_citation_count=relevant_citation_count,
        citation_count=citation_count,
        citation_mapping_errors=sum(
            cited_id not in returned_id_set for cited_id in cited_ids
        ),
        service_latency_ms=payload["latency_ms"],
        client_latency_ms=client_latency_ms,
        trace_id=trace_id,
        model=model,
    )


def failed_outcome(
    case: EvaluationCase,
    *,
    mode: str,
    category: str,
    http_status: int | None,
    client_latency_ms: int,
    trace_id: str | None = None,
) -> EvaluationOutcome:
    return EvaluationOutcome(
        case_id=case.case_id,
        mode=mode,
        succeeded=False,
        http_status=http_status,
        failure_category=category,
        status=None,
        expected_answerable=case.answerable,
        answerability_correct=None,
        retrieved_chunk_ids=[],
        cited_chunk_ids=[],
        recall_at_5=None,
        reciprocal_rank=None,
        citation_precision=None,
        relevant_citation_count=0,
        citation_count=0,
        citation_mapping_errors=0,
        service_latency_ms=None,
        client_latency_ms=client_latency_ms,
        trace_id=_valid_trace_id(trace_id),
        model=None,
    )


def _percentile(values: list[int], percentile_value: float) -> int | None:
    if not values:
        return None
    ordered_values = sorted(values)
    return ordered_values[max(0, ceil(percentile_value * len(ordered_values)) - 1)]


def _average(values: list[float]) -> float | None:
    return mean(values) if values else None


def aggregate_outcomes(outcomes: list[EvaluationOutcome]) -> ModeSummary:
    if not outcomes:
        raise ValueError("at least one evaluation outcome is required")
    modes = {outcome.mode for outcome in outcomes}
    if len(modes) != 1:
        raise ValueError("outcomes must contain exactly one retrieval mode")

    successes = [outcome for outcome in outcomes if outcome.succeeded]
    failures = [outcome for outcome in outcomes if not outcome.succeeded]
    answerability = [
        outcome.answerability_correct
        for outcome in successes
        if outcome.answerability_correct is not None
    ]
    retrieval_outcomes = [
        outcome for outcome in successes if outcome.recall_at_5 is not None
    ]
    citation_count = sum(outcome.citation_count for outcome in successes)
    relevant_citation_count = sum(
        outcome.relevant_citation_count for outcome in successes
    )
    client_latencies = [outcome.client_latency_ms for outcome in outcomes]
    service_latencies = [
        outcome.service_latency_ms
        for outcome in successes
        if outcome.service_latency_ms is not None
    ]
    failure_categories = dict(
        sorted(Counter(
            outcome.failure_category or "unknown" for outcome in failures
        ).items())
    )

    return ModeSummary(
        mode=next(iter(modes)),
        attempted_count=len(outcomes),
        success_count=len(successes),
        failure_count=len(failures),
        failure_rate=len(failures) / len(outcomes),
        answerability_count=len(answerability),
        answerability_accuracy=_average([float(correct) for correct in answerability]),
        retrieval_case_count=len(retrieval_outcomes),
        mean_recall_at_5=_average(
            [outcome.recall_at_5 for outcome in retrieval_outcomes if outcome.recall_at_5 is not None]
        ),
        mean_mrr=_average(
            [outcome.reciprocal_rank for outcome in retrieval_outcomes if outcome.reciprocal_rank is not None]
        ),
        citation_precision=(
            relevant_citation_count / citation_count if citation_count else None
        ),
        citation_count=citation_count,
        no_citation_count=sum(
            outcome.succeeded and outcome.citation_count == 0 for outcome in outcomes
        ),
        citation_mapping_errors=sum(
            outcome.citation_mapping_errors for outcome in successes
        ),
        median_client_latency_ms=(
            median(client_latencies) if client_latencies else None
        ),
        p95_client_latency_ms=_percentile(client_latencies, 0.95),
        median_service_latency_ms=(
            median(service_latencies) if service_latencies else None
        ),
        p95_service_latency_ms=_percentile(service_latencies, 0.95),
        failure_categories=failure_categories,
    )


def mode_order(case_index: int) -> tuple[str, ...]:
    offset = case_index % len(MODES)
    return MODES[offset:] + MODES[:offset]


def run_evaluation(
    cases: list[EvaluationCase], *, client: httpx.Client, base_url: str
) -> list[EvaluationOutcome]:
    if not cases:
        raise EvaluationError("evaluation set must contain at least one case")
    api_base_url = validate_evaluation_url(base_url)

    outcomes: list[EvaluationOutcome] = []
    for case_index, case in enumerate(cases):
        for mode in mode_order(case_index):
            request_body: dict[str, Any] = {
                "question": case.question,
                "policy_id": case.policy_id,
                "loss_date": case.loss_date.isoformat(),
                "top_k": TOP_K,
                "mode": mode,
            }
            if case.guidance_as_of is not None:
                request_body["guidance_as_of"] = case.guidance_as_of.isoformat()

            started_at = perf_counter()
            try:
                response = client.post(
                    f"{api_base_url}{EVALUATION_PATH}", json=request_body
                )
            except httpx.TimeoutException:
                elapsed_ms = round((perf_counter() - started_at) * 1000)
                outcomes.append(
                    failed_outcome(
                        case,
                        mode=mode,
                        category="timeout",
                        http_status=None,
                        client_latency_ms=elapsed_ms,
                    )
                )
                continue
            except httpx.RequestError:
                elapsed_ms = round((perf_counter() - started_at) * 1000)
                outcomes.append(
                    failed_outcome(
                        case,
                        mode=mode,
                        category="transport_error",
                        http_status=None,
                        client_latency_ms=elapsed_ms,
                    )
                )
                continue

            elapsed_ms = round((perf_counter() - started_at) * 1000)
            if not response.is_success:
                outcomes.append(
                    failed_outcome(
                        case,
                        mode=mode,
                        category=f"http_{response.status_code}",
                        http_status=response.status_code,
                        client_latency_ms=elapsed_ms,
                        trace_id=_response_trace_id(response),
                    )
                )
                continue
            payload: Any = None
            try:
                payload = response.json()
                if not isinstance(payload, dict):
                    raise EvaluationError("response body must be an object")
                outcomes.append(
                    metric_for_response(
                        case,
                        mode=mode,
                        payload=payload,
                        client_latency_ms=elapsed_ms,
                    )
                )
            except (ValueError, EvaluationError):
                outcomes.append(
                    failed_outcome(
                        case,
                        mode=mode,
                        category="invalid_response",
                        http_status=response.status_code,
                        client_latency_ms=elapsed_ms,
                        trace_id=_response_trace_id(response),
                    )
                )
    return outcomes


def outcomes_as_dicts(outcomes: list[EvaluationOutcome]) -> list[dict[str, Any]]:
    return [asdict(outcome) for outcome in outcomes]


def format_metric(value: float | int | None, *, percent: bool = False) -> str:
    if value is None:
        return "n/a"
    if percent:
        return f"{value:.1%}"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render_report(
    *,
    summaries: list[ModeSummary],
    outcomes: list[EvaluationOutcome],
    metadata: Mapping[str, str | int | float],
) -> str:
    lines = [
        "# Stage 2.5 RAG Evaluation",
        "",
        "> Baseline comparison only. It does not establish semantic answer correctness or faithfulness.",
        "",
        "## Run Metadata",
        "",
    ]
    lines.extend(f"- {key}: `{value}`" for key, value in metadata.items())
    lines.extend(
        [
            "- Retrieval modes: `dense`, `hybrid`, `hybrid_rerank`",
            "- `top_k`: 5 for every request; equal-weight RRF retained",
            "- Each case/mode attempted once; mode order rotates deterministically; no HTTP retries",
            "- Token usage: unavailable from the public response; not added to the API for this evaluation",
            "",
            "## Aggregate Results",
            "",
            "| Mode | Recall@5 | MRR | Citation precision (n) | No citations | Citation mapping errors | Answerability accuracy | Client latency median/p95 ms | Service latency median/p95 ms | Failures |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for summary in summaries:
        lines.append(
            "| {mode} | {recall} (n={retrieval_count}) | {mrr} (n={retrieval_count}) "
            "| {citation} (n={citation_count}) | {no_citations} | {mapping_errors} "
            "| {answerability} | {client_median}/{client_p95} | {service_median}/{service_p95} "
            "| {failures}/{attempts} ({failure_rate}) |".format(
                mode=summary.mode,
                recall=format_metric(summary.mean_recall_at_5),
                mrr=format_metric(summary.mean_mrr),
                citation=format_metric(summary.citation_precision, percent=True),
                retrieval_count=summary.retrieval_case_count,
                citation_count=summary.citation_count,
                no_citations=summary.no_citation_count,
                mapping_errors=summary.citation_mapping_errors,
                answerability=(
                    f"{format_metric(summary.answerability_accuracy, percent=True)} "
                    f"(n={summary.answerability_count})"
                    if summary.answerability_accuracy is not None
                    else "n/a"
                ),
                client_median=format_metric(summary.median_client_latency_ms),
                client_p95=format_metric(summary.p95_client_latency_ms),
                service_median=format_metric(summary.median_service_latency_ms),
                service_p95=format_metric(summary.p95_service_latency_ms),
                failures=summary.failure_count,
                attempts=summary.attempted_count,
                failure_rate=format_metric(summary.failure_rate, percent=True),
            )
        )
    lines.extend(
        [
            "",
            "Retrieval metrics use answerable cases only. Citation precision is pooled across returned citations; "
            "zero-citation responses are counted separately and are not assigned an artificial precision.",
            "Answerability accuracy uses successful HTTP responses only. Request failures remain in the failure-rate denominator.",
            "Client latency includes all attempts; service latency is available only for successful responses.",
            "",
            "## Per-Case Results",
            "",
            "| Case | Mode | Result | Gold answerable | Status | Recall@5 | MRR | Citation precision | Answerability correct | Client ms | Service ms | Trace |",
            "|---|---|---|---|---|---:|---:|---:|---|---:|---:|---|",
        ]
    )
    for outcome in outcomes:
        lines.append(
            "| {case} | {mode} | {result} | {expected} | {status} | {recall} | {mrr} | {citation} | {answerability} "
            "| {client} | {service} | {trace} |".format(
                case=outcome.case_id,
                mode=outcome.mode,
                result=("ok" if outcome.succeeded else f"failed: {outcome.failure_category}"),
                expected=str(outcome.expected_answerable).lower(),
                status=outcome.status or "n/a",
                recall=format_metric(outcome.recall_at_5),
                mrr=format_metric(outcome.reciprocal_rank),
                citation=format_metric(outcome.citation_precision, percent=True),
                answerability=(
                    str(outcome.answerability_correct).lower()
                    if outcome.answerability_correct is not None
                    else "n/a"
                ),
                client=outcome.client_latency_ms,
                service=format_metric(outcome.service_latency_ms),
                trace=outcome.trace_id or "n/a",
            )
        )
    lines.extend(["", "## Failure Categories", ""])
    for summary in summaries:
        categories = ", ".join(
            f"{name}={count}" for name, count in summary.failure_categories.items()
        ) or "none"
        lines.append(
            f"- `{summary.mode}` failures: {categories}; "
            f"citation mapping errors={summary.citation_mapping_errors}; "
            f"responses without citations={summary.no_citation_count}"
        )
    lines.append("")
    return "\n".join(lines)