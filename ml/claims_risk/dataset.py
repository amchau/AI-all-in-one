from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LabelReason = Literal[
    "duplicate_documents",
    "date_inconsistency",
    "evidence_gap",
    "repeat_open_claims",
    "no_referral_signal",
]

ARCHETYPE_PATH = Path(__file__).resolve().parents[2] / "data" / "risk" / "claim-archetypes.csv"
EXPECTED_COLUMNS = (
    "archetype_id",
    "duplicate_document_count",
    "date_inconsistency_count",
    "missing_required_evidence_count",
    "prior_open_claim_count",
    "estimate_limit_ratio",
    "refer_for_human_review",
    "label_reason",
)
FEATURE_NAMES = (
    "duplicate_document_count",
    "date_inconsistency_count",
    "missing_required_evidence_count",
    "prior_open_claim_count",
    "estimate_limit_ratio",
)


class ClaimRiskFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    duplicate_document_count: int = Field(ge=0, le=3)
    date_inconsistency_count: int = Field(ge=0, le=3)
    missing_required_evidence_count: int = Field(ge=0, le=4)
    prior_open_claim_count: int = Field(ge=0, le=5)
    estimate_limit_ratio: float = Field(ge=0.0, le=2.0, allow_inf_nan=False)


@dataclass(frozen=True)
class ClaimArchetype:
    archetype_id: str
    features: ClaimRiskFeatures
    refer_for_human_review: bool
    label_reason: LabelReason


@dataclass(frozen=True)
class ClaimRiskExample:
    row_id: str
    archetype_id: str
    features: ClaimRiskFeatures
    refer_for_human_review: bool
    label_reason: LabelReason
    generator_seed: int


@dataclass(frozen=True)
class DatasetSplits:
    train: tuple[ClaimRiskExample, ...]
    validation: tuple[ClaimRiskExample, ...]
    test: tuple[ClaimRiskExample, ...]


def referral_label_reason(features: ClaimRiskFeatures) -> LabelReason:
    if features.duplicate_document_count >= 2:
        return "duplicate_documents"
    if features.date_inconsistency_count >= 2:
        return "date_inconsistency"
    if features.missing_required_evidence_count >= 3:
        return "evidence_gap"
    if features.prior_open_claim_count >= 4:
        return "repeat_open_claims"
    return "no_referral_signal"


def refer_for_human_review(features: ClaimRiskFeatures) -> bool:
    return referral_label_reason(features) != "no_referral_signal"


def load_archetypes(path: Path = ARCHETYPE_PATH) -> tuple[ClaimArchetype, ...]:
    try:
        with path.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
                raise ValueError("archetype CSV columns do not match the schema")
            archetypes = tuple(_parse_archetype(row, row_number) for row_number, row in enumerate(reader, 2))
    except OSError as error:
        raise ValueError("could not read archetype CSV") from error

    if not archetypes:
        raise ValueError("archetype CSV must contain at least one row")
    if len({archetype.archetype_id for archetype in archetypes}) != len(archetypes):
        raise ValueError("archetype IDs must be unique")
    return archetypes


def build_dataset(
    seed: int,
    variants_per_archetype: int,
    archetype_path: Path = ARCHETYPE_PATH,
) -> tuple[ClaimRiskExample, ...]:
    if variants_per_archetype < 1 or variants_per_archetype > 100:
        raise ValueError("variants_per_archetype must be between 1 and 100")

    generator = random.Random(seed)
    examples: list[ClaimRiskExample] = []
    for archetype in load_archetypes(archetype_path):
        for variant_index in range(variants_per_archetype):
            features = _variant_features(archetype.features, generator)
            label_reason = referral_label_reason(features)
            if label_reason != archetype.label_reason:
                raise ValueError("variant changed its archetype label or rationale")
            examples.append(
                ClaimRiskExample(
                    row_id=f"{archetype.archetype_id}-V{variant_index + 1:03d}",
                    archetype_id=archetype.archetype_id,
                    features=features,
                    refer_for_human_review=archetype.refer_for_human_review,
                    label_reason=archetype.label_reason,
                    generator_seed=seed,
                )
            )
    return tuple(examples)


