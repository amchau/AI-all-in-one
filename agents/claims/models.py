from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentInvestigationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    claim_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    narrative: str = Field(min_length=5, max_length=1000)


class InvestigationSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=160)
    source_type: Literal["claim", "policy", "customer", "payment", "fraud_signal", "policy_evidence"]
    record_id: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=300)
    facts: dict[str, Any]


class InvestigationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1, max_length=1000)
    source_ids: list[str] = Field(min_length=1, max_length=8)


class AgentInvestigationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    status: Literal["answered", "insufficient_evidence"]
    summary: str = Field(max_length=2000)
    summary_source_ids: list[str] = Field(max_length=8)
    findings: list[InvestigationFinding] = Field(max_length=20)
    unresolved_questions: list[str] = Field(max_length=8)
    sources: list[InvestigationSource] = Field(max_length=40)
    model: str
    tool_calls: int = Field(ge=0, le=6)
    latency_ms: int = Field(ge=0)
    trace_id: str | None = None


class AgentFinalPayload(BaseModel):
    """Model-produced structured response, before server-side source resolution."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["answered", "insufficient_evidence"]
    summary: str = Field(max_length=2000)
    summary_source_ids: list[str] = Field(max_length=8)
    findings: list[InvestigationFinding] = Field(max_length=20)
    unresolved_questions: list[str] = Field(max_length=8)


class ToolSourceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[InvestigationSource] = Field(max_length=40)
    observation: str = Field(max_length=8000)