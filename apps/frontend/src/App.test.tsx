import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
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
  status: "answered",
  summary: "Flood cover is subject to limits.",
  summary_citations: [
    {
      ref: "C1",
      chunk_id: "chunk-1",
      doc_id: "POL-HOME-002-v2",
      title: "Home Policy",
      section: "4",
      clause: "4.2",
      page: 3,
    },
  ],
  findings: [
    {
      text: "The policy limits flood cover.",
      citations: [
        {
          ref: "C1",
          chunk_id: "chunk-1",
          doc_id: "POL-HOME-002-v2",
          title: "Home Policy",
          section: "4",
          clause: "4.2",
          page: 3,
        },
      ],
    },
  ],
  unresolved_questions: ["What is the estimated repair cost?"],
  evidence: [
    {
      chunk_id: "chunk-1",
      ref: "C1",
      title: "Home Policy",
      section: "4",
      clause: "4.2",
      page: 3,
      text: "Flood damage is covered subject to the stated limits.",
    },
  ],
  model: "gpt-oss-20b",
  latency_ms: 120,
  trace_id: "f8b71e2420453174714c9aed94a0d4ea",
};

async function submitClaim(): Promise<void> {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Claim ID"), "CL-123");
  await user.type(screen.getByLabelText("Policy ID"), "HOME-002");
  await user.type(screen.getByLabelText("Loss date"), "2025-03-01");
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

  it("shows the cited evidence brief and navigates to its source", async () => {
    vi.mocked(createInvestigation).mockResolvedValue(answeredBrief);
    render(<App />);

    await submitClaim();

    expect(await screen.findByText("Flood cover is subject to limits.")).toBeVisible();
    expect(screen.getByText("The policy limits flood cover.")).toBeVisible();
    const evidence = screen.getByRole("region", { name: "Cited evidence" });
    expect(within(evidence).getByText("Flood damage is covered subject to the stated limits.")).toBeVisible();
    const summary = screen.getByRole("region", { name: "Brief summary" });
    await userEvent.setup().click(
      within(summary).getByRole("link", { name: "Open cited evidence C1" }),
    );
    await waitFor(() => expect(window.location.hash).toContain("chunk-1"));
  });

  it("distinguishes insufficient evidence and renders no findings", async () => {
    vi.mocked(createInvestigation).mockResolvedValue({
      ...answeredBrief,
      status: "insufficient_evidence",
      summary: "",
      summary_citations: [],
      findings: [],
      unresolved_questions: ["Which rooms were affected?"],
      evidence: [],
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
    expect(screen.getAllByText("Required")).toHaveLength(2);
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