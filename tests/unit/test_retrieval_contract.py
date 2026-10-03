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
        {"mode": "hybrid"},
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