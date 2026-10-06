# ADR-012 - Stage 5 Claims Risk Model and Serving Boundary

## Status

Accepted (user approval: 2026-10-06)

## Context

Stage 5 requires a local synthetic tabular model to estimate whether a claim should be referred for
human fraud review. The prediction is advisory and is not a fraud determination. The existing repo
runs Python 3.12 and uses local kind + Podman, FastAPI, and OTEL. Stage 4 has only two synthetic
fixtures and no labels, so Stage 5 must create its own synthetic training/evaluation data. The model
must remain separate from the Stage 4 agent until Stage 6.

The model family and deployment boundary affect package compatibility, reproducibility, evaluation,
latency, and artifact governance. Inference must return a review-priority band and handler-triage
status without exposing a numerical probability or taking a claim action.

## Options

| Criterion | XGBoost | LightGBM | Logistic regression only |
|-----------|---------|----------|--------------------------|
| Scale | Handles this tabular prototype and larger datasets | Efficient on large tabular datasets | Suitable baseline and small datasets; limited nonlinear interactions |
| Latency | CPU histogram training and inference adequate at current scale | Often faster for larger datasets | Fastest and simplest at this scale |
| Features / filtering | Mature sklearn estimator API; nonlinear feature interactions | Mature tabular learner; similar classification workflow | Transparent linear decision boundary and probability API |
| Operational burden (kind/laptop) | One pinned native Python dependency; verify wheel/runtime compatibility | One pinned native dependency; similar compatibility check | Lowest dependency burden |
| Kubernetes support | CPU-only inference in a separate Python service | CPU-only inference in a separate Python service | CPU-only inference in a separate Python service |
| Cost | Open source; no extra runtime service cost | Open source; no extra runtime service cost | Open source; no extra runtime service cost |
| Developer experience | Broad examples and common Python/sklearn integration | Strong Python API, with no measured need for its speed here | Simple to inspect, but may not model interactions in synthetic rules |
| Cloud portability (Azure/AWS/GCP) | Portable Python artifact and container | Portable Python artifact and container | Portable Python artifact and container |

Training and serving boundary options:

| Criterion | Separate offline training + inference API | Train inside existing `ai-api` | Inference inside Stage 4 agent |
|-----------|-------------------------------------------|----------------------------|--------------------------------|
| Isolation | Immutable artifact and independent API contract | Couples training/model dependencies to RAG and agent API | Couples risk scoring to Stage 4 tool workflow |
| Rollout | Independently pinned and deployed service | Shared API rollout and resource profile | Agent release required for model changes |
| Stage scope | Matches Stage 5 standalone train-and-serve choice | Expands Stage 5 changes into existing APIs | Pulls Stage 6 integration forward |
| Operational burden | One additional local service | Fewer services, larger shared image | No new service, but higher coupling |

## Decision

Use the CPU-only `xgboost-cpu` distribution for the Stage 5 candidate model, with logistic regression and a majority-class baseline
for comparison. XGBoost's established Python/scikit-learn estimator workflow and adequate CPU behavior
fit this small prototype; LightGBM's speed advantage is not a current requirement. The model must
beat the baselines under the agreed grouped evaluation and meet the 90% synthetic referral-recall
gate before it is described as a validated prioritizer. If it fails, publish the failed result rather
than tune against the holdout.

Keep training and evaluation offline in the `ml/` package. Package a versioned immutable artifact
and matching feature/schema metadata into a separate internal FastAPI inference service. The service
returns only a priority band and explicit handler-triage-required state/reason; it does not return a
probability, determine fraud, decide coverage, recommend claim disposition, or mutate a claim. Keep
Stage 4 agent integration deferred to Stage 6.

Use only synthetic structured inputs; exclude narratives, customer identifiers, and real data. Add
an `ml.*` OTEL span with bounded operational metadata, never raw inputs or labels. Follow Python 3.12,
local Kubernetes, Podman, and container-hardening conventions.

## Validation

- Pin `xgboost-cpu`/scikit-learn versions and verify installation, training, serialization, and inference
  under Python 3.12 before packaging.
- Compare XGBoost, logistic regression, and majority baseline with identical grouped partitions.
- Split by archetype before variants; require disjoint train/validation/test groups and both labels
  in every partition.
- Tune the priority threshold on validation; evaluate the untouched grouped test set once. Require at
  least 90% synthetic referral recall and report precision, confusion counts, review volume, PR-AUC,
  Brier score, and 10-bin expected calibration error. State sample sizes and synthetic-label
  limitations.
- Test artifact/schema mismatch, API validation and triage states, and trace/log privacy.
- Build/load and deploy the hardened internal service locally; smoke-test with synthetic inputs and
  correlate the OTEL trace.
- Execution (2026-10-06): `xgboost-cpu==3.4.1` and `scikit-learn==1.9.1` install/import under
  Python 3.12.14. XGBoost holdout recall/precision were 100%/100%, versus 95.3%/68.4% for logistic
  regression and 100%/55.6% for the majority baseline. Synthetic-label limitations are in the
  [evaluation report](../eval/stage5-risk-model-report.md).
- Verification (2026-10-06): 35 Stage 5 unit tests and one serving integration test pass with 89%
  focused coverage; the full unit/integration suite reports 299 passed and 2 skipped. The hardened
  inference service is deployed locally, and its synthetic smoke trace was correlated in the
  collector. This does not establish real-data readiness.

## Consequences

Positive:
- Keeps training, model artifact, inference, and agent orchestration boundaries explicit.
- The Stage 5 service can be evaluated and rolled back without changing the Stage 4 agent.
- Logistic baseline guards against using a more complex model without measured value.
- Triage behavior and synthetic-only constraints are part of the API contract, not informal guidance.

Negative:
- Adds a service and a native ML dependency to the local cluster.
- Synthetic rule-derived labels test whether the implementation reproduces the rubric, not real fraud.
- Grouped splitting requires enough independent archetypes; generated row count alone is not evidence
  of evaluation strength.
- Not returning probability limits downstream flexibility, but avoids presenting synthetic output as
  a calibrated real-world risk estimate.

Follow-up:
- Revisit model family only if measured baseline comparisons or a changed data scale justify it.
- Integrate with the Stage 4 agent only under the approved Stage 6 plan.
- Any future real-data use requires a separate approved plan, privacy/security review, label-quality
  evidence, and independent evaluation; this ADR grants no such approval.
