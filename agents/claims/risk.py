"""Call the internal Stage 5 service without exposing risk inputs to the agent."""

from __future__ import annotations

import logging
import time
from typing import Literal
from urllib.parse import quote

import httpx
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agents.claims.models import HybridRiskAssessment
from ml.claims_risk.dataset import ClaimRiskFeatures

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class RiskFeatureLookup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    claim_id: str = Field(min_length=1, max_length=80)
    assessment_complete: bool
    features: ClaimRiskFeatures


class RiskServiceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    priority_band: Literal["routine_review", "priority_review"] | None
    handler_triage_required: bool
    triage_reason: Literal["assessment_incomplete", "near_decision_threshold"] | None
    model_version: str = Field(min_length=1, max_length=80)
    trace_id: str | None = None

    @model_validator(mode="after")
    def validate_assessment_state(self) -> RiskServiceResponse:
        if self.handler_triage_required:
            if self.priority_band is not None or self.triage_reason is None:
                raise ValueError("triage result is inconsistent")
        elif self.priority_band is None or self.triage_reason is not None:
            raise ValueError("scored result is inconsistent")
        return self


def assess_claim_risk(
    client: httpx.Client,
    *,
    claim_id: str,
    claims_service_url: str,
    risk_service_url: str,
) -> HybridRiskAssessment:
    """Return a separate advisory result; service failures become explicit partial state."""
    started = time.perf_counter()
    unavailable_reason = "feature_service_unavailable"
    with tracer.start_as_current_span("claims.risk_advisory") as span:
        try:
            encoded_claim_id = quote(claim_id, safe="")
            feature_response = client.get(
                f"{claims_service_url.rstrip('/')}/v1/claims/{encoded_claim_id}/risk-features",
                timeout=5.0,
            )
            feature_response.raise_for_status()
            lookup = RiskFeatureLookup.model_validate(feature_response.json())
            if lookup.claim_id != claim_id:
                raise ValueError("risk feature claim identity mismatch")

            unavailable_reason = "risk_service_unavailable"
            assessment_response = client.post(
                f"{risk_service_url.rstrip('/')}/v1/claims/risk-assessments",
                json={
                    "assessment_complete": lookup.assessment_complete,
                    "features": lookup.features.model_dump(mode="json"),
                },
                timeout=10.0,
            )
            assessment_response.raise_for_status()
            assessment = RiskServiceResponse.model_validate(assessment_response.json())
            result = HybridRiskAssessment(
                status="available",
                priority_band=assessment.priority_band,
                handler_triage_required=assessment.handler_triage_required,
                triage_reason=assessment.triage_reason,
                model_version=assessment.model_version,
                unavailable_reason=None,
            )
            span.set_attribute("ml.outcome", "available")
            span.set_attribute("ml.model_version", assessment.model_version)
            return result
        except httpx.HTTPError:
            result = HybridRiskAssessment(
                status="unavailable",
                priority_band=None,
                handler_triage_required=None,
                triage_reason=None,
                model_version=None,
                unavailable_reason=unavailable_reason,
            )
            span.set_attribute("ml.outcome", "unavailable")
            span.set_attribute("ml.unavailable_reason", result.unavailable_reason or "unknown")
            logger.warning("claims risk advisory unavailable: %s", result.unavailable_reason)
            return result
        except (ValueError, ValidationError):
            result = HybridRiskAssessment(
                status="unavailable",
                priority_band=None,
                handler_triage_required=None,
                triage_reason=None,
                model_version=None,
                unavailable_reason="invalid_response",
            )
            span.set_attribute("ml.outcome", "unavailable")
            span.set_attribute("ml.unavailable_reason", result.unavailable_reason or "unknown")
            logger.warning("claims risk advisory unavailable: %s", result.unavailable_reason)
            return result
        finally:
            span.set_attribute("ml.latency_ms", round((time.perf_counter() - started) * 1000))