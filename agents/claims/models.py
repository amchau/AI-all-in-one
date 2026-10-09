"""Typed request and response contracts for claims investigations."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class HybridClaimsInvestigationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    claim_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    narrative: str = Field(min_length=5, max_length=1000)
    guidance_as_of: date | None = None


class HybridRiskAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: Literal["available", "unavailable"]
    priority_band: Literal["routine_review", "priority_review"] | None
    handler_triage_required: bool | None
    triage_reason: Literal[
        "assessment_incomplete",
        "near_decision_threshold",
    ] | None
    model_version: str | None = Field(default=None, max_length=80)
    unavailable_reason: Literal[
        "feature_service_unavailable",
        "risk_service_unavailable",
        "invalid_response",
    ] | None

    @model_validator(mode="after")
    def validate_assessment_state(self) -> HybridRiskAssessment:
        if self.status == "unavailable":
            if any(
                value is not None
                for value in (
                    self.priority_band,
                    self.handler_triage_required,
                    self.triage_reason,
                    self.model_version,
                )
            ) or self.unavailable_reason is None:
                raise ValueError("unavailable risk assessment is inconsistent")
        elif self.unavailable_reason is not None or self.model_version is None:
            raise ValueError("available risk assessment is inconsistent")
        elif self.handler_triage_required:
            if self.priority_band is not None or self.triage_reason is None:
                raise ValueError("triage risk assessment is inconsistent")
        elif self.priority_band is None or self.triage_reason is not None:
            raise ValueError("scored risk assessment is inconsistent")
        return self


class HybridClaimsInvestigationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    policy_id: str
    loss_date: date
    guidance_as_of: date
    policy_evidence_status: Literal[
        "retrieved",
        "insufficient_evidence",
        "unavailable",
    ]
    policy_evidence_unavailable_reason: Literal[
        "retrieval_dependency_failed",
        "source_selection_failed",
    ] | None
    investigation: AgentInvestigationOutput
    risk_assessment: HybridRiskAssessment
    latency_ms: int = Field(ge=0)
    trace_id: str | None = None

    @model_validator(mode="after")
    def validate_policy_evidence_state(self) -> HybridClaimsInvestigationOutput:
        if self.policy_evidence_status == "unavailable":
            if self.policy_evidence_unavailable_reason is None:
                raise ValueError("unavailable policy evidence requires a reason")
        elif self.policy_evidence_unavailable_reason is not None:
            raise ValueError("available policy evidence cannot have an unavailable reason")
        return self


class ClaimsWorkflowCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    claim_id: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    narrative: str = Field(min_length=5, max_length=1000)
    guidance_as_of: date | None = None


class ClaimsWorkflowDispositionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    disposition: Literal["continue", "request_info", "stop"]
    expected_version: int = Field(ge=1)
    actor_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    reason: str = Field(min_length=1, max_length=300)


class ClaimsWorkflowResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_version: int = Field(ge=1)
    actor_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    reason: str = Field(min_length=1, max_length=300)
    updated_narrative: str = Field(min_length=5, max_length=1000)


class ClaimsWorkflowEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: int
    from_state: str | None
    state: Literal[
        "created",
        "investigating",
        "awaiting_human_review",
        "needs_more_information",
        "completed",
        "failed",
        "cancelled",
    ]
    action: str
    disposition: Literal["continue", "request_info", "stop"] | None
    actor_id: str
    reason: str
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    created_at: datetime


class ClaimsWorkflowSourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    source_type: Literal[
        "claim",
        "policy",
        "customer",
        "payment",
        "fraud_signal",
        "policy_evidence",
    ]


class ClaimsWorkflowInvestigationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    status: Literal["answered", "insufficient_evidence"]
    summary: str
    summary_source_ids: list[str]
    findings: list[InvestigationFinding]
    unresolved_questions: list[str]
    sources: list[ClaimsWorkflowSourceReference]
    model: str
    tool_calls: int
    latency_ms: int
    trace_id: str | None


class ClaimsWorkflowResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    policy_id: str
    loss_date: date
    guidance_as_of: date
    policy_evidence_status: Literal[
        "retrieved",
        "insufficient_evidence",
        "unavailable",
    ]
    policy_evidence_unavailable_reason: Literal[
        "retrieval_dependency_failed",
        "source_selection_failed",
    ] | None
    investigation: ClaimsWorkflowInvestigationSummary
    risk_assessment: HybridRiskAssessment
    latency_ms: int
    trace_id: str | None


class ClaimsWorkflowStatusOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    claim_id: str
    state: Literal[
        "created",
        "investigating",
        "awaiting_human_review",
        "needs_more_information",
        "completed",
        "failed",
        "cancelled",
    ]
    version: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    error_code: Literal[
        "stage6_dependency_failed",
        "stage6_response_invalid",
        "worker_interrupted",
    ] | None
    result: ClaimsWorkflowResult | None
    history: list[ClaimsWorkflowEvent] = Field(default_factory=list)