export interface RetrievalEvaluationMode {
  mode: string;
  recallAt5: number;
  reciprocalRank: number;
  citationPrecision: number;
  citationsEvaluated: number;
  noCitationResponses: number;
  answerabilityAccuracy: number;
  cases: number;
  clientLatencyMedianMs: number;
  clientLatencyP95Ms: number;
  failedRequests: number;
}

export const retrievalEvaluation = {
  suite: "Stage 2.5 RAG comparison",
  run: "2026-10-04",
  cases: 35,
  modes: [
    {
      mode: "Dense",
      recallAt5: 0.966,
      reciprocalRank: 0.931,
      citationPrecision: 0.761,
      citationsEvaluated: 46,
      noCitationResponses: 6,
      answerabilityAccuracy: 1,
      cases: 35,
      clientLatencyMedianMs: 7936,
      clientLatencyP95Ms: 12696,
      failedRequests: 0,
    },
    {
      mode: "Hybrid",
      recallAt5: 0.983,
      reciprocalRank: 0.948,
      citationPrecision: 0.795,
      citationsEvaluated: 44,
      noCitationResponses: 6,
      answerabilityAccuracy: 1,
      cases: 35,
      clientLatencyMedianMs: 8313,
      clientLatencyP95Ms: 10711,
      failedRequests: 0,
    },
    {
      mode: "Hybrid + rerank",
      recallAt5: 1,
      reciprocalRank: 0.948,
      citationPrecision: 0.787,
      citationsEvaluated: 47,
      noCitationResponses: 6,
      answerabilityAccuracy: 1,
      cases: 35,
      clientLatencyMedianMs: 7476,
      clientLatencyP95Ms: 10646,
      failedRequests: 0,
    },
  ] satisfies RetrievalEvaluationMode[],
  limitation: "Fixed synthetic cases; metrics do not establish semantic correctness or faithfulness.",
} as const;

export const riskEvaluation = {
  suite: "Stage 5 synthetic referral model",
  run: "2026-10-06",
  archetypes: 44,
  generatedRows: 1320,
  holdoutRows: 270,
  independentHoldoutArchetypes: 9,
  recall: 1,
  precision: 1,
  prAuc: 1,
  reviewVolumeFraction: 0.556,
  baselinePrecision: 0.684,
  baselineName: "Logistic regression",
  limitation: "Rule-derived labels; 44 independent archetypes. Not fraud ground truth or real-claims performance.",
} as const;
