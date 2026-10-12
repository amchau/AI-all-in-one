"""Test feedback persistence, retention, and privacy without a database."""

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "ai-api"))


@pytest.fixture
def feedback_module():
    return importlib.import_module("feedback_store")


@pytest.fixture
def database(feedback_module, monkeypatch):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(feedback_module.psycopg, "connect", connect)
    settings = feedback_module.FeedbackSettings(
        host="localhost", port=5432, db="synthetic", password="test-only"
    )
    store = feedback_module.FeedbackStore(settings)
    return store, cursor, connect


def test_write_deletes_expired_first_and_parameterizes_private_values(database):
    store, cursor, connect = database
    feedback_id = uuid4()
    created_at = datetime.now(timezone.utc)
    cursor.fetchone.return_value = {
        "feedback_id": feedback_id, "created_at": created_at
    }
    receipt = store.create(
        rating="useful", reason_tags=("grounding",), note="private ' note",
        workflow_id=None, trace_id="a" * 32,
    )
    calls = cursor.execute.call_args_list
    assert "DELETE FROM ai_feedback.feedback" in calls[0].args[0]
    assert "30 days" in calls[0].args[0]
    assert "INSERT INTO ai_feedback.feedback" in calls[1].args[0]
    assert "private ' note" not in calls[1].args[0]
    assert "private ' note" in calls[1].args[1]
    assert "a" * 32 in calls[1].args[1]
    assert receipt.feedback_id == feedback_id
    assert receipt.created_at == created_at
    assert set(receipt.model_dump()) == {"feedback_id", "created_at"}
    assert connect.call_args.kwargs["user"] == "claims_feedback"
    assert "test-only" not in repr(store.settings)


def test_explicit_cleanup_returns_deleted_count(database):
    store, cursor, _ = database
    cursor.rowcount = 3
    assert store.cleanup_expired() == 3
    assert "created_at <=" in cursor.execute.call_args.args[0]


@pytest.mark.parametrize("operation", ["create", "cleanup_expired"])
def test_database_errors_do_not_escape_with_private_text(database, operation):
    store, cursor, _ = database
    cursor.execute.side_effect = RuntimeError("PRIVATE_NOTE PRIVATE_REFERENCE")
    if operation == "create":
        result = store.create(rating="useful")
    else:
        result = getattr(store, operation)()
    assert result is None


def test_settings_require_explicit_credentials(feedback_module):
    with pytest.raises(Exception):
        feedback_module.FeedbackSettings()