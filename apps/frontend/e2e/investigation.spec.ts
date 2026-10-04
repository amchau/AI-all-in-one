import { expect, test } from "@playwright/test";

const answeredBrief = {
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

const requestPath = "**/api/v1/investigations";

test("development proxy exposes only the copilot investigation route", async ({ request }) => {
  for (const path of ["/api", "/api/v1/investigate", "/api/v1/rag/query"]) {
    const response = await request.get(path);
    expect(response.status(), path).toBe(404);
  }
});

async function completeClaimForm(page: import("@playwright/test").Page): Promise<void> {
  await page.getByLabel("Claim ID").fill("CL-123");
  await page.getByLabel("Policy ID").fill("HOME-002");
  await page.getByLabel("Loss date").fill("2025-03-01");
  await page.getByLabel("Claim narrative").fill("Flood water entered the ground floor overnight.");
}

test("handler reviews cited evidence without horizontal overflow", async ({ page }) => {
  await page.route(requestPath, (route) => route.fulfill({ json: answeredBrief }));
  await page.goto("/");
  await expect(page.getByText(/narrative goes to hosted models/i)).toBeVisible();
  await completeClaimForm(page);
  await page.getByRole("button", { name: /generate brief/i }).click();

  await expect(page.getByText("Flood cover is subject to limits.")).toBeVisible();
  await expect(page.getByText("The policy limits flood cover.")).toBeVisible();
  await page.getByRole("link", { name: "Open cited evidence C1" }).first().click();
  await expect(page.locator("#evidence-chunk-1")).toBeInViewport();

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
        status: "insufficient_evidence",
        summary: "",
        summary_citations: [],
        findings: [],
        evidence: [],
        unresolved_questions: ["Which rooms were affected?"],
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