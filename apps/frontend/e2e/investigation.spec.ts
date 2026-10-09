import { expect, test } from "@playwright/test";

const answeredBrief = {
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
    priority_band: "priority_review",
    handler_triage_required: false,
    triage_reason: null,
    model_version: "stage5-test",
    unavailable_reason: null,
  },
  latency_ms: 120,
  trace_id: "f8b71e2420453174714c9aed94a0d4ea",
};

const requestPath = "**/api/v1/claims/hybrid-investigations";
const workflowPath = "**/api/v1/claims/workflows**";

test("development proxy exposes only the approved claims routes", async ({ request }) => {
  for (const path of [
    "/api",
    "/api/v1/investigate",
    "/api/v1/rag/query",
    "/api/v1/investigations",
    "/api/v1/claims/workflows-extra",
  ]) {
    const response = await request.get(path);
    expect(response.status(), path).toBe(404);
  }

  const workflowPathResponse = await request.get(
    "/api/v1/claims/workflows/11111111-1111-4111-8111-111111111111",
  );
  expect(workflowPathResponse.status()).not.toBe(404);
});

async function completeClaimForm(page: import("@playwright/test").Page): Promise<void> {
  await page.getByLabel("Claim ID").fill("CL-123");
  await page.getByLabel("Claim narrative").fill("Flood water entered the ground floor overnight.");
}

test("handler reviews the combined brief and referral advice without overflow", async ({ page }) => {
  await page.route(requestPath, (route) => route.fulfill({ json: answeredBrief }));
  await page.goto("/");
  await expect(page.getByText(/narrative goes to hosted models/i)).toBeVisible();
  await completeClaimForm(page);
  await page.getByRole("button", { name: /generate brief/i }).click();

  await expect(page.getByText("Flood cover is subject to limits.")).toBeVisible();
  await expect(page.getByText("The policy limits flood cover.")).toBeVisible();
  await expect(page.getByRole("region", { name: "Policy evidence status" })).toContainText(
    "Policy evidence was retrieved and supplied to the investigation.",
  );
  await expect(page.getByRole("region", { name: "Risk referral advisory" })).toContainText("Priority review");
  await expect(page.getByRole("region", { name: "Policy evidence", exact: true })).toContainText(
    "Flood damage is covered subject to the stated limits.",
  );

  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(hasHorizontalOverflow).toBe(false);
});

test("handler sees abstention and dependency errors as separate states", async ({ page }) => {
  await page.route(requestPath, (route) =>
    route.fulfill({
      json: {
        ...answeredBrief,
        investigation: {
          ...answeredBrief.investigation,
          status: "insufficient_evidence",
          summary: "",
          summary_source_ids: [],
          findings: [],
          sources: [],
          unresolved_questions: ["Which rooms were affected?"],
        },
      },
    }),
  );
  await page.goto("/");
  await completeClaimForm(page);
  await page.getByRole("button", { name: /generate brief/i }).click();
  await expect(page.getByText("Evidence is insufficient")).toBeVisible();
  await expect(page.getByText("Which rooms were affected?")).toBeVisible();

  await page.unroute(requestPath);
  await page.route(requestPath, (route) =>
    route.fulfill({ status: 502, json: { detail: "private provider detail" } }),
  );
  await page.getByRole("button", { name: /generate brief/i }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "The investigation service is unavailable. Try again later.",
  );
  await expect(page.getByText("private provider detail")).toHaveCount(0);
});

test("handler can reload a workflow and submit a persisted human disposition", async ({ page }) => {
  let state = "created";
  const workflowId = "11111111-1111-4111-8111-111111111111";
  const result = {
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
      findings: [{ text: "Schedule applicability requires confirmation.", source_ids: ["policy_evidence:chunk-1"] }],
      unresolved_questions: ["Is the extension on the schedule?"],
      sources: [{ source_id: "policy_evidence:chunk-1", source_type: "policy_evidence" }],
      model: "test-model",
      tool_calls: 2,
      latency_ms: 120,
      trace_id: "f8b71e2420453174714c9aed94a0d4ea",
    },
    risk_assessment: answeredBrief.risk_assessment,
    latency_ms: 120,
    trace_id: "f8b71e2420453174714c9aed94a0d4ea",
  };
  const response = () => ({
    workflow_id: workflowId,
    claim_id: "CL-123",
    state,
    version: state === "created" ? 0 : state === "awaiting_human_review" ? 2 : 3,
    created_at: "2026-10-09T10:00:00Z",
    updated_at: "2026-10-09T10:00:05Z",
    error_code: null,
    result: state === "awaiting_human_review" || state === "completed" ? result : null,
    history: [],
  });

  await page.route(workflowPath, async (route) => {
    const method = route.request().method();
    if (method === "POST" && route.request().url().endsWith("/workflows")) {
      state = "awaiting_human_review";
      await route.fulfill({ status: 202, json: response() });
      return;
    }
    if (method === "POST" && route.request().url().endsWith("/dispositions")) {
      state = "completed";
      await route.fulfill({ status: 200, json: response() });
      return;
    }
    await route.fulfill({ status: 200, json: response() });
  });

  await page.goto("/");
  await page.getByRole("tab", { name: "Approval workflow" }).click();
  await completeClaimForm(page);
  await page.getByRole("button", { name: /create workflow/i }).click();

  await expect(page.getByText("Flood cover is subject to limits.")).toBeVisible();
  await expect(page.getByText(/not a claim decision/i)).toBeVisible();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("claims-workflow-id")))
    .toBe(workflowId);

  await page.reload();
  await page.getByRole("tab", { name: "Approval workflow" }).click();
  await expect(page.getByText("Flood cover is subject to limits.")).toBeVisible();
  await page.getByLabel("Review reason").fill("Continue review");
  await page.getByRole("button", { name: /continue workflow/i }).click();
  await expect(page.getByRole("heading", { name: "Workflow completed" })).toBeVisible();
  expect(await page.evaluate(() => localStorage.length)).toBe(1);
});