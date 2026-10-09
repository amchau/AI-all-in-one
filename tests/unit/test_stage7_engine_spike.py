"""Tests for the isolated Stage 7 workflow-engine comparison spike."""

import pytest

from spikes.stage7_engine_comparison import (
    action_fingerprint,
    apply_disposition,
    resolve_idempotent_replay,
    resume_for_information,
)


@pytest.mark.parametrize(
    ("disposition", "expected_state"),
    [
        ("continue", "completed"),
        ("request_info", "needs_more_information"),
        ("stop", "cancelled"),
    ],
)
def test_disposition_maps_to_the_planned_state(
    disposition: str,
    expected_state: str,
) -> None:
    assert apply_disposition("awaiting_human_review", disposition) == expected_state


def test_disposition_is_rejected_outside_human_review() -> None:
    with pytest.raises(ValueError, match="awaiting_human_review"):
        apply_disposition("completed", "continue")


def test_unknown_disposition_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported disposition"):
        apply_disposition("awaiting_human_review", "approve_claim")


def test_request_info_requires_explicit_resume() -> None:
    assert resume_for_information("needs_more_information") == "awaiting_human_review"


def test_non_request_info_state_cannot_resume() -> None:
    with pytest.raises(ValueError, match="needs_more_information"):
        resume_for_information("completed")


def test_action_fingerprint_ignores_mapping_key_order() -> None:
    assert action_fingerprint({"actor_id": "reviewer", "reason": "continue"}) == (
        action_fingerprint({"reason": "continue", "actor_id": "reviewer"})
    )


def test_action_fingerprint_changes_when_action_changes() -> None:
    first = action_fingerprint({"disposition": "continue", "reason": "reviewed"})
    second = action_fingerprint({"disposition": "stop", "reason": "reviewed"})
    assert first != second


def test_idempotent_replay_returns_original_response() -> None:
    action = {"disposition": "continue", "reason": "reviewed"}
    response = {"state": "completed", "version": 2}
    assert resolve_idempotent_replay(action_fingerprint(action), response, action) == response


def test_idempotent_replay_rejects_conflicting_payload() -> None:
    response = {"state": "completed", "version": 2}
    with pytest.raises(ValueError, match="different action"):
        resolve_idempotent_replay(
            action_fingerprint({"disposition": "continue"}),
            response,
            {"disposition": "stop"},
        )