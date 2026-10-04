import { z } from "zod";

const identifier = z
  .string()
  .trim()
  .min(1, "Required")
  .max(80, "Must be 80 characters or fewer")
  .regex(/^[A-Za-z0-9][A-Za-z0-9_-]*$/, "Use letters, numbers, hyphens, or underscores");

export const investigationRequestSchema = z.object({
  claim_id: identifier,
  policy_id: identifier,
  loss_date: z.iso.date("Enter a valid loss date"),
  guidance_as_of: z.union([z.iso.date("Enter a valid guidance date"), z.literal("")]).optional(),
  narrative: z
    .string()
    .trim()
    .min(5, "Enter at least 5 characters")
    .max(1000, "Keep the narrative to 1,000 characters or fewer"),
});

export type ClaimsInvestigationRequest = z.infer<typeof investigationRequestSchema>;