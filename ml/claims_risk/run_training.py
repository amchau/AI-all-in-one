from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
import platform

import sklearn
import xgboost

from ml.claims_risk.dataset import ARCHETYPE_PATH, build_dataset, split_by_archetype
from ml.claims_risk.predictor import FEATURE_NAMES
from ml.claims_risk.training import evaluate_candidate, train_candidates

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_PATH = ROOT / "docs" / "eval" / "stage5-risk-model-results.json"
DEFAULT_ARTIFACT_DIR = ROOT / "artifacts" / "claims-risk"
MINIMUM_RECALL = 0.9
DATASET_SEED = 1729
SPLIT_SEED = 31415
MODEL_SEED = 27182
VARIANTS_PER_ARCHETYPE = 30


def run_training(
    results_path: Path = DEFAULT_RESULTS_PATH,
    artifact_dir: Path = DEFAULT_ARTIFACT_DIR,
) -> dict[str, Any]:
    examples = build_dataset(DATASET_SEED, VARIANTS_PER_ARCHETYPE)
    splits = split_by_archetype(examples, SPLIT_SEED)
    candidates = train_candidates(splits, MODEL_SEED, MINIMUM_RECALL)
    holdout_metrics = {
        name: evaluate_candidate(candidate, splits.test, MINIMUM_RECALL)
        for name, candidate in candidates.items()
    }
    xgboost_metrics = holdout_metrics["xgboost"]
    baseline_precision = max(
        holdout_metrics["logistic_regression"].precision,
        holdout_metrics["majority"].precision,
    )
    promotion_passed = (
        xgboost_metrics.recall_gate_passed
        and xgboost_metrics.precision > baseline_precision
    )
    dataset_hash = _sha256_file(ARCHETYPE_PATH)
    results = {
        "dataset_version": "synthetic-archetypes-v1",
        "dataset_sha256": dataset_hash,
        "seeds": {
            "dataset": DATASET_SEED,
            "split": SPLIT_SEED,
            "model": MODEL_SEED,
        },
        "variants_per_archetype": VARIANTS_PER_ARCHETYPE,
        "archetypes": _archetype_counts(examples),
        "rows": {
            "total": len(examples),
            "train": len(splits.train),
            "validation": len(splits.validation),
            "test": len(splits.test),
        },
        "split_archetypes": {
            name: _archetype_counts(partition)
            for name, partition in (
                ("train", splits.train),
                ("validation", splits.validation),
                ("test", splits.test),
            )
        },
        "runtime": {
            "python": platform.python_version(),
            "scikit_learn": sklearn.__version__,
            "xgboost": xgboost.__version__,
        },
        "minimum_recall": MINIMUM_RECALL,
        "feature_names": list(FEATURE_NAMES),
        "candidates": {
            name: {
                "validation_threshold": candidate.threshold,
                "validation": candidate.validation_metrics.__dict__,
                "holdout": metrics.__dict__,
            }
            for name, candidate in candidates.items()
            for metrics in (holdout_metrics[name],)
        },
        "promotion": {
            "passed": promotion_passed,
            "reason": "xgboost_recall_and_precision_gates_passed"
            if promotion_passed
            else "xgboost_did_not_beat_baseline_or_meet_recall_gate",
            "xgboost_must_meet_recall_gate": True,
            "xgboost_precision_must_exceed_best_baseline": True,
        },
        "limitations": [
            "Labels are derived from a synthetic rule and do not represent fraud ground truth.",
            "Generated variants do not increase the count of independent archetypes.",
            "Holdout metrics do not establish real-world quality or operational performance.",
        ],
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if promotion_passed:
        candidate = candidates["xgboost"]
        temporary_model_path = artifact_dir / "model.tmp.json"
        final_model_path = artifact_dir / "model.json"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        candidate.estimator.save_model(temporary_model_path)
        model_sha256 = _sha256_file(temporary_model_path)
        model_version = f"stage5-{model_sha256[:12]}"
        metadata = {
            "model_version": model_version,
            "dataset_version": results["dataset_version"],
            "dataset_sha256": dataset_hash,
            "model_sha256": model_sha256,
            "feature_names": list(FEATURE_NAMES),
            "threshold": candidate.threshold,
            "triage_margin": 0.05,
            "minimum_recall": MINIMUM_RECALL,
            "synthetic_only": True,
        }
        temporary_model_path.replace(final_model_path)
        (artifact_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        results["promotion"]["model_version"] = model_version
        results_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return results


def _archetype_counts(examples: tuple[Any, ...]) -> dict[str, int]:
    counts = {"negative": set(), "positive": set()}
    for example in examples:
        bucket = "positive" if example.refer_for_human_review else "negative"
        counts[bucket].add(example.archetype_id)
    return {name: len(archetype_ids) for name, archetype_ids in counts.items()}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Train and evaluate the synthetic claims risk model")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACT_DIR)
    arguments = parser.parse_args()
    try:
        results = run_training(arguments.results, arguments.artifacts)
    except ValueError as error:
        print(f"Training stopped: {error}", file=sys.stderr)
        return 2
    print(json.dumps(results["promotion"], sort_keys=True))
    return 0 if results["promotion"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
