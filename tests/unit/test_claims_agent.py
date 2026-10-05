from __future__ import annotations

import json
from pathlib import Path
import sys

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agents.claims.models import AgentInvestigationInput
from agents.claims.runner import AgentDependencyError, AgentOutputError, ClaimsAgent


def tool_call(name: str, arguments: dict[str, str], *, call_id: str = "call-1") -> dict[str, object]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def model_tool_response(*calls: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "tool_calls": list(calls)}}]},
    )


def model_final_response(*, source_id: str = "claim:CL-123") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "status": "answered",
                                "summary": "The claim is under review.",
                                "summary_source_ids": [source_id],
                                "findings": [
                                    {"text": "The reported event is water damage.", "source_ids": [source_id]}
                                ],
                                "unresolved_questions": [],
                            }
                        ),
                    }
                }
            ]
        },
    )


def claim_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "claim_id": "CL-123",
            "policy_id": "HOME-002",
            "customer_id": "CUST-123",
            "loss_date": "2025-03-01",
            "reported_event": "Water entered the ground floor.",
            "status": "under_review",
        },
    )


def make_agent(handler, *, max_tool_calls: int = 6, rag_provider=None) -> ClaimsAgent:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ClaimsAgent(
        http_client=client,
        claims_service_url="http://claims-service:8080",
        litellm_url="http://litellm:4000",
        litellm_master_key="test-key",
        model="test-model",
        rag_evidence_provider=rag_provider,
        max_tool_calls=max_tool_calls,
    )


def test_agent_runs_allowlisted_tool_and_validates_source_refs() -> None:
    model_turn = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal model_turn
        if request.url.path == "/chat/completions":
            model_turn += 1
            if model_turn == 1:
                payload = json.loads(request.content)
                tools = payload["tools"]
                assert {tool["function"]["name"] for tool in tools} == {
                    "get_claim",
                    "get_policy",
                    "get_customer",
                    "list_payments",
                    "list_fraud_signals",
                }
                return model_tool_response(tool_call("get_claim", {"claim_id": "CL-123"}))
            return model_final_response()
        assert request.url.path == "/v1/claims/CL-123"
        return claim_response()

    agent = make_agent(handle)
    result = agent.investigate(
        AgentInvestigationInput(claim_id="CL-123", narrative="Water entered the home overnight.")
    )

    assert result.claim_id == "CL-123"
    assert result.status == "answered"
    assert result.tool_calls == 1
    assert result.summary_source_ids == ["claim:CL-123"]
    assert result.sources[0].facts["policy_id"] == "HOME-002"


@pytest.mark.parametrize("name", ["run_sql", "approve_claim", "issue_payment", "update_claim"])
def test_agent_rejects_unknown_tool_before_dispatch(name: str) -> None:
    business_calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host != "litellm":
            business_calls.append(request.url.path)
            return claim_response()
        call = tool_call(name, {"query": "select *"})
        call["function"]["arguments"] = "not-json"
        return model_tool_response(call)

    agent = make_agent(handle)
    with pytest.raises(AgentOutputError, match="unsupported tool"):
        agent.investigate(
            AgentInvestigationInput(claim_id="CL-123", narrative="Water entered the home overnight.")
        )
    assert business_calls == []


def test_agent_rejects_policy_not_bound_to_claim() -> None:
    model_turn = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal model_turn
        if request.url.path == "/chat/completions":
            model_turn += 1
            if model_turn == 1:
                return model_tool_response(tool_call("get_claim", {"claim_id": "CL-123"}))
            return model_tool_response(tool_call("get_policy", {"policy_id": "HOME-OTHER"}))
        return claim_response()

    agent = make_agent(handle)
    with pytest.raises(AgentOutputError, match="outside the claim"):
        agent.investigate(
            AgentInvestigationInput(claim_id="CL-123", narrative="Water entered the home overnight.")
        )


def test_agent_rejects_model_source_id_not_returned_by_tool() -> None:
    model_turn = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal model_turn
        if request.url.path == "/chat/completions":
            model_turn += 1
            if model_turn == 1:
                return model_tool_response(tool_call("get_claim", {"claim_id": "CL-123"}))
            return model_final_response(source_id="claim:MADE-UP")
        return claim_response()

    agent = make_agent(handle)
    with pytest.raises(AgentOutputError, match="unknown source"):
        agent.investigate(
            AgentInvestigationInput(claim_id="CL-123", narrative="Water entered the home overnight.")
        )


def test_agent_enforces_configured_tool_call_budget() -> None:
    model_turn = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal model_turn
        if request.url.path == "/chat/completions":
            model_turn += 1
            return model_tool_response(tool_call("get_claim", {"claim_id": "CL-123"}, call_id=f"call-{model_turn}"))
        return claim_response()

    agent = make_agent(handle, max_tool_calls=1)
    with pytest.raises(AgentOutputError, match="tool-call budget"):
        agent.investigate(
            AgentInvestigationInput(claim_id="CL-123", narrative="Water entered the home overnight.")
        )


def test_agent_tool_definitions_omit_rag_tool_when_not_configured() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert "get_policy_evidence" not in {
            tool["function"]["name"] for tool in payload["tools"]
        }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "status": "insufficient_evidence",
                                    "summary": "",
                                    "summary_source_ids": [],
                                    "findings": [],
                                    "unresolved_questions": ["Which claim facts should be reviewed next?"],
                                }
                            )
                        }
                    }
                ]
            },
        )

    agent = make_agent(handle)
    result = agent.investigate(
        AgentInvestigationInput(claim_id="CL-123", narrative="Water entered the home overnight.")
    )
    assert result.status == "insufficient_evidence"


def test_agent_rejects_configuration_above_fixed_tool_bound() -> None:
    with pytest.raises(ValueError, match="approved safety bound"):
        make_agent(lambda _request: model_final_response(), max_tool_calls=7)


def test_agent_does_not_retry_litellm_dependency_failure() -> None:
    requests = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(503)

    agent = make_agent(handle)
    with pytest.raises(AgentDependencyError, match="LiteLLM agent request failed"):
        agent.investigate(
            AgentInvestigationInput(claim_id="CL-123", narrative="Water entered the home overnight.")
        )
    assert requests == 1


def test_agent_rejects_malformed_successful_final_response() -> None:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    agent = make_agent(handle)
    with pytest.raises(AgentOutputError, match="final response is invalid"):
        agent.investigate(
            AgentInvestigationInput(claim_id="CL-123", narrative="Water entered the home overnight.")
        )
