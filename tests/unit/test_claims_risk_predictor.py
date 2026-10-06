from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import xgboost as xgb

from ml.claims_risk.dataset import ClaimRiskFeatures
from ml.claims_risk.predictor import FEATURE_NAMES, load_predictor


def _write_model_artifact(directory: Path) -> tuple[Path, Path]:
	model_path = directory / "model.json"
	metadata_path = directory / "metadata.json"
	features = np.asarray(
		[
			[0, 0, 0, 0, 0.2],
			[2, 0, 0, 0, 0.3],
			[0, 2, 0, 0, 0.4],
			[0, 0, 3, 0, 0.5],
			[0, 0, 0, 4, 0.6],
			[1, 1, 1, 1, 0.7],
		],
		dtype=np.float64,
	)
	labels = np.asarray([0, 1, 1, 1, 1, 0], dtype=np.int8)
	model = xgb.XGBClassifier(
		n_estimators=3,
		max_depth=2,
		tree_method="hist",
		n_jobs=1,
		random_state=11,
		verbosity=0,
	)
	model.fit(features, labels)
	model.save_model(model_path)
	digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
	metadata = {
		"model_version": "test-model",
		"model_sha256": digest,
		"feature_names": list(FEATURE_NAMES),
		"threshold": 0.7,
		"triage_margin": 0.05,
	}
	metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
	return model_path, metadata_path


def test_predictor_loads_versioned_model_and_scores_features(tmp_path: Path) -> None:
	model_path, metadata_path = _write_model_artifact(tmp_path)

	predictor = load_predictor(model_path, metadata_path)
	probability = predictor.predict_probability(
		ClaimRiskFeatures(
			duplicate_document_count=2,
			date_inconsistency_count=0,
			missing_required_evidence_count=0,
			prior_open_claim_count=0,
			estimate_limit_ratio=0.5,
		)
	)

	assert predictor.model_version == "test-model"
	assert predictor.threshold == 0.7
	assert predictor.triage_margin == 0.05
	assert 0.0 <= probability <= 1.0


def test_predictor_rejects_model_hash_mismatch(tmp_path: Path) -> None:
	model_path, metadata_path = _write_model_artifact(tmp_path)
	model_path.write_bytes(model_path.read_bytes() + b"changed")

	with pytest.raises(ValueError, match="hash"):
		load_predictor(model_path, metadata_path)


def test_predictor_rejects_feature_schema_mismatch(tmp_path: Path) -> None:
	model_path, metadata_path = _write_model_artifact(tmp_path)
	metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
	metadata["feature_names"] = ["customer_id"]
	metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

	with pytest.raises(ValueError, match="feature schema"):
		load_predictor(model_path, metadata_path)
