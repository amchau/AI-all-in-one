import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import {
  createClaimsWorkflow,
  createInvestigation,
  getClaimsWorkflow,
  resumeClaimsWorkflow,
  submitClaimsWorkflowDisposition,
} from "./api";
import type { ClaimsInvestigationResponse, ClaimsWorkflowStatus } from "./api";

vi.mock("./api", () => ({
  createClaimsWorkflow: vi.fn(),
  createInvestigation: vi.fn(),
  getClaimsWorkflow: vi.fn(),
  resumeClaimsWorkflow: vi.fn(),
  submitClaimsWorkflowDisposition: vi.fn(),
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

const waitingWorkflow: ClaimsWorkflowStatus = {
  workflow_id: "11111111-1111-4111-8111-111111111111",
  claim_id: "CL-123",
  state: "awaiting_human_review",
  version: 2,
  created_at: "2026-10-09T10:00:00Z",
  updated_at: "2026-10-09T10:00:05Z",
  error_code: null,
  result: {
    claim_id: "CL-123",
    policy_id: "HOME-002",
    loss_date: "2025-03-01",
    guidance_as_of: "2025-03-01",
    policy_evidence_status: "retrieved",
    policy_evidence_unavailable_reason: null,
    investigation: {
      claim_id: "CL-123",
      status: "answered",
      summary: "Review summary",
      summary_source_ids: ["policy_evidence:chunk-1"],
      findings: [{ text: "Review finding", source_ids: ["policy_evidence:chunk-1"] }],
      unresolved_questions: ["Confirm the schedule."],
      sources: [
        {
          source_id: "policy_evidence:chunk-1",
          source_type: "policy_evidence",
        },
      ],
      model: "test-model",
      tool_calls: 2,
      latency_ms: 100,
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
  },
  history: [
    {
      event_id: 1,
      from_state: null,
      state: "created",
      action: "created",
      disposition: null,
      actor_id: "system",
      reason: "Workflow created",
      trace_id: null,
      created_at: "2026-10-09T10:00:00Z",
    },
  ],
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
    window.localStorage.clear();
    vi.mocked(createInvestigation).mockReset();
    vi.mocked(createClaimsWorkflow).mockReset();
    vi.mocked(getClaimsWorkflow).mockReset();
    vi.mocked(resumeClaimsWorkflow).mockReset();
    vi.mocked(submitClaimsWorkflowDisposition).mockReset();
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

  it("creates a persisted workflow and submits a human-only disposition", async () => {
    vi.mocked(createClaimsWorkflow).mockResolvedValue({
      ...waitingWorkflow,
      state: "created",
      version: 0,
      result: null,
      history: [],
    });
    vi.mocked(getClaimsWorkflow).mockResolvedValue(waitingWorkflow);
    vi.mocked(submitClaimsWorkflowDisposition).mockResolvedValue({
      ...waitingWorkflow,
      state: "completed",
      version: 3,
    });
    render(<App />);

    await userEvent.setup().click(screen.getByRole("tab", { name: "Approval workflow" }));
    await userEvent.setup().type(screen.getByLabelText("Claim ID"), "CL-123");
    await userEvent.setup().type(
      screen.getByLabelText("Claim narrative"),
      "Flood water entered the ground floor overnight.",
    );
    await userEvent.setup().click(screen.getByRole("button", { name: /create workflow/i }));

    expect(await screen.findByText("Review summary")).toBeVisible();
    expect(window.localStorage.getItem("claims-workflow-id")).toBe(
      waitingWorkflow.workflow_id,
    );
    expect(screen.getByText(/not a claim decision/i)).toBeVisible();
    expect(screen.getByText("Confirm the schedule.")).toBeVisible();
    await userEvent.setup().type(screen.getByLabelText("Review reason"), "Continue review");
    await userEvent.setup().click(screen.getByRole("button", { name: /continue workflow/i }));

    expect(await screen.findByText(/completed/i)).toBeVisible();
    expect(submitClaimsWorkflowDisposition).toHaveBeenCalledWith(
      waitingWorkflow.workflow_id,
      expect.objectContaining({
        disposition: "continue",
        expected_version: 2,
        actor_id: "synthetic-handler-1",
      }),
    );
  });

  it("loads a saved workflow ID and shows its persisted review", async () => {
    vi.mocked(getClaimsWorkflow).mockResolvedValue(waitingWorkflow);
    render(<App />);
    await userEvent.setup().click(screen.getByRole("tab", { name: "Approval workflow" }));
    await userEvent.setup().type(
      screen.getByLabelText("Load saved workflow"),
      waitingWorkflow.workflow_id,
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Load" }));

    expect(await screen.findByText("Review summary")).toBeVisible();
    expect(getClaimsWorkflow).toHaveBeenCalledWith(waitingWorkflow.workflow_id);
  });

  it("restores only the workflow ID after a browser refresh", async () => {
    window.localStorage.setItem("claims-workflow-id", waitingWorkflow.workflow_id);
    vi.mocked(getClaimsWorkflow).mockResolvedValue(waitingWorkflow);
    render(<App />);
    await userEvent.setup().click(screen.getByRole("tab", { name: "Approval workflow" }));

    expect(await screen.findByText("Review summary")).toBeVisible();
    expect(screen.getByLabelText("Load saved workflow")).toHaveValue(
      waitingWorkflow.workflow_id,
    );
    expect(window.localStorage.length).toBe(1);
  });

  it("requires new information before resuming a request-info workflow", async () => {
    const requestInfoWorkflow: ClaimsWorkflowStatus = {
      ...waitingWorkflow,
      state: "needs_more_information",
      version: 3,
    };
    vi.mocked(createClaimsWorkflow).mockResolvedValue({
      ...waitingWorkflow,
      state: "created",
      version: 0,
      result: null,
      history: [],
    });
    vi.mocked(getClaimsWorkflow).mockResolvedValue(requestInfoWorkflow);
    vi.mocked(resumeClaimsWorkflow).mockResolvedValue({
      ...waitingWorkflow,
      state: "created",
      version: 4,
      result: null,
    });
    render(<App />);
    await userEvent.setup().click(screen.getByRole("tab", { name: "Approval workflow" }));
    await userEvent.setup().type(screen.getByLabelText("Claim ID"), "CL-123");
    await userEvent.setup().type(
      screen.getByLabelText("Claim narrative"),
      "Flood water entered the ground floor overnight.",
    );
    await userEvent.setup().click(screen.getByRole("button", { name: /create workflow/i }));
    expect(await screen.findByRole("region", { name: "Resume workflow" })).toBeVisible();
    await userEvent.setup().type(screen.getByLabelText("Resume reason"), "Details received");
    await userEvent.setup().type(
      screen.getByLabelText("Updated investigation narrative"),
      "The flood extension appears on the schedule.",
    );
    await userEvent.setup().click(screen.getByRole("button", { name: /resume investigation/i }));

    expect(
      await screen.findByRole("heading", { name: "Queued for investigation" }),
    ).toBeVisible();
    expect(resumeClaimsWorkflow).toHaveBeenCalledWith(
      waitingWorkflow.workflow_id,
      expect.objectContaining({
        expected_version: 3,
        updated_narrative: "The flood extension appears on the schedule.",
      }),
    );
  });

  it("shows a safe error when workflow creation fails", async () => {
    vi.mocked(createClaimsWorkflow).mockRejectedValue(new Error("The workflow service is unavailable."));
    render(<App />);
    await userEvent.setup().click(screen.getByRole("tab", { name: "Approval workflow" }));
    await userEvent.setup().type(screen.getByLabelText("Claim ID"), "CL-123");
    await userEvent.setup().type(
      screen.getByLabelText("Claim narrative"),
      "Flood water entered the ground floor overnight.",
    );
    await userEvent.setup().click(screen.getByRole("button", { name: /create workflow/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The workflow service is unavailable.");
  });

  it.each([
    {
      state: "investigating" as const,
      error_code: null,
      heading: "Investigation in progress",
      message: null,
    },
    {
      state: "failed" as const,
      error_code: "worker_interrupted" as const,
      heading: "Workflow unavailable",
      message: "The worker stopped during investigation. No automatic retry was made.",
    },
    {
      state: "failed" as const,
      error_code: "stage6_dependency_failed" as const,
      heading: "Workflow unavailable",
      message: "The investigation could not be completed. No automatic retry was made.",
    },
    {
      state: "cancelled" as const,
      error_code: null,
      heading: "Workflow stopped",
      message: null,
    },
  ])("renders persisted $state workflow status", async ({ state, error_code, heading, message }) => {
    const savedWorkflow: ClaimsWorkflowStatus = {
      ...waitingWorkflow,
      state,
      error_code,
      result: null,
    };
    vi.mocked(getClaimsWorkflow).mockResolvedValue(savedWorkflow);
    render(<App />);
    await userEvent.setup().click(screen.getByRole("tab", { name: "Approval workflow" }));
    await userEvent.setup().type(
      screen.getByLabelText("Load saved workflow"),
      savedWorkflow.workflow_id,
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Load" }));

    expect(await screen.findByRole("heading", { name: heading })).toBeVisible();
    if (message) expect(screen.getByText(message)).toBeVisible();
  });
});