from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import subprocess
import sys

import httpx

from rag.evaluation import (
    MODES,
    EvaluationError,
    aggregate_outcomes,
    load_evaluation_set,
    outcomes_as_dicts,
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


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLDEN_PATH = REPOSITORY_ROOT / "tests/evaluation/golden.yaml"
DEFAULT_REPORT_PATH = REPOSITORY_ROOT / "docs/eval/stage2-report.md"
DEFAULT_RESULTS_PATH = REPOSITORY_ROOT / "docs/eval/stage2-results.json"
EVALUATOR_SOURCE_PATHS = (
    REPOSITORY_ROOT / "rag/evaluation.py",
    Path(__file__).resolve(),
    REPOSITORY_ROOT / "rag/ingestion/chunk.py",
    REPOSITORY_ROOT / "rag/ingestion/parse.py",
    REPOSITORY_ROOT / "rag/ingestion/manifest.py",
    REPOSITORY_ROOT / "rag/ingestion/models.py",
    REPOSITORY_ROOT / "rag/retrieval/models.py",
    REPOSITORY_ROOT / "apps/ai-api/requirements.txt",
    REPOSITORY_ROOT / "tests/evaluation/requirements.txt",
)


def _git_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _worktree_dirty() -> str:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return str(bool(result.stdout.strip())).lower()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _corpus_chunk_locations() -> dict[str, tuple[str, str | None, str | None]]:
    documents = load_manifest(REPOSITORY_ROOT / "data/generated")
    return {
        chunk.chunk_id: (chunk.document_id, chunk.section, chunk.clause)
        for document in documents
        for chunk in chunk_pages(
            str(document.metadata["doc_id"]),
            extract_pdf_pages(document.pdf_path),
        )
    }


def _package_version(package_name: str) -> str:
    try:
        return version(package_name)
    except PackageNotFoundError:
        return "unknown"


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare dense, hybrid, and hybrid-rerank through the deployed RAG API. "
            "This sends one request per case and mode; it does not retry failures."
        )
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("RAG_API_BASE_URL", "http://127.0.0.1:8000"),
        help="RAG API base URL (default: RAG_API_BASE_URL or localhost:8000)",
    )
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be greater than zero")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        api_base_url = validate_evaluation_url(args.base_url)
        evaluation_set = load_evaluation_set(args.golden)
        corpus_manifest = REPOSITORY_ROOT / "data/generated/manifest.json"
        corpus_manifest_hash = hashlib.sha256(corpus_manifest.read_bytes()).hexdigest()
        if corpus_manifest_hash != evaluation_set.corpus_manifest_sha256:
            raise EvaluationError(
                "golden set corpus fingerprint does not match data/generated/manifest.json"
            )
        validate_expected_chunk_ids(
            evaluation_set.cases,
            _corpus_chunk_locations(),
        )
        report_path, results_path = validate_output_paths(
            args.report,
            args.results,
            repository_root=REPOSITORY_ROOT,
            protected_paths=[
                args.golden,
                corpus_manifest,
                REPOSITORY_ROOT / "rag/evaluation.py",
                Path(__file__),
            ],
        )
    except (EvaluationError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2

    timeout = httpx.Timeout(
        args.timeout_seconds,
        connect=min(args.timeout_seconds, 5.0),
    )
    try:
        with httpx.Client(timeout=timeout) as client:
            outcomes = run_evaluation(
                evaluation_set.cases,
                client=client,
                base_url=api_base_url,
            )
    except EvaluationError as error:
        print(str(error), file=sys.stderr)
        return 2

    summaries = [
        aggregate_outcomes(
            [outcome for outcome in outcomes if outcome.mode == mode]
        )
        for mode in MODES
    ]
    run_timestamp = datetime.now(UTC).isoformat()
    metadata: dict[str, str | int | float] = {
        "run_timestamp_utc": run_timestamp,
        "dataset_sha256": hashlib.sha256(args.golden.read_bytes()).hexdigest(),
        "corpus_manifest_sha256": corpus_manifest_hash,
        "code_revision": _git_revision(),
        "worktree_dirty": _worktree_dirty(),
        "evaluator_sha256": sha256_files(
            list(EVALUATOR_SOURCE_PATHS),
            root=REPOSITORY_ROOT,
        ),
        "python_version": sys.version.split()[0],
        "httpx_version": _package_version("httpx"),
        "pydantic_version": _package_version("pydantic"),
        "pyyaml_version": _package_version("PyYAML"),
        "pypdf_version": _package_version("pypdf"),
        "tiktoken_version": _package_version("tiktoken"),
        "models_observed": ",".join(
            sorted({outcome.model for outcome in outcomes if outcome.model})
        ) or "none",
        "embedding_model_config": "unavailable_not_exposed_by_api",
        "reranker_model_config": "unavailable_not_exposed_by_api",
        "dataset_case_count": len(evaluation_set.cases),
        "requests_per_mode": len(evaluation_set.cases),
        "timeout_seconds": args.timeout_seconds,
    }
    metadata.update(safe_url_metadata(api_base_url))
    report = render_report(
        summaries=summaries,
        outcomes=outcomes,
        metadata=metadata,
    )
    results = {
        "metadata": metadata,
        "summaries": [asdict(summary) for summary in summaries],
        "outcomes": outcomes_as_dicts(outcomes),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    results_path.write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    total_failures = sum(summary.failure_count for summary in summaries)
    print(
        f"attempted={len(outcomes)} failures={total_failures} "
        f"report={report_path} results={results_path}"
    )
    return 1 if total_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())