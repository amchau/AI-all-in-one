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

test("development proxy exposes only the hybrid claims route", async ({ request }) => {
  for (const path of [
    "/api",
    "/api/v1/investigate",
    "/api/v1/rag/query",
    "/api/v1/investigations",
  ]) {
    const response = await request.get(path);
    expect(response.status(), path).toBe(404);
  }
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