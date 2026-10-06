# Stage 5 Claims Risk Model: Synthetic Evaluation Report

Date: 2026-10-06  
Status: Prototype gate passed on synthetic data only; not fraud detection or production readiness.

## Scope and label rubric

The target is `refer_for_human_review`, a synthetic referral label, not a fraud finding. A record is
labeled positive when any rule applies:

- `duplicate_document_count >= 2`
- `date_inconsistency_count >= 2`
- `missing_required_evidence_count >= 3`
- `prior_open_claim_count >= 4`

Negative means none of those synthetic indicators are present. Label reason records the first matching
rule in the order above. The five structured model inputs are those counts plus
`estimate_limit_ratio` (estimate divided by declared limit, bounded to 0.0-2.0). No claim narrative,
customer identifier, or real data is used.

The checked-in table has 44 hand-authored archetypes (20 negative, 24 positive). Thirty deterministic
variants per archetype produce 1,320 rows. Splits are grouped by archetype, not row: training has 12
negative and 14 positive archetypes (780 rows); validation has 4 negative and 5 positive archetypes
(270 rows); the untouched holdout has 4 negative and 5 positive archetypes (270 rows). Dataset seed:
1729; split seed: 31415; model seed: 27182. Runtime: Python 3.12.14, scikit-learn 1.9.1,
xgboost-cpu 3.4.1.
Dataset SHA-256: `83d822aa56de3b134553e40466a923beb2b5e50cbdc94aec18fd6fefa8a7d6d2`.

## Method

XGBoost, logistic regression, and a majority-class baseline use identical grouped partitions. Each
candidate's priority threshold is selected on validation data to meet at least 90% referral recall.
The holdout set is evaluated once after fitting and threshold selection. XGBoost promotion requires
at least 90% holdout recall and precision strictly above both baselines. The deployed API does not
return a probability; outputs near the threshold are sent to handler triage.

## Results

| Candidate | Holdout recall | Holdout precision | PR-AUC (average precision) | Brier score | ECE | Priority-review volume |
|---|---:|---:|---:|---:|---:|---:|
| XGBoost | 100.0% | 100.0% | 1.000 | 0.0029 | 0.0532 | 150/270 (55.6%) |
| Logistic regression | 95.3% | 68.4% | 0.865 | 0.1600 | 0.0613 | 209/270 (77.4%) |
| Majority baseline | 100.0% | 55.6% | 0.556 | 0.2472 | 0.0171 | 270/270 (100.0%) |

XGBoost passed the prototype gate. Promoted model version: `stage5-cfb12f6a9cc1`. Artifact SHA-256:
`cfb12f6a9cc178ebfd98c17f3a94a0792bfb47ad1dc50f8ae5abaa43b17410a5`. Detailed machine-readable
metrics and provenance are in [stage5-risk-model-results.json](stage5-risk-model-results.json).

Serving smoke (2026-10-06): the rolled-out internal service returned `handler_triage_required=true`
with reason `near_decision_threshold` for one synthetic assessment. Trace
`e40a3fd6e0348bea6f1bb5122785dace` was found in the OTEL Collector. One smoke request verifies
integration only, not service reliability.

## Limitations

- Labels are computed from the same explicit synthetic indicators supplied to the model. The perfect
  XGBoost score shows that this implementation learned the synthetic rule; it does not establish
  generalization to real claim behavior, fraud, or production workloads.
- Thirty variants do not create more than 44 independent archetypes. The effective independent sample
  for generalization remains small; percentages are descriptive of this synthetic holdout only.
- Synthetic indicators/rules are illustrative and are not a validated fraud rubric. No legal,
  actuarial, fairness, or domain-expert validation is claimed.
- The priority band is advisory. A human handler remains responsible for review. Near-threshold and
  incomplete assessments require handler triage; no claim action or coverage outcome is produced.
- This evaluation says nothing about authenticated real-data deployment, provider behavior, or
  production readiness.
