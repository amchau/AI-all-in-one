import { describe, expect, it } from "vitest";

import { investigationRequestSchema } from "./validation";

const validRequest = {
  claim_id: "CL-123",
  policy_id: "HOME-002",
  loss_date: "2025-03-01",
  guidance_as_of: "",
  narrative: "Flood water entered the ground floor overnight.",
};

describe("investigation request validation", () => {
  it("accepts bounded claim context and trims surrounding whitespace", () => {
    const result = investigationRequestSchema.parse({
      ...validRequest,
      claim_id: " CL-123 ",
      narrative: " Flood water entered the ground floor overnight. ",
    });

    expect(result.claim_id).toBe("CL-123");
    expect(result.narrative).toBe("Flood water entered the ground floor overnight.");
  });

  it("rejects invalid identifiers, dates, and oversized narratives", () => {
    expect(investigationRequestSchema.safeParse({ ...validRequest, policy_id: "../../secret" }).success).toBe(false);
    expect(investigationRequestSchema.safeParse({ ...validRequest, loss_date: "2025-02-30" }).success).toBe(false);
    expect(investigationRequestSchema.safeParse({ ...validRequest, narrative: "n".repeat(1001) }).success).toBe(false);
  });
});