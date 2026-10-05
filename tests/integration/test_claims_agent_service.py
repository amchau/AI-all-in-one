from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import httpx
from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agents.claims.models import AgentInvestigationInput
from agents.claims.runner import ClaimsAgent

SERVICE_PATH = ROOT / "apps" / "claims-service" / "main.py"
SPEC = importlib.util.spec_from_file_location("claims_service_integration", SERVICE_PATH)
assert SPEC is not None and SPEC.loader is not None
SERVICE_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVICE_MODULE)
SERVICE_CLIENT = TestClient(SERVICE_MODULE.app)


def model_tool_call(name: str, arguments: dict[str, str]) -> httpx.Response:
    call = {
        "id": "call-1",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "tool_calls": [call]}}]},
    )


def test_claims_agent_consumes_typed_claims_service_records() -> None:
    model_turn = 0

    def route(request: httpx.Request) -> httpx.Response:
        nonlocal model_turn
        if request.url.host == "litellm":
            model_turn += 1
            if model_turn == 1:
                return model_tool_call("get_claim", {"claim_id": "CL-123"})
            if model_turn == 2:
                return model_tool_call("list_fraud_signals", {"claim_id": "CL-123"})
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "status": "answered",
                                        "summary": "The claim is under review.",
                                        "summary_source_ids": ["claim:CL-123"],
                                        "findings": [
                                            {
                                                "text": "One date-inconsistency signal is unreviewed.",
                                                "source_ids": ["fraud_signal:FRD-001"],
                                            }
                                        ],
                                        "unresolved_questions": [],
                                    }
                                )
                            }
                        }
                    ]
                },
            )
        service_response = SERVICE_CLIENT.request(
            request.method,
            f"{request.url.path}?{request.url.query.decode()}" if request.url.query else request.url.path,
        )
        return httpx.Response(
            service_response.status_code,
            json=service_response.json(),
        )

    with httpx.Client(transport=httpx.MockTransport(route)) as client:
        agent = ClaimsAgent(
            http_client=client,
            claims_service_url="http://claims-service:8080",
            litellm_url="http://litellm:4000",
            litellm_master_key="test-key",
            model="test-model",
        )
        result = agent.investigate(
            AgentInvestigationInput(
                claim_id="CL-123",
                narrative="Water entered the ground floor after a pipe failure.",
            )
        )

    assert result.status == "answered"
    assert result.tool_calls == 2
    assert {source.source_id for source in result.sources} == {
        "claim:CL-123",
        "fraud_signal:FRD-001",
    }
    assert result.findings[0].source_ids == ["fraud_signal:FRD-001"]


def _model_final(source_id: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "status": "answered",
                                "summary": "The requested record is available for handler review.",
                                "summary_source_ids": [source_id],
                                "findings": [
                                    {
                                        "text": "The synthetic record was returned.",
                                        "source_ids": [source_id],
                                    }
                                ],
                                "unresolved_questions": [],
                            }
                        )
                    }
                }
            ]
        },
    )


@pytest.mark.parametrize(
    ("tool_name", "arguments", "source_id", "source_type"),
    [
        ("get_policy", {"policy_id": "HOME-002"}, "policy:HOME-002", "policy"),
        ("get_customer", {"customer_id": "CUST-123"}, "customer:CUST-123", "customer"),
        ("list_payments", {"claim_id": "CL-123"}, "payment:PAY-001", "payment"),
        ("list_fraud_signals", {"claim_id": "CL-123"}, "fraud_signal:FRD-001", "fraud_signal"),
    ],
)
def test_agent_integration_scenarios_cover_each_read_only_domain_tool(
    tool_name: str,
    arguments: dict[str, str],
    source_id: str,
    source_type: str,
) -> None:
    model_turn = 0

    def route(request: httpx.Request) -> httpx.Response:
        nonlocal model_turn
        if request.url.host == "litellm":
            model_turn += 1
            if model_turn == 1:
                return model_tool_call("get_claim", {"claim_id": "CL-123"})
            if model_turn == 2:
                return model_tool_call(tool_name, arguments)
            return _model_final(source_id)
        path = request.url.path
        if request.url.query:
            path = f"{path}?{request.url.query.decode()}"
        response = SERVICE_CLIENT.request(request.method, path)
        return httpx.Response(response.status_code, json=response.json())

    with httpx.Client(transport=httpx.MockTransport(route)) as client:
        agent = ClaimsAgent(
            http_client=client,
            claims_service_url="http://claims-service:8080",
            litellm_url="http://litellm:4000",
            litellm_master_key="test-key",
            model="test-model",
        )
        result = agent.investigate(
            AgentInvestigationInput(
                claim_id="CL-123",
                narrative="Retrieve the synthetic record for handler review.",
            )
        )

    assert result.status == "answered"
    assert result.tool_calls == 2
    assert source_id in {source.source_id for source in result.sources}
    assert source_type in {source.source_type for source in result.sources}
    assert set(result.findings[0].source_ids) <= {source.source_id for source in result.sources}
