from __future__ import annotations

import pytest

from ml.claims_risk.evaluation import (
    evaluate_predictions,
    select_recall_threshold,
)


def test_threshold_maximizes_precision_while_meeting_recall_target() -> None:
    labels = (1, 1, 0, 0)
    probabilities = (0.8, 0.7, 0.4, 0.1)

    threshold = select_recall_threshold(labels, probabilities, minimum_recall=0.9)

    assert threshold == 0.7


def test_threshold_rejects_inputs_without_positive_examples() -> None:
    with pytest.raises(ValueError, match="positive examples"):
        select_recall_threshold((0, 0), (0.2, 0.4), minimum_recall=0.9)


def test_threshold_rejects_invalid_probability_or_recall_values() -> None:
    with pytest.raises(ValueError, match="probabilities"):
        select_recall_threshold((0, 1), (0.2, 1.2), minimum_recall=0.9)
    with pytest.raises(ValueError, match="minimum_recall"):
        select_recall_threshold((0, 1), (0.2, 0.8), minimum_recall=1.1)


def test_evaluation_reports_metrics_and_recall_gate() -> None:
    metrics = evaluate_predictions(
        labels=(1, 1, 0, 0),
        probabilities=(0.8, 0.7, 0.4, 0.1),
        threshold=0.7,
        minimum_recall=0.9,
    )

    assert metrics.true_positive == 2
    assert metrics.false_negative == 0
    assert metrics.false_positive == 0
    assert metrics.true_negative == 2
    assert metrics.recall == 1.0
    assert metrics.precision == 1.0
    assert metrics.review_volume == 2
    assert metrics.review_volume_fraction == 0.5
    assert metrics.expected_calibration_error == 0.25
    assert metrics.recall_gate_passed is True
    assert 0.0 <= metrics.pr_auc <= 1.0
    assert 0.0 <= metrics.brier_score <= 1.0


def test_evaluation_marks_failed_recall_gate() -> None:
    metrics = evaluate_predictions(
        labels=(1, 1, 0, 0),
        probabilities=(0.9, 0.3, 0.2, 0.1),
        threshold=0.8,
        minimum_recall=0.9,
    )

    assert metrics.recall == 0.5
    assert metrics.recall_gate_passed is False


def test_evaluation_rejects_mismatched_vectors() -> None:
    with pytest.raises(ValueError, match="same non-zero length"):
        evaluate_predictions((1,), (0.2, 0.3), 0.5, 0.9)
