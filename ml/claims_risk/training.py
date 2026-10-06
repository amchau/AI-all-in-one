from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier

from ml.claims_risk.dataset import (
    ClaimRiskExample,
    DatasetSplits,
    FEATURE_NAMES,
)
from ml.claims_risk.evaluation import EvaluationMetrics, evaluate_predictions, select_recall_threshold

@dataclass(frozen=True)
class TrainedCandidate:
    name: str
    estimator: object
    threshold: float
    validation_metrics: EvaluationMetrics


def train_candidates(
    splits: DatasetSplits,
    seed: int,
    minimum_recall: float,
) -> dict[str, TrainedCandidate]:
    train_features, train_labels = _matrix_and_labels(splits.train)
    validation_features, validation_labels = _matrix_and_labels(splits.validation)
    estimators = {
        "xgboost": XGBClassifier(
            objective="binary:logistic",
            eval_metric="logloss",
            n_estimators=80,
            max_depth=3,
            learning_rate=0.05,
            subsample=1.0,
            colsample_bytree=1.0,
            reg_lambda=1.0,
            tree_method="hist",
            n_jobs=1,
            random_state=seed,
            verbosity=0,
        ),
        "logistic_regression": LogisticRegression(
            max_iter=500,
            random_state=seed,
        ),
        "majority": DummyClassifier(strategy="prior"),
    }
    candidates: dict[str, TrainedCandidate] = {}
    for name, estimator in estimators.items():
        estimator.fit(train_features, train_labels)
        validation_probabilities = tuple(
            float(probability) for probability in estimator.predict_proba(validation_features)[:, 1]
        )
        threshold = select_recall_threshold(
            tuple(int(label) for label in validation_labels),
            validation_probabilities,
            minimum_recall,
        )
        validation_metrics = evaluate_predictions(
            tuple(int(label) for label in validation_labels),
            validation_probabilities,
            threshold,
            minimum_recall,
        )
        candidates[name] = TrainedCandidate(
            name=name,
            estimator=estimator,
            threshold=threshold,
            validation_metrics=validation_metrics,
        )
    return candidates


def evaluate_candidate(
    candidate: TrainedCandidate,
    examples: tuple[ClaimRiskExample, ...],
    minimum_recall: float,
) -> EvaluationMetrics:
    features, labels = _matrix_and_labels(examples)
    probabilities = tuple(
        float(probability) for probability in candidate.estimator.predict_proba(features)[:, 1]
    )
    return evaluate_predictions(
        tuple(int(label) for label in labels),
        probabilities,
        candidate.threshold,
        minimum_recall,
    )


def _matrix_and_labels(
    examples: tuple[ClaimRiskExample, ...],
) -> tuple[np.ndarray, np.ndarray]:
    if not examples:
        raise ValueError("training and evaluation partitions must not be empty")
    features = np.asarray(
        [
            [getattr(example.features, feature_name) for feature_name in FEATURE_NAMES]
            for example in examples
        ],
        dtype=np.float64,
    )
    labels = np.asarray(
        [int(example.refer_for_human_review) for example in examples],
        dtype=np.int8,
    )
    if set(labels.tolist()) != {0, 1}:
        raise ValueError("each partition must contain both labels")
    return features, labels
