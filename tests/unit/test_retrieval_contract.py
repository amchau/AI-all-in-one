from datetime import date

import pytest
from pydantic import ValidationError

from rag.retrieval.models import RagQueryInput


def test_query_defaults_to_dense_and_guidance_date_can_be_omitted() -> None:
    request = RagQueryInput(
        question="Is flood damage covered?",
        policy_id="HOME-002",
        loss_date=date(2025, 3, 1),
    )

    assert request.mode == "dense"
    assert request.guidance_as_of is None
    assert request.top_k == 5


@pytest.mark.parametrize(
    "overrides",
    [
        {"question": "   "},
        {"question": "tiny"},
        {"policy_id": ""},
        {"policy_id": "HOME 002"},
        {"top_k": 0},
        {"top_k": 21},
        {"mode": "hybrid_sparse"},
    ],
)
def test_query_rejects_invalid_or_out_of_scope_fields(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "question": "Is flood damage covered?",
        "policy_id": "HOME-002",
        "loss_date": date(2025, 3, 1),
    }
    values.update(overrides)

    with pytest.raises(ValidationError):
        RagQueryInput.model_validate(values)


@pytest.mark.parametrize("mode", ["dense", "hybrid", "hybrid_rerank"])
def test_query_accepts_supported_retrieval_modes(mode: str) -> None:
    request = RagQueryInput(
        question="Is flood damage covered?",
        policy_id="HOME-002",
        loss_date=date(2025, 3, 1),
        mode=mode,
    )

    assert request.mode == mode