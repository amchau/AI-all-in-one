import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createInvestigation,
} from "./api";
import type { ClaimsInvestigationResponse } from "./api";

const request = {
  claim_id: "CL-123",
  policy_id: "HOME-002",
  loss_date: "2025-03-01",
  narrative: "Flood water entered the ground floor overnight.",
};

const responseBody: ClaimsInvestigationResponse = {
  claim_id: "CL-123",
  policy_id: "HOME-002",
  loss_date: "2025-03-01",
  guidance_as_of: "2025-03-01",
  status: "answered",
  summary: "Flood cover is subject to limits.",
  summary_citations: [],
  findings: [],
  unresolved_questions: [],
  evidence: [],
  model: "gpt-oss-20b",
  latency_ms: 120,
  trace_id: "f8b71e2420453174714c9aed94a0d4ea",
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
      "/api/v1/investigations",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(request),
      }),
    );
  });

  it("maps policy conflicts to safe user-facing messages", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("private details", { status: 409 }));

    await expect(createInvestigation(request)).rejects.toThrow(
      "The applicable policy wording is ambiguous. Review the policy dates.",
    );
    await expect(createInvestigation(request)).rejects.not.toThrow("private details");
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