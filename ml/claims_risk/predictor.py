from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Protocol

import numpy as np
import xgboost as xgb

from ml.claims_risk.dataset import ClaimRiskFeatures, FEATURE_NAMES


class RiskPredictor(Protocol):
    model_version: str
    threshold: float
    triage_margin: float

    def predict_probability(self, features: ClaimRiskFeatures) -> float:
        """Return the model's internal referral probability."""


class XGBoostRiskPredictor:
    def __init__(self, model_path: Path, metadata_path: Path) -> None:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("could not read model metadata") from error
        if metadata.get("feature_names") != list(FEATURE_NAMES):
            raise ValueError("model feature schema does not match the service")
        expected_model_hash = metadata.get("model_sha256")
        try:
            actual_model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
        except OSError as error:
            raise ValueError("could not read model artifact") from error
        if not isinstance(expected_model_hash, str) or actual_model_hash != expected_model_hash:
            raise ValueError("model artifact hash does not match metadata")
        model_version = metadata.get("model_version")
        threshold = metadata.get("threshold")
        triage_margin = metadata.get("triage_margin")
        if not isinstance(model_version, str) or not model_version:
            raise ValueError("model metadata has no version")
        if not isinstance(threshold, (int, float)) or not 0.0 <= threshold <= 1.0:
            raise ValueError("model metadata has an invalid threshold")
        if not isinstance(triage_margin, (int, float)) or not 0.0 <= triage_margin <= 0.5:
            raise ValueError("model metadata has an invalid triage margin")

        model = xgb.Booster()
        try:
            model.load_model(model_path)
        except (OSError, ValueError, xgb.core.XGBoostError) as error:
            raise ValueError("could not load model artifact") from error
        self._model = model
        self.model_version = model_version
        self.threshold = float(threshold)
        self.triage_margin = float(triage_margin)

    def predict_probability(self, features: ClaimRiskFeatures) -> float:
        feature_values = np.asarray(
            [[getattr(features, name) for name in FEATURE_NAMES]],
            dtype=np.float64,
        )
        return float(self._model.predict(xgb.DMatrix(feature_values))[0])


def load_predictor(model_path: Path, metadata_path: Path) -> XGBoostRiskPredictor:
    return XGBoostRiskPredictor(model_path, metadata_path)
