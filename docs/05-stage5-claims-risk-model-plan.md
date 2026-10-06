# Stage 5 - Claims Risk Model

Status: **DONE FOR APPROVED LOCAL SYNTHETIC SCOPE**
Pattern: Synthetic decision intelligence with human review
Builds on: Stage 4 synthetic claims service; does not integrate into the Stage 4 agent

## 0. Problem and outcome

The roadmap calls for a claims risk model but does not define its prediction target, labels, output,
evaluation, or serving boundary. Stage 4 contains only two synthetic claims and no outcome labels,
which are insufficient for supervised training. Stage 5 will build a reproducible synthetic dataset,
train and evaluate an offline binary referral model, and expose a versioned local inference API.

The positive class means **refer this synthetic claim for human fraud review**. It does not mean the
claim is fraudulent. The service only informs a handler; it must not make coverage decisions,
recommend approval or denial, or perform claim actions. This synthetic exercise does not establish
real-world fraud detection or production readiness.

## 1. Approved scope

- Hand-authored, reviewable synthetic claim archetypes with explicit referral labels and rationale.
- A deterministic seeded generator for controlled variants; generated examples retain their source
  archetype ID for leakage-safe splitting.
- Structured, bounded, non-identifying tabular inputs only. Do not ingest claim narratives, customer
  identifiers, or real data.
- Offline XGBoost training plus logistic-regression and majority-class baselines; fixed feature
  preprocessing, reproducible seeds, and a versioned immutable model artifact.
- A separate internal FastAPI inference service. Response contains a review-priority band, an
  explicit handler-triage-required status/reason for incomplete or near-threshold inputs,
  model version, and trace ID. Do not expose a numerical probability in the initial API.
- OpenTelemetry `ml.*` trace for bounded operational attributes such as model version, latency, and
  outcome category. Never record request content, identifiers, raw features, or labels.
- Local kind + Podman delivery following current Python 3.12 and hardened Kubernetes conventions.
- A methodology/results report that clearly distinguishes synthetic-label performance from actual
  fraud risk or operational effectiveness.

## 2. Out of scope

- Real claims/customer data, production readiness, or fraud determinations.
- Coverage decisions, approve/deny recommendations, payment actions, or claim mutation.
- Use of claim narrative text, identity attributes, or raw customer identifiers as model features.
- Integration into `agents/claims`, RAG, or the Stage 3 frontend; that orchestration remains Stage 6.
- Online training, mutable model downloads, persistence of predictions, or handler feedback capture.
- Claims that synthetic recall proves real-world safety or model quality.

## 3. Data and model contract

- Target: `refer_for_human_review`, a synthetic binary label defined by a documented rubric over
  explicitly listed synthetic evidence indicators. It is not a fraud ground-truth label.
- Inputs: `duplicate_document_count` (0-3), `date_inconsistency_count` (0-3),
  `missing_required_evidence_count` (0-4), `prior_open_claim_count` (0-5), and
  `estimate_limit_ratio` (0.0-2.0). No narrative or identity data.
- The synthetic positive label applies when duplicate documents >= 2, date inconsistencies >= 2,
  missing required evidence >= 3, or prior open claims >= 4. Label reason records the first matching
  rule in that order. This is a transparent synthetic referral rubric, not fraud ground truth.
- Dataset records include stable row ID, archetype ID, feature values, label, label-rationale code,
  generator version, and seed/provenance. No free-text customer details.
- Splits are made by archetype, not generated row. Train, validation, and untouched test groups must
  be disjoint, with both labels represented in each partition. Fail closed if the data cannot meet
  this condition; do not fall back to row-random splits.
- API rejects malformed or out-of-range requests with a sanitized 422. Valid but incomplete
  assessments and predictions near the selected threshold return a triage response; do not force a
  priority classification in these cases.
- For scored inputs, priority bands are `routine_review` and `priority_review`; response includes no
  raw probability. The validation-selected threshold prioritizes recall. A priority score is not an
  instruction or claim outcome.

## 4. Evaluation and go/no-go

- Compare XGBoost with logistic regression and a majority baseline on identical grouped partitions.
- Tune the priority threshold using validation data only. Evaluate the held-out archetype test set
  once, after freezing the model and threshold.
- Prototype go/no-go gate: at least **90% referral recall** on the untouched synthetic test set.
  Report precision, false-negative/false-positive counts, resulting priority-review volume, PR-AUC,
  Brier score, expected calibration error (10 equal-width bins), and calibration summary with sample
  counts and provenance. Report baseline results too.
- If 90% recall is not met, report the failed gate and do not expose the model as a validated
  prioritizer. Do not change data, threshold, or model after viewing test outcomes and still call it
  the same holdout evaluation.
- The 90% gate applies only to the generated synthetic dataset; it is not a real-world service-level
  target. Small or correlated archetype counts and label-rule simplicity must be prominent limitations.

## 5. Implementation slices

1. **Contracts and rubric:** define the feature schema, ranges, target rubric, label-rationale codes,
  response states, and malformed/incomplete-input behavior. Add tests before implementation.