def split_by_archetype(
    examples: tuple[ClaimRiskExample, ...],
    seed: int,
) -> DatasetSplits:
    rows_by_archetype: dict[str, list[ClaimRiskExample]] = {}
    labels_by_archetype: dict[str, bool] = {}
    for example in examples:
        previous_label = labels_by_archetype.setdefault(
            example.archetype_id, example.refer_for_human_review
        )
        if previous_label != example.refer_for_human_review:
            raise ValueError("an archetype cannot contain multiple labels")
        rows_by_archetype.setdefault(example.archetype_id, []).append(example)

    archetype_ids_by_label = {
        label: [
            archetype_id
            for archetype_id, archetype_label in labels_by_archetype.items()
            if archetype_label is label
        ]
        for label in (False, True)
    }
    if any(len(archetype_ids) < 5 for archetype_ids in archetype_ids_by_label.values()):
        raise ValueError("each label needs at least five independent archetypes")

    generator = random.Random(seed)
    split_ids: dict[str, set[str]] = {"train": set(), "validation": set(), "test": set()}
    for archetype_ids in archetype_ids_by_label.values():
        shuffled_ids = list(archetype_ids)
        generator.shuffle(shuffled_ids)
        train_count = round(len(shuffled_ids) * 0.6)
        validation_count = round(len(shuffled_ids) * 0.2)
        if train_count < 1 or validation_count < 1 or train_count + validation_count >= len(shuffled_ids):
            raise ValueError("not enough archetypes for train, validation, and test splits")
        split_ids["train"].update(shuffled_ids[:train_count])
        split_ids["validation"].update(shuffled_ids[train_count : train_count + validation_count])
        split_ids["test"].update(shuffled_ids[train_count + validation_count :])

    partitions = {
        name: tuple(example for example in examples if example.archetype_id in archetype_ids)
        for name, archetype_ids in split_ids.items()
    }
    return DatasetSplits(
        train=partitions["train"],
        validation=partitions["validation"],
        test=partitions["test"],
    )


def _parse_archetype(row: dict[str, str | None], row_number: int) -> ClaimArchetype:
    try:
        archetype_id = row["archetype_id"]
        if not archetype_id:
            raise ValueError("archetype ID cannot be empty")
        features = ClaimRiskFeatures(
            duplicate_document_count=int(row["duplicate_document_count"] or ""),
            date_inconsistency_count=int(row["date_inconsistency_count"] or ""),
            missing_required_evidence_count=int(row["missing_required_evidence_count"] or ""),
            prior_open_claim_count=int(row["prior_open_claim_count"] or ""),
            estimate_limit_ratio=float(row["estimate_limit_ratio"] or ""),
        )
        label_value = row["refer_for_human_review"]
        if label_value not in {"true", "false"}:
            raise ValueError("label must be 'true' or 'false'")
        expected_label = label_value == "true"
        expected_reason = row["label_reason"]
        actual_reason = referral_label_reason(features)
        if expected_label != refer_for_human_review(features) or expected_reason != actual_reason:
            raise ValueError("archetype label or reason does not match the synthetic rubric")
        return ClaimArchetype(
            archetype_id=archetype_id,
            features=features,
            refer_for_human_review=expected_label,
            label_reason=actual_reason,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid archetype CSV row {row_number}: {error}") from error


def _variant_features(
    features: ClaimRiskFeatures,
    generator: random.Random,
) -> ClaimRiskFeatures:
    duplicate_range = (2, 3) if features.duplicate_document_count >= 2 else (0, 1)
    date_range = (2, 3) if features.date_inconsistency_count >= 2 else (0, 1)
    evidence_range = (3, 4) if features.missing_required_evidence_count >= 3 else (0, 2)
    prior_range = (4, 5) if features.prior_open_claim_count >= 4 else (0, 3)
    estimate_ratio = min(2.0, max(0.0, features.estimate_limit_ratio + generator.uniform(-0.15, 0.15)))
    return ClaimRiskFeatures(
        duplicate_document_count=generator.randint(*duplicate_range),
        date_inconsistency_count=generator.randint(*date_range),
        missing_required_evidence_count=generator.randint(*evidence_range),
        prior_open_claim_count=generator.randint(*prior_range),
        estimate_limit_ratio=round(estimate_ratio, 4),
    )
