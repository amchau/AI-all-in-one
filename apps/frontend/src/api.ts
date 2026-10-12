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

const workflowResultSchema = z.object({
  claim_id: z.string(),
  policy_id: z.string(),
  loss_date: z.string(),
  guidance_as_of: z.string(),
  policy_evidence_status: z.enum(["retrieved", "insufficient_evidence", "unavailable"]),
  policy_evidence_unavailable_reason: z
    .enum(["retrieval_dependency_failed", "source_selection_failed"])
    .nullable(),
  investigation: z.object({
    claim_id: z.string(),
    status: z.enum(["answered", "insufficient_evidence"]),
    summary: z.string(),
    summary_source_ids: z.array(z.string()),
    findings: z.array(
      z.object({ text: z.string(), source_ids: z.array(z.string()) }),
    ),
    unresolved_questions: z.array(z.string()),
    sources: z.array(
      z.object({
        source_id: z.string(),
        source_type: sourceSchema.shape.source_type,
      }),
    ),
    model: z.string(),
    tool_calls: z.number().int().nonnegative(),
    latency_ms: z.number().int().nonnegative(),
    trace_id: z.string().regex(/^[0-9a-f]{32}$/).nullable(),
  }),
  risk_assessment: riskAssessmentSchema,
  latency_ms: z.number().int().nonnegative(),
  trace_id: z.string().regex(/^[0-9a-f]{32}$/).nullable(),
});

const workflowStateSchema = z.enum([
  "created",
  "investigating",
  "awaiting_human_review",
  "needs_more_information",
  "completed",
  "failed",
  "cancelled",
]);

const workflowStatusSchema = z.object({
  workflow_id: z.string().uuid(),
  claim_id: z.string(),
  state: workflowStateSchema,
  version: z.number().int().nonnegative(),
  created_at: z.string(),
  updated_at: z.string(),
  error_code: z.enum([
    "stage6_dependency_failed",
    "stage6_response_invalid",
    "worker_interrupted",
  ]).nullable(),
  result: workflowResultSchema.nullable(),
  history: z.array(
    z.object({
      event_id: z.number().int().positive(),
      from_state: workflowStateSchema.nullable(),
      state: workflowStateSchema,
      action: z.string(),
      disposition: z.enum(["continue", "request_info", "stop"]).nullable(),
      actor_id: z.string(),
      reason: z.string(),
      trace_id: z.string().regex(/^[0-9a-f]{32}$/).nullable(),
      created_at: z.string(),
    }),
  ),
});

export type ClaimsInvestigationResponse = z.infer<typeof hybridInvestigationResponseSchema>;
export type InvestigationSource = z.infer<typeof sourceSchema>;
export type ClaimsWorkflowStatus = z.infer<typeof workflowStatusSchema>;
export type ClaimsWorkflowDisposition = "continue" | "request_info" | "stop";
export type ReviewerFeedbackRating = "useful" | "needs_review" | "unable_to_assess";
export type ReviewerFeedbackReason = "grounding" | "completeness" | "relevance" | "safety" | "other";

export interface ReviewerFeedbackInput {
  rating: ReviewerFeedbackRating;
  reason_tags?: ReviewerFeedbackReason[];
  note?: string;
  workflow_id?: string;
  trace_id?: string;
}

export interface ReviewerFeedbackReceipt {
  feedback_id: string;
  created_at: string;
}

const feedbackReceiptSchema = z.object({
  feedback_id: z.uuid(),
  created_at: z.iso.datetime(),
});

const feedbackInputSchema = z.object({
  rating: z.enum(["useful", "needs_review", "unable_to_assess"]),
  reason_tags: z.array(z.enum(["grounding", "completeness", "relevance", "safety", "other"]))
    .max(5).optional(),
  note: z.string().max(500).optional(),
  workflow_id: z.uuid().optional(),
  trace_id: z.string().regex(/^(?!0{32})[0-9a-fA-F]{32}$/).optional(),
}).refine((input) => !(input.workflow_id && input.trace_id));

export interface ClaimsWorkflowAction {
  expected_version: number;
  actor_id: string;
  reason: string;
  idempotency_key: string;
}

export interface ClaimsWorkflowResumeAction extends ClaimsWorkflowAction {
  updated_narrative: string;
}

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
      : response.status === 429
        ? "The language model is rate limited. Wait briefly, then try again."
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

async function sendWorkflowRequest(
  url: string,
  init: RequestInit,
  expectedStatus: number,
): Promise<ClaimsWorkflowStatus> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new InvestigationApiError("The workflow service could not be reached.");
  }
  if (!response.ok || response.status !== expectedStatus) {
    const message = response.status === 404
      ? "The workflow was not found."
      : response.status === 409
        ? "The workflow changed. Reload it before submitting this action."
        : response.status === 422
          ? "Some workflow details are invalid. Review the fields and try again."
          : "The workflow service is unavailable. Try again later.";
    throw new InvestigationApiError(message);
  }
  try {
    const payload: unknown = await response.json();
    return workflowStatusSchema.parse(payload);
  } catch {
    throw new InvestigationApiError("The workflow service returned an invalid response.");
  }
}

export function createClaimsWorkflow(
  input: ClaimsInvestigationRequest,
): Promise<ClaimsWorkflowStatus> {
  const request = investigationRequestSchema.parse(input);
  return sendWorkflowRequest(
    "/api/v1/claims/workflows",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    202,
  );
}

export function getClaimsWorkflow(workflowId: string): Promise<ClaimsWorkflowStatus> {
  return sendWorkflowRequest(`/api/v1/claims/workflows/${workflowId}`, { method: "GET" }, 200);
}

export function submitClaimsWorkflowDisposition(
  workflowId: string,
  action: ClaimsWorkflowAction & { disposition: ClaimsWorkflowDisposition },
): Promise<ClaimsWorkflowStatus> {
  const { idempotency_key: idempotencyKey, ...body } = action;
  return sendWorkflowRequest(
    `/api/v1/claims/workflows/${workflowId}/dispositions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(body),
    },
    200,
  );
}

export function resumeClaimsWorkflow(
  workflowId: string,
  action: ClaimsWorkflowResumeAction,
): Promise<ClaimsWorkflowStatus> {
  const { idempotency_key: idempotencyKey, ...body } = action;
  return sendWorkflowRequest(
    `/api/v1/claims/workflows/${workflowId}/resume`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(body),
    },
    200,
  );
}

export async function submitReviewerFeedback(
  input: ReviewerFeedbackInput,
): Promise<ReviewerFeedbackReceipt> {
  const request = feedbackInputSchema.parse(input);
  let response: Response;
  try {
    response = await fetch("/api/v1/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
  } catch {
    throw new InvestigationApiError("Feedback could not be submitted. Try again later.");
  }
  if (!response.ok || response.status !== 201) {
    throw new InvestigationApiError("Feedback could not be submitted. Try again later.");
  }
  try {
    return feedbackReceiptSchema.parse(await response.json());
  } catch {
    throw new InvestigationApiError("Feedback could not be submitted. Try again later.");
  }
}