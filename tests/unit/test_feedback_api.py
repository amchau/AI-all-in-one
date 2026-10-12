"""Test strict feedback boundaries and sanitized HTTP behavior."""

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "ai-api"))


@pytest.fixture
def api_module():
    return importlib.import_module("feedback_api")


@pytest.fixture
def client_store(api_module):
    store = MagicMock()
    store.create.return_value = api_module.FeedbackReceipt(
        feedback_id=uuid4(), created_at=datetime.now(timezone.utc)
    )
    app = FastAPI()
    app.include_router(api_module.create_feedback_router(store))
    return TestClient(app), store


@pytest.mark.parametrize("rating", ["useful", "needs_review", "unable_to_assess"])
def test_create_returns_receipt_only(client_store, rating):
    client, store = client_store
    response = client.post("/v1/feedback", json={
        "rating": rating, "note": "PRIVATE_NOTE", "reason_tags": ["grounding"],
        "workflow_id": str(uuid4()),
    })
    assert response.status_code == 201
    assert set(response.json()) == {"feedback_id", "created_at"}
    assert "PRIVATE_NOTE" not in response.text
    assert store.create.call_args.kwargs["rating"] == rating


@pytest.mark.parametrize("payload", [
    {}, None, [], "PRIVATE_NOTE",
    {"rating": None}, {"rating": 1}, {"rating": "invalid"},
    {"rating": "useful", "reviewer_identity": "PRIVATE_NOTE"},
    {"rating": "useful", "note": "x" * 501},
    {"rating": "useful", "note": 10},
    {"rating": "useful", "reason_tags": ["grounding", "grounding"]},
    {"rating": "useful", "reason_tags": ["invalid"]},
    {"rating": "useful", "reason_tags": ["other"] * 6},
    {"rating": "useful", "reason_tags": "safety"},
    {"rating": "useful", "workflow_id": "PRIVATE_REFERENCE"},
    {"rating": "useful", "trace_id": "0" * 32},
    {"rating": "useful", "trace_id": "g" * 32},
    {"rating": "useful", "trace_id": "a" * 31},
    {"rating": "useful", "trace_id": 1},
    {"rating": "useful", "trace_id": "a" * 32, "workflow_id": str(uuid4())},
])
def test_invalid_payload_is_generic_without_input_echo(client_store, payload):
    client, store = client_store
    response = client.post("/v1/feedback", json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid feedback request"}
    store.create.assert_not_called()


def test_malformed_json_is_generic(client_store):
    client, store = client_store
    response = client.post(
        "/v1/feedback", content='{"note":"PRIVATE_NOTE",',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid feedback request"}
    store.create.assert_not_called()


def test_boundary_is_frozen_strict_and_converts_json_uuid(api_module):
    workflow_id = uuid4()
    request = api_module.FeedbackRequest.model_validate_json(
        '{"rating":"useful","workflow_id":"' + str(workflow_id) + '"}'
    )
    assert request.workflow_id == workflow_id
    with pytest.raises(ValidationError):
        request.rating = "needs_review"
    with pytest.raises(ValidationError):
        api_module.FeedbackRequest.model_validate({
            "rating": "useful", "workflow_id": str(workflow_id)
        })


def test_all_bounds_and_trace_normalization(client_store):
    client, store = client_store
    response = client.post("/v1/feedback", json={
        "rating": "useful", "note": "'\u2603" * 250,
        "reason_tags": ["grounding", "completeness", "relevance", "safety", "other"],
        "trace_id": "A" * 32,
    })
    assert response.status_code == 201
    assert store.create.call_args.kwargs["trace_id"] == "a" * 32


@pytest.mark.parametrize("operation,method,path", [
    ("create", "post", "/v1/feedback"),
])
def test_unexpected_store_errors_are_private(client_store, caplog, operation, method, path):
    client, store = client_store
    getattr(store, operation).side_effect = RuntimeError("PRIVATE_NOTE PRIVATE_REFERENCE")
    kwargs = {"json": {"rating": "useful"}}
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 503
    assert response.json() == {"detail": "Feedback service unavailable"}
    assert "PRIVATE_NOTE" not in caplog.text + response.text
    assert "PRIVATE_REFERENCE" not in caplog.text + response.text


@pytest.mark.parametrize("operation,method,path", [
    ("create", "post", "/v1/feedback"),
])
def test_store_failure_result_is_generic(client_store, operation, method, path):
    client, store = client_store
    getattr(store, operation).return_value = None
    kwargs = {"json": {"rating": "useful"}}
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 503


def test_feedback_aggregate_endpoint_is_not_exposed_without_approved_threshold(client_store):
    client, store = client_store
    response = client.get("/v1/feedback/summary")
    assert response.status_code == 404
    store.create.assert_not_called()