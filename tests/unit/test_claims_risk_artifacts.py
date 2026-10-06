from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ml.claims_risk import artifacts
from ml.claims_risk.artifacts import validate_promoted_artifact


def _write_promotion_files(directory: Path) -> tuple[Path, Path, Path]:
    model_path = directory / "model.json"
    metadata_path = directory / "metadata.json"
    results_path = directory / "results.json"
    model_path.write_bytes(b"synthetic model bytes")
    model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    metadata_path.write_text(
        json.dumps(
            {
                "model_version": "stage5-test",
                "model_sha256": model_hash,
                "dataset_sha256": "dataset-sha",
                "synthetic_only": True,
            }
        ),
        encoding="utf-8",
    )
    results_path.write_text(
        json.dumps(
            {
                "dataset_sha256": "dataset-sha",
                "promotion": {"passed": True, "model_version": "stage5-test"},
            }
        ),
        encoding="utf-8",
    )
    return model_path, metadata_path, results_path


def test_validates_current_promoted_model_and_dataset(tmp_path: Path) -> None:
    model_path, metadata_path, results_path = _write_promotion_files(tmp_path)

    validate_promoted_artifact(model_path, metadata_path, results_path)


def test_rejects_artifact_after_latest_evaluation_failed(tmp_path: Path) -> None:
    model_path, metadata_path, results_path = _write_promotion_files(tmp_path)
    report = json.loads(results_path.read_text(encoding="utf-8"))
    report["promotion"]["passed"] = False
    results_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="promotion did not pass"):
        validate_promoted_artifact(model_path, metadata_path, results_path)


def test_rejects_artifact_hash_or_version_mismatch(tmp_path: Path) -> None:
    model_path, metadata_path, results_path = _write_promotion_files(tmp_path)
    model_path.write_bytes(b"different model bytes")

    with pytest.raises(ValueError, match="model hash"):
        validate_promoted_artifact(model_path, metadata_path, results_path)


def test_rejects_promotion_version_mismatch(tmp_path: Path) -> None:
    model_path, metadata_path, results_path = _write_promotion_files(tmp_path)
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results["promotion"]["model_version"] = "older-model"
    results_path.write_text(json.dumps(results), encoding="utf-8")

    with pytest.raises(ValueError, match="model version"):
        validate_promoted_artifact(model_path, metadata_path, results_path)


def test_rejects_dataset_hash_mismatch(tmp_path: Path) -> None:
    model_path, metadata_path, results_path = _write_promotion_files(tmp_path)
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results["dataset_sha256"] = "older-dataset"
    results_path.write_text(json.dumps(results), encoding="utf-8")

    with pytest.raises(ValueError, match="dataset hash"):
        validate_promoted_artifact(model_path, metadata_path, results_path)


def test_rejects_non_synthetic_artifact(tmp_path: Path) -> None:
    model_path, metadata_path, results_path = _write_promotion_files(tmp_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["synthetic_only"] = False
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="synthetic-only"):
        validate_promoted_artifact(model_path, metadata_path, results_path)


def test_cli_reports_validation_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_path, metadata_path, results_path = _write_promotion_files(tmp_path)
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results["promotion"]["passed"] = False
    results_path.write_text(json.dumps(results), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "artifacts",
            "--model",
            str(model_path),
            "--metadata",
            str(metadata_path),
            "--results",
            str(results_path),
        ],
    )

    assert artifacts.main() == 1
