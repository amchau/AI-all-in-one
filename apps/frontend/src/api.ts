import { z } from "zod";

import { investigationRequestSchema } from "./validation";
import type { ClaimsInvestigationRequest } from "./validation";

const citationSchema = z.object({
  ref: z.string(),
  chunk_id: z.string(),
  doc_id: z.string(),
  title: z.string(),
  section: z.string().nullable(),
  clause: z.string().nullable(),
  page: z.number().int().positive(),
});

const investigationResponseSchema = z.object({
  claim_id: z.string(),
  policy_id: z.string(),
  loss_date: z.iso.date(),
  guidance_as_of: z.iso.date(),
  status: z.enum(["answered", "insufficient_evidence"]),
  summary: z.string(),
  summary_citations: z.array(citationSchema),
  findings: z.array(
    z.object({
      text: z.string(),
      citations: z.array(citationSchema),
    }),
  ),
  unresolved_questions: z.array(z.string()),
  evidence: z.array(
    z.object({
      chunk_id: z.string(),
      ref: z.string(),
      title: z.string(),
      section: z.string().nullable(),
      clause: z.string().nullable(),
      page: z.number().int().positive(),
      text: z.string(),
    }),
  ),
  model: z.string(),
  latency_ms: z.number().int().nonnegative(),
  trace_id: z.string().regex(/^[0-9a-f]{32}$/).nullable(),
});

export type ClaimsInvestigationResponse = z.infer<typeof investigationResponseSchema>;
export type InvestigationCitation = z.infer<typeof citationSchema>;

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
    response = await fetch("/api/v1/investigations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new InvestigationApiError("The investigation service could not be reached.");
  }

  if (!response.ok) {
    const message = response.status === 404
      ? "No applicable policy wording was found for that policy and loss date."
      : response.status === 409
        ? "The applicable policy wording is ambiguous. Review the policy dates."
        : response.status === 422
          ? "Some claim details are invalid. Review the fields and try again."
          : "The investigation service is unavailable. Try again later.";
    throw new InvestigationApiError(message);
  }

  try {
    const payload: unknown = await response.json();
    return investigationResponseSchema.parse(payload);
  } catch {
    throw new InvestigationApiError("The investigation service returned an invalid response.");
  }
}