2. **Synthetic dataset:** add hand-authored archetypes, deterministic seeded variants, provenance,
   schema checks, class-balance checks, and group-disjoint train/validation/test generation. Add a
   dataset audit report before fitting a model.
3. **Training/evaluation:** add pinned Python 3.12 training dependencies, feature preprocessing,
   XGBoost/logistic/majority baselines, validation-only threshold selection, artifact export, hashes,
   and machine-readable metrics. Keep training out of the serving container.
4. **Inference API:** create a separate Python 3.12 FastAPI app that loads the packaged immutable
   artifact, validates bounded inputs, returns the documented output contract, and fails safely if
   model metadata/schema versions mismatch. Instrument `ml.*` spans without raw inputs.
5. **Deployment:** add a pinned service image, hardened internal Deployment/Service with probes and
   resource requests/limits, Kustomize registration, and a Podman-aware build/load script. Include
   `/tmp` writable storage if root filesystem is read-only and required by runtime libraries.
6. **Closeout:** run unit/integration/evaluation tests, Python compilation, shell syntax, Kustomize
   render, image build/load, rollout checks, one synthetic API smoke request, and trace correlation.
   Publish actual results and limitations; update roadmap, README, and `AGENTS.md` only after verified
   completion. Leave Stage 4 agent integration for Stage 6.

## 6. Proposed architecture decision

ADR-012 records the user-approved XGBoost choice and separate train/serve boundary. XGBoost is chosen
for its established Python/scikit-learn estimator workflow and adequate CPU behavior at this small
prototype scale; LightGBM's speed advantage is not a current requirement. Logistic regression remains
a baseline, so model complexity must earn its place on the grouped holdout. Pin compatible releases
and verify installation/training in Python 3.12 before deployment.

## 7. Acceptance criteria

- Dataset validation proves reproducibility, allowed feature schema, documented label rules, both
  classes per split, and zero archetype overlap across partitions.
- Automated tests cover generation, validation, features, split leakage, metrics, threshold selection,
  artifact metadata/loading, API error handling, incomplete/near-threshold triage, and trace
  privacy. New Stage 5 packages target at least 80% coverage.
- XGBoost and baselines are evaluated on the same untouched grouped test set; report all required
  metrics and the 90% recall go/no-go without overstating synthetic results.
- Inference returns priority only for supported sufficiently certain inputs; triage cases do not
  receive an automated priority band. No probability is returned by the initial API.
- Service remains internal, read-only, non-root, resource-bounded, and independent of the Stage 4
  agent. Existing Stage 2-4 contracts remain unchanged.
- Kustomize renders, image builds/loads, service rolls out locally, and one synthetic request has a
  correlated trace with no raw request features in spans/logs.

## 8. Decisions and execution record

- User approved Stage 5 implementation on 2026-10-06.
- User selected synthetic fraud-review referral risk with uncertain cases delegated to handler triage;
  this is not fraud detection or claim decisioning.
- User selected hand-authored archetypes plus deterministic generated variants.
- User selected standalone training and serving; Stage 4 agent integration stays in Stage 6.
- User approved XGBoost. Logistic regression and majority baselines remain required comparisons.
- User selected recall-first thresholding and approved a 90% recall gate on the untouched synthetic
  archetype holdout. Precision and resulting review volume must also be reported.
- Stage 4's incomplete domain-source coverage is a known limitation but does not block this independent
  Stage 5 work.
- Execution (2026-10-06): added 44 hand-authored archetypes (20 negative, 24 positive) and 30 seeded
  variants per archetype. The grouped split contains 12/4/4 negative and 14/5/5 positive archetypes in
  train/validation/test respectively (780/270/270 rows). Dataset SHA-256:
  `83d822aa56de3b134553e40466a923beb2b5e50cbdc94aec18fd6fefa8a7d6d2`.
- Execution (2026-10-06): pinned Python 3.12.14, `xgboost-cpu==3.4.1`, and `scikit-learn==1.9.1`.
  XGBoost reached 100% holdout recall and precision; logistic regression reached 95.3% recall and
  68.4% precision; the majority baseline reached 100% recall and 55.6% precision. The 90% recall and
  baseline precision gates passed. These are synthetic-rule reproduction results, not real-world
  predictive performance. Full metrics: [Stage 5 evaluation report](eval/stage5-risk-model-report.md).
- Execution (2026-10-06): artifact `stage5-cfb12f6a9cc1` is packaged in the separate hardened
  inference service. The service rolled out in `ai-platform`; a synthetic near-threshold assessment
  returned `handler_triage_required=true`, and trace `e40a3fd6e0348bea6f1bb5122785dace` was found in
  the OTEL Collector. Agent integration remains deferred to Stage 6.
- Verification (2026-10-06): 35 Stage 5 unit tests and one model-serving integration test pass under
  Python 3.12 with 89% focused coverage. Full repository unit/integration suites report 299 passed,
  2 skipped. Python compilation, touched shell syntax, Kustomize render, promoted-artifact validation,
  image build/load, local rollout, synthetic smoke/trace correlation, and `git diff --check` pass.
