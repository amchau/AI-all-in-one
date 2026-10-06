from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


def validate_promoted_artifact(
    model_path: Path,
    metadata_path: Path,
    results_path: Path,
) -> dict[str, Any]:
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        results = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("could not read model promotion metadata") from error

    promotion = results.get("promotion")
    if not isinstance(promotion, dict) or promotion.get("passed") is not True:
        raise ValueError("latest model promotion did not pass")
    model_version = metadata.get("model_version")
    if not isinstance(model_version, str) or not model_version:
        raise ValueError("model metadata is missing model version")
    if promotion.get("model_version") != model_version:
        raise ValueError("model version does not match latest evaluation")
    dataset_hash = metadata.get("dataset_sha256")
    if not isinstance(dataset_hash, str) or dataset_hash != results.get("dataset_sha256"):
        raise ValueError("dataset hash does not match latest evaluation")
    if metadata.get("synthetic_only") is not True:
        raise ValueError("model metadata is not marked synthetic-only")
    try:
        actual_model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    except OSError as error:
        raise ValueError("could not read model artifact") from error
    if actual_model_hash != metadata.get("model_sha256"):
        raise ValueError("model hash does not match metadata")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the promoted claims risk artifact")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        metadata = validate_promoted_artifact(
            arguments.model,
            arguments.metadata,
            arguments.results,
        )
    except ValueError as error:
        print(f"Artifact validation failed: {error}", file=sys.stderr)
        return 1
    print(f"Validated promoted model {metadata['model_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
