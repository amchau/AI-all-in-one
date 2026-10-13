import { z } from "zod";

import { investigationRequestSchema } from "./validation";
import type { ClaimsInvestigationRequest } from "./validation";

const sourceSchema = z.object({
  source_id: z.string(),
  source_type: z.enum(["claim", "policy", "customer", "payment", "fraud_signal", "policy_evidence"]),
  record_id: z.string(),
  label: z.string(),
  facts: z.record(z.string(), z.unknown()),
});

const investigationResponseSchema = z.object({
  claim_id: z.string(),
  status: z.enum(["answered", "insufficient_evidence"]),
  summary: z.string(),
  summary_source_ids: z.array(z.string()),
  findings: z.array(
    z.object({
      text: z.string(),
      source_ids: z.array(z.string()),
    }),
  ),
  unresolved_questions: z.array(z.string()),
  sources: z.array(sourceSchema),
  model: z.string(),
  tool_calls: z.number().int().nonnegative().max(6),
  latency_ms: z.number().int().nonnegative(),
  trace_id: z.string().regex(/^[0-9a-f]{32}$/).nullable(),
});

const riskAssessmentSchema = z.object({
  status: z.enum(["available", "unavailable"]),
  priority_band: z.enum(["routine_review", "priority_review"]).nullable(),
  handler_triage_required: z.boolean().nullable(),
  triage_reason: z.enum(["assessment_incomplete", "near_decision_threshold"]).nullable(),
  model_version: z.string().nullable(),
  unavailable_reason: z
    .enum(["feature_service_unavailable", "risk_service_unavailable", "invalid_response"])
    .nullable(),
});

const hybridInvestigationResponseSchema = z.object({
  claim_id: z.string(),
  policy_id: z.string(),
  loss_date: z.iso.date(),
  guidance_as_of: z.iso.date(),
  policy_evidence_status: z.enum(["retrieved", "insufficient_evidence", "unavailable"]),
  policy_evidence_unavailable_reason: z
    .enum(["retrieval_dependency_failed", "source_selection_failed"])
    .nullable(),
  investigation: investigationResponseSchema,
  risk_assessment: riskAssessmentSchema,
  latency_ms: z.number().int().nonnegative(),
  trace_id: z.string().regex(/^[0-9a-f]{32}$/).nullable(),
});

export type ClaimsInvestigationResponse = z.infer<typeof hybridInvestigationResponseSchema>;
export type InvestigationSource = z.infer<typeof sourceSchema>;

export class InvestigationApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvestigationApiError";
  }
}

export async function createInvestigation(
  input: ClaimsInvestigationRequest,
): Promise<ClaimsInvestigationResponse> {
  const request = investigationRequestSchema.parse(input);
  const body = {
    ...request,
    ...(request.guidance_as_of ? {} : { guidance_as_of: undefined }),
  };
  let response: Response;
  try {
    response = await fetch("/api/v1/claims/hybrid-investigations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new InvestigationApiError("The investigation service could not be reached.");
  }

  if (!response.ok) {
    const message = response.status === 404
      ? "The claim was not found in the synthetic claims service."
      : response.status === 422
        ? "Some claim details are invalid. Review the fields and try again."
        : "The investigation service is unavailable. Try again later.";
    throw new InvestigationApiError(message);
  }

  try {
    const payload: unknown = await response.json();
    return hybridInvestigationResponseSchema.parse(payload);
  } catch {
    throw new InvestigationApiError("The investigation service returned an invalid response.");
  }
}