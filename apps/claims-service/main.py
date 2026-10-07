"""Serve read-only synthetic claims records and their bounded risk features."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

from ml.claims_risk.dataset import ClaimRiskFeatures


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClaimRecord(Contract):
    claim_id: str
    policy_id: str
    customer_id: str
    loss_date: date
    reported_event: str
    status: Literal["open", "under_review"]


class PolicyRecord(Contract):
    policy_id: str
    product: str
    status: Literal["active", "expired"]
    effective_date: date
    declared_limit: str


class CustomerRecord(Contract):
    customer_id: str
    display_name: str
    contact_status: Literal["verified", "unverified"]


class PaymentRecord(Contract):
    payment_id: str
    claim_id: str
    payment_type: Literal["repair_advance", "expense_reimbursement"]
    amount_gbp: int
    status: Literal["issued", "pending", "void"]


class FraudSignal(Contract):
    signal_id: str
    claim_id: str
    signal_type: Literal["duplicate_document", "date_inconsistency", "none"]
    description: str
    status: Literal["unreviewed", "reviewed"]


class RiskFeatureAssessment(Contract):
    claim_id: str
    assessment_complete: bool
    features: ClaimRiskFeatures


RiskFeatureAssessment.model_rebuild(
    _types_namespace={"ClaimRiskFeatures": ClaimRiskFeatures}
)


app = FastAPI(title="Synthetic Claims Service", version="0.1.0")

_CLAIMS = {
    "CL-123": ClaimRecord(
        claim_id="CL-123",
        policy_id="HOME-002",
        customer_id="CUST-123",
        loss_date=date(2025, 3, 1),
        reported_event="Water entered the ground floor after a reported pipe failure.",
        status="under_review",
    ),
    "CL-124": ClaimRecord(
        claim_id="CL-124",
        policy_id="COMM-001",
        customer_id="CUST-124",
        loss_date=date(2025, 4, 12),
        reported_event="A delivery vehicle was damaged in a loading-bay collision.",
        status="open",
    ),
}
_POLICIES = {
    "HOME-002": PolicyRecord(
        policy_id="HOME-002",
        product="home",
        status="active",
        effective_date=date(2024, 1, 1),
        declared_limit="GBP 250000",
    ),
    "COMM-001": PolicyRecord(
        policy_id="COMM-001",
        product="commercial",
        status="active",
        effective_date=date(2024, 6, 1),
        declared_limit="GBP 500000",
    ),
}
_CUSTOMERS = {
    "CUST-123": CustomerRecord(
        customer_id="CUST-123",
        display_name="Synthetic Customer 123",
        contact_status="verified",
    ),
    "CUST-124": CustomerRecord(
        customer_id="CUST-124",
        display_name="Synthetic Customer 124",
        contact_status="unverified",
    ),
}
_PAYMENTS = {
    "CL-123": [
        PaymentRecord(
            payment_id="PAY-001",
            claim_id="CL-123",
            payment_type="repair_advance",
            amount_gbp=500,
            status="pending",
        )
    ]
}
_FRAUD_SIGNALS = {
    "CL-123": [
        FraudSignal(
            signal_id="FRD-001",
            claim_id="CL-123",
            signal_type="date_inconsistency",
            description="Reported incident date differs from the first submitted document date.",
            status="unreviewed",
        )
    ],
    "CL-124": [
        FraudSignal(
            signal_id="FRD-002",
            claim_id="CL-124",
            signal_type="none",
            description="No review signal is recorded for this synthetic claim.",
            status="reviewed",
        )
    ],
}
_RISK_FEATURES = {
    "CL-123": ClaimRiskFeatures(
        duplicate_document_count=0,
        date_inconsistency_count=1,
        missing_required_evidence_count=1,
        prior_open_claim_count=0,
        estimate_limit_ratio=0.5,
    ),
    "CL-124": ClaimRiskFeatures(
        duplicate_document_count=0,
        date_inconsistency_count=0,
        missing_required_evidence_count=0,
        prior_open_claim_count=0,
        estimate_limit_ratio=0.25,
    ),
}


@app.get("/livez")
def livez() -> dict[str, bool]:
    return {"ok": True}


@app.get("/readyz")
def readyz() -> dict[str, bool]:
    return {"ok": True}


@app.get("/v1/claims/{claim_id}", response_model=ClaimRecord)
def get_claim(claim_id: str) -> ClaimRecord:
    record = _CLAIMS.get(claim_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return record


@app.get(
    "/v1/claims/{claim_id}/risk-features",
    response_model=RiskFeatureAssessment,
)
def get_claim_risk_features(claim_id: str) -> RiskFeatureAssessment:
    if claim_id not in _CLAIMS:
        raise HTTPException(status_code=404, detail="Claim not found")
    return RiskFeatureAssessment(
        claim_id=claim_id,
        assessment_complete=True,
        features=_RISK_FEATURES[claim_id],
    )


@app.get("/v1/policies/{policy_id}", response_model=PolicyRecord)
def get_policy(policy_id: str) -> PolicyRecord:
    record = _POLICIES.get(policy_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    return record


@app.get("/v1/customers/{customer_id}", response_model=CustomerRecord)
def get_customer(customer_id: str) -> CustomerRecord:
    record = _CUSTOMERS.get(customer_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return record


@app.get("/v1/payments", response_model=list[PaymentRecord])
def list_payments(claim_id: str) -> list[PaymentRecord]:
    if claim_id not in _CLAIMS:
        raise HTTPException(status_code=404, detail="Claim not found")
    return list(_PAYMENTS.get(claim_id, []))


@app.get("/v1/fraud-signals", response_model=list[FraudSignal])
def list_fraud_signals(claim_id: str) -> list[FraudSignal]:
    if claim_id not in _CLAIMS:
        raise HTTPException(status_code=404, detail="Claim not found")
    return list(_FRAUD_SIGNALS.get(claim_id, []))
