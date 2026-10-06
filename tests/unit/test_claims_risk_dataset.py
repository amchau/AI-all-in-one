from __future__ import annotations

from dataclasses import asdict

import pytest

from ml.claims_risk.dataset import (
    ClaimRiskFeatures,
    build_dataset,
    refer_for_human_review,
    split_by_archetype,
)


def test_dataset_is_reproducible_for_same_seed() -> None:
    first = build_dataset(seed=17, variants_per_archetype=3)
    second = build_dataset(seed=17, variants_per_archetype=3)

    assert [asdict(row) for row in first] == [asdict(row) for row in second]


def test_dataset_has_unique_rows_and_both_labels() -> None:
    dataset = build_dataset(seed=17, variants_per_archetype=3)

    assert len({row.row_id for row in dataset}) == len(dataset)
    assert {row.refer_for_human_review for row in dataset} == {False, True}
    assert len({row.archetype_id for row in dataset}) >= 30


def test_labels_match_documented_synthetic_referral_rubric() -> None:
    dataset = build_dataset(seed=17, variants_per_archetype=3)

    assert all(
        row.refer_for_human_review == refer_for_human_review(row.features)
        for row in dataset
    )
    assert all(row.label_reason for row in dataset)


def test_features_are_bounded_and_reject_extra_identity_fields() -> None:
    feature_names = set(ClaimRiskFeatures.model_fields)
    assert feature_names == {
        "duplicate_document_count",
        "date_inconsistency_count",
        "missing_required_evidence_count",
        "prior_open_claim_count",
        "estimate_limit_ratio",
    }

    with pytest.raises(ValueError):
        ClaimRiskFeatures(
            duplicate_document_count=0,
            date_inconsistency_count=0,
            missing_required_evidence_count=0,
            prior_open_claim_count=0,
            estimate_limit_ratio=0.5,
            customer_id="CUST-123",
        )

    with pytest.raises(ValueError):
        ClaimRiskFeatures(
            duplicate_document_count=True,
            date_inconsistency_count=0,
            missing_required_evidence_count=0,
            prior_open_claim_count=0,
            estimate_limit_ratio=0.5,
        )


def test_split_keeps_archetypes_disjoint_and_both_labels_present() -> None:
    dataset = build_dataset(seed=17, variants_per_archetype=3)
    splits = split_by_archetype(dataset, seed=29)
    train_ids = {row.archetype_id for row in splits.train}
    validation_ids = {row.archetype_id for row in splits.validation}
    test_ids = {row.archetype_id for row in splits.test}

    assert train_ids.isdisjoint(validation_ids)
    assert train_ids.isdisjoint(test_ids)
    assert validation_ids.isdisjoint(test_ids)
    assert all(
        {row.refer_for_human_review for row in partition} == {False, True}
        for partition in (splits.train, splits.validation, splits.test)
    )


def test_split_is_deterministic() -> None:
    dataset = build_dataset(seed=17, variants_per_archetype=3)
    first = split_by_archetype(dataset, seed=29)
    second = split_by_archetype(dataset, seed=29)

    assert first == second


def test_generator_rejects_non_positive_variant_count() -> None:
    with pytest.raises(ValueError, match="variants_per_archetype"):
        build_dataset(seed=17, variants_per_archetype=0)
