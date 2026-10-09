import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createInvestigation,
  createClaimsWorkflow,
  getClaimsWorkflow,
  resumeClaimsWorkflow,
  submitClaimsWorkflowDisposition,
} from "./api";
import type { ClaimsInvestigationResponse } from "./api";

const request = {
  claim_id: "CL-123",
  narrative: "Flood water entered the ground floor overnight.",
};

const responseBody: ClaimsInvestigationResponse = {
  claim_id: "CL-123",
  policy_id: "HOME-002",
  loss_date: "2025-03-01",
  guidance_as_of: "2025-03-01",
  policy_evidence_status: "retrieved",
  policy_evidence_unavailable_reason: null,
  investigation: {
    claim_id: "CL-123",
    status: "answered",
    summary: "Flood cover is subject to limits.",
    summary_source_ids: [],
    findings: [],
    unresolved_questions: [],
    sources: [],
    model: "gpt-oss-20b",
    tool_calls: 2,
    latency_ms: 120,
    trace_id: "f8b71e2420453174714c9aed94a0d4ea",
  },
  risk_assessment: {
    status: "available",
    priority_band: "priority_review",
    handler_triage_required: false,
    triage_reason: null,
    model_version: "stage5-test",
    unavailable_reason: null,
  },
  latency_ms: 120,
  trace_id: "f8b71e2420453174714c9aed94a0d4ea",
};

const workflowBody = {
  workflow_id: "11111111-1111-4111-8111-111111111111",
  claim_id: "CL-123",
  state: "awaiting_human_review",
  version: 2,
  created_at: "2026-10-09T10:00:00Z",
  updated_at: "2026-10-09T10:00:05Z",
  error_code: null,
  result: null,
  history: [],
};

describe("investigation API client", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("posts validated claim input to the same-origin API and validates the response", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(responseBody), { status: 200 }),
    );

    await expect(createInvestigation(request)).resolves.toEqual(responseBody);
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/claims/hybrid-investigations",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          claim_id: request.claim_id,
          narrative: request.narrative,
        }),
      }),
    );
  });

  it("maps missing claims to a safe user-facing message", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("private details", { status: 404 }));

    await expect(createInvestigation(request)).rejects.toThrow(
      "The claim was not found in the synthetic claims service.",
    );
    await expect(createInvestigation(request)).rejects.not.toThrow("private details");
  });

  it("maps provider rate limits to a cooldown message without exposing details", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: "private provider detail" }), { status: 429 }),
    );

    await expect(createInvestigation(request)).rejects.toThrow(
      "The language model is rate limited. Wait briefly, then try again.",
    );
  });

  it("rejects malformed API responses without exposing payload details", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ private: "provider detail" }), { status: 200 }),
    );

    await expect(createInvestigation(request)).rejects.toThrow(
      "The investigation service returned an invalid response.",
    );
  });

  it("maps network failures and local validation errors", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("private network detail"));
    await expect(createInvestigation(request)).rejects.toThrow(
      "The investigation service could not be reached.",
    );

    await expect(
      createInvestigation({ ...request, narrative: "bad" }),
    ).rejects.toBeInstanceOf(Error);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe("claims workflow API client", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("creates and retrieves a persisted workflow", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response(JSON.stringify(workflowBody), { status: 202 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(workflowBody), { status: 200 }));

    await expect(
      createClaimsWorkflow(request),
    ).resolves.toEqual(workflowBody);
    await expect(getClaimsWorkflow(workflowBody.workflow_id)).resolves.toEqual(workflowBody);
    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "/api/v1/claims/workflows",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      `/api/v1/claims/workflows/${workflowBody.workflow_id}`,
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("sends idempotency keys for decisions and request-info resumes", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response(JSON.stringify(workflowBody), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(workflowBody), { status: 200 }));

    await submitClaimsWorkflowDisposition(workflowBody.workflow_id, {
      disposition: "continue",
      expected_version: 2,
      actor_id: "synthetic-handler-1",
      reason: "Continue workflow",
      idempotency_key: "decision-0123456789",
    });
    await resumeClaimsWorkflow(workflowBody.workflow_id, {
      expected_version: 2,
      actor_id: "synthetic-handler-1",
      reason: "Information received",
      updated_narrative: "The schedule confirms the extension.",
      idempotency_key: "resume-0123456789",
    });

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      `/api/v1/claims/workflows/${workflowBody.workflow_id}/dispositions`,
      expect.objectContaining({
        headers: expect.objectContaining({ "Idempotency-Key": "decision-0123456789" }),
      }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      `/api/v1/claims/workflows/${workflowBody.workflow_id}/resume`,
      expect.objectContaining({
        headers: expect.objectContaining({ "Idempotency-Key": "resume-0123456789" }),
      }),
    );
  });

  it("maps workflow 404, stale 409, validation 422, network, and malformed responses", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response("missing", { status: 404 }));
    await expect(getClaimsWorkflow(workflowBody.workflow_id)).rejects.toThrow("The workflow was not found.");

    vi.mocked(fetch).mockResolvedValueOnce(new Response("conflict", { status: 409 }));
    await expect(
      submitClaimsWorkflowDisposition(workflowBody.workflow_id, {
        disposition: "stop",
        expected_version: 2,
        actor_id: "synthetic-handler-1",
        reason: "Stop",
        idempotency_key: "decision-key-0001",
      }),
    ).rejects.toThrow("The workflow changed. Reload it before submitting this action.");

    vi.mocked(fetch).mockResolvedValueOnce(new Response("invalid", { status: 422 }));
    await expect(
      resumeClaimsWorkflow(workflowBody.workflow_id, {
        expected_version: 2,
        actor_id: "synthetic-handler-1",
        reason: "Resume",
        updated_narrative: "New information is available.",
        idempotency_key: "resume-key-0001",
      }),
    ).rejects.toThrow("Some workflow details are invalid.");

    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("private network detail"));
    await expect(getClaimsWorkflow(workflowBody.workflow_id)).rejects.toThrow(
      "The workflow service could not be reached.",
    );

    vi.mocked(fetch).mockResolvedValueOnce(new Response("{}", { status: 200 }));
    await expect(getClaimsWorkflow(workflowBody.workflow_id)).rejects.toThrow(
      "The workflow service returned an invalid response.",
    );
  });
});