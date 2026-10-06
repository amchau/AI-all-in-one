from __future__ import annotations

from ml.claims_risk.dataset import FEATURE_NAMES, build_dataset, split_by_archetype
from ml.claims_risk.training import evaluate_candidate, train_candidates


def test_candidates_train_with_validation_thresholds_and_holdout_evaluation() -> None:
    dataset = build_dataset(seed=17, variants_per_archetype=6)
    splits = split_by_archetype(dataset, seed=29)

    candidates = train_candidates(splits, seed=41, minimum_recall=0.9)

    assert set(candidates) == {"xgboost", "logistic_regression", "majority"}
    for candidate in candidates.values():
        assert candidate.threshold is not None
        assert candidate.validation_metrics.recall >= 0.9
        holdout_metrics = evaluate_candidate(candidate, splits.test, minimum_recall=0.9)
        assert holdout_metrics.true_positive + holdout_metrics.false_negative > 0


def test_training_feature_order_comes_from_dataset_contract() -> None:
    from ml.claims_risk.training import FEATURE_NAMES as TRAINING_FEATURE_NAMES
    from ml.claims_risk.predictor import FEATURE_NAMES as PREDICTOR_FEATURE_NAMES

    assert TRAINING_FEATURE_NAMES is FEATURE_NAMES
    assert PREDICTOR_FEATURE_NAMES is FEATURE_NAMES


def test_training_is_reproducible_for_fixed_data_and_seed() -> None:
    dataset = build_dataset(seed=17, variants_per_archetype=4)
    splits = split_by_archetype(dataset, seed=29)

    first = train_candidates(splits, seed=41, minimum_recall=0.9)
    second = train_candidates(splits, seed=41, minimum_recall=0.9)

    assert {
        name: candidate.threshold for name, candidate in first.items()
    } == {
        name: candidate.threshold for name, candidate in second.items()
    }
    assert {
        name: candidate.validation_metrics for name, candidate in first.items()
    } == {
        name: candidate.validation_metrics for name, candidate in second.items()
    }
