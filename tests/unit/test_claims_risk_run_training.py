from __future__ import annotations

import json
from pathlib import Path

from ml.claims_risk import run_training
from ml.claims_risk.evaluation import EvaluationMetrics
from ml.claims_risk.training import TrainedCandidate


def test_training_run_writes_promoted_artifact_and_provenance(tmp_path: Path) -> None:
    results_path = tmp_path / "results.json"
    artifact_dir = tmp_path / "artifacts"

    results = run_training.run_training(results_path, artifact_dir)

    assert results["promotion"]["passed"] is True
    assert results["runtime"]["python"].startswith("3.12.")
    assert results["split_archetypes"]["test"] == {"negative": 4, "positive": 5}
    assert (artifact_dir / "model.json").is_file()
    metadata = json.loads((artifact_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["model_version"] == results["promotion"]["model_version"]


def test_failed_promotion_writes_results_without_creating_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    failed_metrics = EvaluationMetrics(
        true_positive=1,
        false_positive=4,
        true_negative=1,
        false_negative=1,
        recall=0.5,
        precision=0.2,
        review_volume=5,
        review_volume_fraction=0.5,
        pr_auc=0.5,
        brier_score=0.4,
        expected_calibration_error=0.3,
        recall_gate_passed=False,
    )
    baseline_metrics = EvaluationMetrics(
        true_positive=2,
        false_positive=0,
        true_negative=5,
        false_negative=0,
        recall=1.0,
        precision=1.0,
        review_volume=2,
        review_volume_fraction=0.2,
        pr_auc=1.0,
        brier_score=0.1,
        expected_calibration_error=0.1,
        recall_gate_passed=True,
    )
    candidates = {
        name: TrainedCandidate(
            name=name,
            estimator=object(),
            threshold=0.5,
            validation_metrics=baseline_metrics,
        )
        for name in ("xgboost", "logistic_regression", "majority")
    }
    monkeypatch.setattr(run_training, "train_candidates", lambda *args: candidates)
    monkeypatch.setattr(
        run_training,
        "evaluate_candidate",
        lambda candidate, examples, minimum_recall: (
            failed_metrics if candidate.name == "xgboost" else baseline_metrics
        ),
    )
    results_path = tmp_path / "results.json"
    artifact_dir = tmp_path / "artifacts"

    results = run_training.run_training(results_path, artifact_dir)

    assert results["promotion"]["passed"] is False
    assert results_path.is_file()
    assert not artifact_dir.exists()