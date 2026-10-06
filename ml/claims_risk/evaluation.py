from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class EvaluationMetrics:
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    recall: float
    precision: float
    review_volume: int
    review_volume_fraction: float
    pr_auc: float
    brier_score: float
    expected_calibration_error: float
    recall_gate_passed: bool


def select_recall_threshold(
    labels: tuple[int, ...],
    probabilities: tuple[float, ...],
    minimum_recall: float,
) -> float:
    _validate_predictions(labels, probabilities)
    if not math.isfinite(minimum_recall) or not 0.0 < minimum_recall <= 1.0:
        raise ValueError("minimum_recall must be in (0, 1]")
    positive_count = sum(labels)
    if positive_count == 0:
        raise ValueError("threshold selection requires positive examples")

    candidates: list[tuple[float, float]] = []
    for threshold in sorted(set(probabilities), reverse=True):
        predicted = tuple(probability >= threshold for probability in probabilities)
        true_positive = sum(label == 1 and prediction for label, prediction in zip(labels, predicted))
        false_positive = sum(label == 0 and prediction for label, prediction in zip(labels, predicted))
        recall = true_positive / positive_count
        if recall >= minimum_recall:
            precision = true_positive / (true_positive + false_positive)
            candidates.append((precision, threshold))
    if not candidates:
        raise ValueError("no threshold meets minimum_recall")
    return max(candidates)[1]


def evaluate_predictions(
    labels: tuple[int, ...],
    probabilities: tuple[float, ...],
    threshold: float,
    minimum_recall: float,
) -> EvaluationMetrics:
    _validate_predictions(labels, probabilities)
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be in [0, 1]")
    if not math.isfinite(minimum_recall) or not 0.0 < minimum_recall <= 1.0:
        raise ValueError("minimum_recall must be in (0, 1]")

    predicted = tuple(probability >= threshold for probability in probabilities)
    true_positive = sum(label == 1 and prediction for label, prediction in zip(labels, predicted))
    false_positive = sum(label == 0 and prediction for label, prediction in zip(labels, predicted))
    true_negative = sum(label == 0 and not prediction for label, prediction in zip(labels, predicted))
    false_negative = sum(label == 1 and not prediction for label, prediction in zip(labels, predicted))
    positive_count = true_positive + false_negative
    predicted_positive_count = true_positive + false_positive
    recall = true_positive / positive_count
    precision = true_positive / predicted_positive_count if predicted_positive_count else 0.0
    review_volume = predicted_positive_count
    return EvaluationMetrics(
        true_positive=true_positive,
        false_positive=false_positive,
        true_negative=true_negative,
        false_negative=false_negative,
        recall=recall,
        precision=precision,
        review_volume=review_volume,
        review_volume_fraction=review_volume / len(labels),
        pr_auc=_average_precision(labels, probabilities),
        brier_score=sum(
            (probability - label) ** 2 for label, probability in zip(labels, probabilities)
        )
        / len(labels),
        expected_calibration_error=_expected_calibration_error(labels, probabilities),
        recall_gate_passed=recall >= minimum_recall,
    )


def _average_precision(
    labels: tuple[int, ...],
    probabilities: tuple[float, ...],
) -> float:
    positive_count = sum(labels)
    if positive_count == 0:
        return 0.0

    ranked = sorted(zip(probabilities, labels), reverse=True)
    true_positive = 0
    false_positive = 0
    previous_recall = 0.0
    average_precision = 0.0
    index = 0
    while index < len(ranked):
        threshold = ranked[index][0]
        while index < len(ranked) and ranked[index][0] == threshold:
            if ranked[index][1] == 1:
                true_positive += 1
            else:
                false_positive += 1
            index += 1
        recall = true_positive / positive_count
        precision = true_positive / (true_positive + false_positive)
        average_precision += (recall - previous_recall) * precision
        previous_recall = recall
    return average_precision


def _expected_calibration_error(
    labels: tuple[int, ...],
    probabilities: tuple[float, ...],
    bin_count: int = 10,
) -> float:
    bins: list[list[tuple[int, float]]] = [[] for _ in range(bin_count)]
    for label, probability in zip(labels, probabilities):
        bin_index = min(int(probability * bin_count), bin_count - 1)
        bins[bin_index].append((label, probability))

    weighted_error = 0.0
    for calibration_bin in bins:
        if calibration_bin:
            mean_label = sum(label for label, _ in calibration_bin) / len(calibration_bin)
            mean_probability = sum(probability for _, probability in calibration_bin) / len(calibration_bin)
            weighted_error += (
                len(calibration_bin)
                / len(labels)
                * abs(mean_label - mean_probability)
            )
    return weighted_error


def _validate_predictions(
    labels: tuple[int, ...],
    probabilities: tuple[float, ...],
) -> None:
    if not labels or len(labels) != len(probabilities):
        raise ValueError("labels and probabilities must have the same non-zero length")
    if any(label not in (0, 1) for label in labels):
        raise ValueError("labels must contain only 0 or 1")
    if any(not math.isfinite(probability) or not 0.0 <= probability <= 1.0 for probability in probabilities):
        raise ValueError("probabilities must be finite values in [0, 1]")
    if sum(labels) == 0:
        raise ValueError("evaluation requires positive examples")
