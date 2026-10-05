from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict


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


app = FastAPI(title="Synthetic Claims Service", version="0.1.0")

_CLAIMS = {
    "CL-123": ClaimRecord(
        claim_id="CL-123",
        policy_id="HOME-002",
        customer_id="CUST-123",
        loss_date=date(2025, 3, 1),
        reported_event="Water entered the ground floor after a reported pipe failure.",
        status="under_review",
    )
}
_POLICIES = {
    "HOME-002": PolicyRecord(
        policy_id="HOME-002",
        product="home",
        status="active",
        effective_date=date(2024, 1, 1),
        declared_limit="GBP 250000",
    )
}
_CUSTOMERS = {
    "CUST-123": CustomerRecord(
        customer_id="CUST-123",
        display_name="Synthetic Customer 123",
        contact_status="verified",
    )
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
    ]
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
