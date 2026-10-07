import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { createInvestigation } from "./api";
import type { ClaimsInvestigationResponse } from "./api";

vi.mock("./api", () => ({
  createInvestigation: vi.fn(),
}));

const answeredBrief: ClaimsInvestigationResponse = {
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
    summary_source_ids: ["policy_evidence:chunk-1"],
    findings: [
      {
        text: "The policy limits flood cover.",
        source_ids: ["policy_evidence:chunk-1"],
      },
    ],
    unresolved_questions: ["What is the estimated repair cost?"],
    sources: [
      {
        source_id: "policy_evidence:chunk-1",
        source_type: "policy_evidence",
        record_id: "chunk-1",
        label: "Home Policy, section 4, clause 4.2, page 3",
        facts: { text: "Flood damage is covered subject to the stated limits." },
      },
    ],
    model: "gpt-oss-20b",
    tool_calls: 2,
    latency_ms: 120,
    trace_id: "f8b71e2420453174714c9aed94a0d4ea",
  },
  risk_assessment: {
    status: "available",
    priority_band: "routine_review",
    handler_triage_required: false,
    triage_reason: null,
    model_version: "stage5-test",
    unavailable_reason: null,
  },
  latency_ms: 120,
  trace_id: "f8b71e2420453174714c9aed94a0d4ea",
};

async function submitClaim(): Promise<void> {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Claim ID"), "CL-123");
  await user.type(
    screen.getByLabelText("Claim narrative"),
    "Flood water entered the ground floor overnight.",
  );
  await user.click(screen.getByRole("button", { name: /generate brief/i }));
}

describe("Claims evidence desk", () => {
  beforeEach(() => {
    vi.mocked(createInvestigation).mockReset();
  });

  afterEach(() => cleanup());

  it("shows source-linked findings and policy excerpts", async () => {
    vi.mocked(createInvestigation).mockResolvedValue(answeredBrief);
    render(<App />);

    await submitClaim();

    expect(await screen.findByText("Flood cover is subject to limits.")).toBeVisible();
    expect(screen.getByText("The policy limits flood cover.")).toBeVisible();
    const evidence = screen.getByRole("region", { name: "Policy evidence" });
    expect(within(evidence).getByText("Flood damage is covered subject to the stated limits.")).toBeVisible();
    expect(screen.getAllByText("Home Policy, section 4, clause 4.2, page 3")).toHaveLength(3);
  });

  it("renders risk advice in a distinct section from cited investigation findings", async () => {
    vi.mocked(createInvestigation).mockResolvedValue({
      ...answeredBrief,
      risk_assessment: {
        status: "available",
        priority_band: "priority_review",
        handler_triage_required: false,
        triage_reason: null,
        model_version: "stage5-test",
        unavailable_reason: null,
      },
    } as unknown as ClaimsInvestigationResponse);
    render(<App />);

    await submitClaim();

    const advisory = await screen.findByRole("region", { name: "Risk referral advisory" });
    expect(within(advisory).getByText("Priority review")).toBeVisible();
    expect(within(advisory).getByText(/stage5-test/)).toBeVisible();
    expect(
      within(screen.getByRole("region", { name: "Findings" })).queryByText(/priority/i),
    ).not.toBeInTheDocument();
  });

  it("keeps evidence visible when the risk service is unavailable", async () => {
    vi.mocked(createInvestigation).mockResolvedValue({
      ...answeredBrief,
      risk_assessment: {
        status: "unavailable",
        priority_band: null,
        handler_triage_required: null,
        triage_reason: null,
        model_version: null,
        unavailable_reason: "risk_service_unavailable",
      },
    });
    render(<App />);

    await submitClaim();

    const advisory = await screen.findByRole("region", { name: "Risk referral advisory" });
    expect(within(advisory).getByText("Assessment unavailable")).toBeVisible();
    expect(screen.getByText("Flood cover is subject to limits.")).toBeVisible();
    expect(screen.getByText("The policy limits flood cover.")).toBeVisible();
  });

  it("shows RAG retrieval failure separately from the investigation result", async () => {
    vi.mocked(createInvestigation).mockResolvedValue({
      ...answeredBrief,
      policy_evidence_status: "unavailable",
      policy_evidence_unavailable_reason: "retrieval_dependency_failed",
    } as unknown as ClaimsInvestigationResponse);
    render(<App />);

    await submitClaim();

    expect(
      await screen.findByRole("region", { name: "Policy evidence status" }),
    ).toHaveTextContent("Policy evidence could not be retrieved.");
    expect(screen.getByText("The policy limits flood cover.")).toBeVisible();
  });

  it("distinguishes insufficient evidence and renders no findings", async () => {
    vi.mocked(createInvestigation).mockResolvedValue({
      ...answeredBrief,
      investigation: {
        ...answeredBrief.investigation,
        status: "insufficient_evidence",
        summary: "",
        summary_source_ids: [],
        findings: [],
        unresolved_questions: ["Which rooms were affected?"],
        sources: [],
      },
    });
    render(<App />);

    await submitClaim();

    expect(await screen.findByText(/evidence is insufficient/i)).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Findings" })).not.toBeInTheDocument();
    expect(screen.getByText("Which rooms were affected?")).toBeVisible();
  });

  it("shows a safe service error without exposing internal details", async () => {
    vi.mocked(createInvestigation).mockRejectedValue(
      new Error("The investigation service is unavailable."),
    );
    render(<App />);

    await submitClaim();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The investigation service is unavailable.",
    );
    expect(screen.queryByText(/stack|traceback|provider/i)).not.toBeInTheDocument();
  });

  it("blocks an invalid form and identifies required fields", async () => {
    render(<App />);
    expect(screen.getByText(/narrative goes to hosted models/i)).toBeVisible();
    expect(screen.getByText(/the app does not save it/i)).toBeVisible();
    await userEvent.setup().click(screen.getByRole("button", { name: /generate brief/i }));

    expect(screen.getByRole("alert")).toHaveTextContent("Review the highlighted fields.");
    expect(screen.getAllByText("Required")).toHaveLength(1);
    expect(screen.getByText("Enter at least 5 characters")).toBeVisible();
    expect(createInvestigation).not.toHaveBeenCalled();
  });

  it("shows a pending state while the request is in flight", async () => {
    let resolveRequest: (response: ClaimsInvestigationResponse) => void = () => undefined;
    vi.mocked(createInvestigation).mockReturnValue(
      new Promise((resolve) => {
        resolveRequest = resolve;
      }),
    );
    render(<App />);
    await submitClaim();

    expect(screen.getByRole("button", { name: /preparing brief/i })).toBeDisabled();
    expect(screen.getByLabelText("Claim narrative")).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Resolving applicable wording and evidence");
    resolveRequest(answeredBrief);
    expect(await screen.findByText("Flood cover is subject to limits.")).toBeVisible();
  });

  it("does not restore a cleared brief when an older request completes", async () => {
    let resolveRequest: (response: ClaimsInvestigationResponse) => void = () => undefined;
    vi.mocked(createInvestigation).mockReturnValue(
      new Promise((resolve) => {
        resolveRequest = resolve;
      }),
    );
    render(<App />);
    await submitClaim();

    await userEvent.setup().click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByRole("button", { name: /generate brief/i })).toBeEnabled();
    expect(screen.getByText("Waiting for a claim")).toBeVisible();

    await act(async () => {
      resolveRequest(answeredBrief);
      await Promise.resolve();
    });

    expect(screen.queryByText("Flood cover is subject to limits.")).not.toBeInTheDocument();
    expect(screen.getByText("Waiting for a claim")).toBeVisible();
  });
});