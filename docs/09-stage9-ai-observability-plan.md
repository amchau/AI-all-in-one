# Stage 9 - AI Observability and Control Tower

Status: **Done for the approved local synthetic scope; follow-up verification deferred**  
Builds on: OpenTelemetry tracing, Stage 2-7 RAG, claims, risk, and workflow services  
Stage 8: **Deferred until concrete requirements are available**

## 1. Goal

Add a local control tower for service health, AI operational signals, traces, logs, offline evaluation results, and reviewer feedback. The stack is for learning and local synthetic data only; it is not a production observability or real-data security claim.

Stage 8 specialist agents are not part of this stage. Telemetry and evaluation contracts must remain generic enough for future agent roles, orchestration spans, and evaluation runs to be added without redesigning the backends.

## 2. Approved scope

- Deploy Prometheus, Grafana, Loki, and Tempo in the existing local kind cluster with pinned images, bounded resources, and bounded storage/retention.
- Extend the current OpenTelemetry Collector pipeline for OTLP traces and metrics. Collect Kubernetes container logs with an OpenTelemetry node agent and forward them to Loki through the collector gateway.
- Expose a small, low-cardinality set of operational metrics for API, model, retrieval, risk, and workflow paths.
- Display existing offline evaluation results as evaluation data, distinct from service health and from live reviewer feedback. Do not add live model-as-judge scoring.
- Add a structured reviewer-feedback signal to the claims review experience. Permit an optional note up to 500 characters; retain for 30 days; link only to a workflow UUID or trace ID; store no reviewer identity. Keep feedback separate from Stage 7 workflow dispositions.
- Provision Grafana dashboards and data sources from version-controlled configuration.
- Keep all services cluster-internal. Use local port-forward only; no public ingress, NodePort, production authentication claim, or real claims data.
- Update README, roadmap, and AGENTS status with verified results and limitations.

## 3. Out of scope

- Implementing Stage 8 specialists, deciding their decomposition, or evaluating multi-agent versus single-agent behavior.
- Production deployment, public exposure, production retention/security guarantees, or real customer/claims data.
- Claim decisions, fraud determinations, or workflow dispositions based on dashboards or feedback.
- Exporting reviewer notes, claim narratives, evidence, claim/workflow IDs, or arbitrary user-provided values as telemetry labels or span attributes.
- Automated quality scoring by another model.

## 4. Proposed architecture

ADR-008 records the pending deployment and storage details. Current direction:

- Prometheus scrapes the OpenTelemetry Collector's Prometheus metrics exporter.
- Tempo receives OTLP traces; Loki receives structured Kubernetes container logs.
- An OpenTelemetry Collector agent runs per kind node with read-only container-log mounts and CRI parsing. It forwards logs to the existing central Collector gateway, which exports them to Loki. Exclude collector/backend logs or otherwise prevent self-ingestion loops.
- The central Collector remains the OTLP gateway for application traces and metrics. Existing trace export and trace IDs remain compatible.
- Grafana is the only UI and is reachable only through `kubectl port-forward`.
- Feedback is written to a dedicated Postgres schema and a distinct least-privilege role/Secret. Do not reuse `claims_workflow`, `rag_query`, or bootstrap credentials. The feedback store is not an audit log and does not change workflow state.
- Feedback records contain a validated rating, an optional bounded note, one optional workflow UUID or trace ID, and timestamps. Reviewer identity is not collected. Dashboards show aggregates and fixed-category summaries only, never raw notes.
- Set explicit local resource requests/limits, PVC size, and retention per backend before rollout. Values must be validated against the available kind/Podman host capacity.

## 5. Implementation slices

1. **Architecture and contracts:** complete ADR-008 with pinned versions, Kustomize packaging, telemetry routing, resource/PVC/retention limits, and feedback rating values. Add generic low-cardinality service/operation/agent-role dimensions; do not encode Stage 8 assumptions.
2. **Metrics and collector:** add operational API/model/RAG/risk/workflow instruments, an OTLP metrics exporter, collector metrics pipeline/exporter, and Prometheus scrape configuration. Cover request counts, latency, errors, model usage where provided by LiteLLM, and workflow outcomes. Never use high-cardinality or sensitive attributes as metric labels.
3. **Backends and log collection:** add hardened, pinned Prometheus, Grafana, Loki, and Tempo resources; storage/retention; collector gateway configuration; and a node-level OTel log agent. Register all resources in Kustomize. Add local-only port-forward instructions.
4. **Offline evaluation views:** define a stable evaluation result import/record format and load checked-in evaluation artifacts with suite/run identifiers and measured dimensions. Clearly mark sample size and limits; do not imply that trace presence or source-ID validity proves semantic quality.
5. **Reviewer feedback:** define controlled rating values, validate note length and identifiers, add a dedicated Postgres schema/role/secret/provisioner, feedback API, and UI control. Enforce 30-day retention. Exclude notes and references from logs, traces, and metrics; use a synthetic canary to verify.
6. **Dashboards:** provision versioned dashboards for service health, AI operational signals, trace/log correlation, workflow outcomes, offline evaluations, and aggregated reviewer feedback.
7. **Validation and handoff:** run unit/integration/UI tests; Python/shell/Kustomize checks; build/load/rollout; verify scrape targets, metrics, trace lookup, log ingestion, dashboards, port-forward boundary, retention, resource usage, and privacy canary. Update docs only with measured outcomes.

## 6. Acceptance criteria

- All four backends are pinned, hardened, resource-bounded, and reachable only inside the local cluster; Grafana works through port-forward.
- Prometheus reports healthy targets and receives the approved API/AI operational metrics with bounded cardinality.
- A known application trace is retrievable in Tempo, and a known synthetic application log is retrievable in Loki with trace correlation where available.
- Existing API trace export remains functional; telemetry excludes narratives, full evidence, reviewer notes, secrets, and claim/workflow IDs.
- Offline evaluation results are displayed as distinct, versioned runs with their limitations visible; live model-as-judge scoring is absent.
- Reviewer feedback validates its rating and optional 500-character note, accepts no reviewer identity, and links only to an optional workflow UUID or trace ID. It is separate from Stage 7 dispositions and retained no longer than 30 days.
- A privacy canary verifies feedback notes remain only in the approved Postgres store and never appear in application/collector logs, spans, metric labels, or dashboards.
- Unit/integration/UI checks cover metric contracts, feedback validation/storage/retention, telemetry privacy, and failure behavior.
- Kustomize, Python compilation, and shell syntax checks pass; local deployment and configured storage/retention are verified.
- Documentation states measured resource use, evaluation limits, local-only boundary, and Stage 8 extension points without production-readiness claims.

## 7. Verification commands

```bash
python3 -m pytest -q tests/unit tests/integration
npm --prefix apps/frontend run test:coverage
npm --prefix apps/frontend run test:e2e
bash -n scripts/*.sh
python3 -m py_compile apps/ai-api/main.py apps/ai-api/feedback_store.py
kubectl kustomize infrastructure/kubernetes/base >/dev/null
git diff --check
```

## 8. Open ADR details

- Kustomize resource packaging versus vendored, pinned Helm charts.
- Dedicated Postgres feedback schema/role/secret provisioning and cleanup behavior.
- Safe dashboard aggregation thresholds.

Confirmed on 2026-10-12:

- Pin Prometheus `v3.15.0`, Grafana `13.2.3`, Loki `3.7.8`, Tempo `3.1.0`, and both core and Contrib OpenTelemetry Collector images to `0.162.0`.
- Prometheus: 2 GiB PVC and 3-day retention. Loki: 1 GiB PVC and 3-day retention. Tempo: 1 GiB PVC and 24-hour retention. Grafana state is ephemeral.
- Feedback ratings: `useful`, `needs_review`, or `unable_to_assess`; optional reason tags: `grounding`, `completeness`, `relevance`, `safety`, or `other`; note remains optional and capped at 500 characters.
- Feedback retains for 30 days, links to at most one workflow UUID or trace ID, and stores no reviewer identity.
- Postgres feedback schema, dedicated role/secret provisioning, and cleanup behavior.

These are Stage 9 implementation details, not Stage 8 requirements. Implement only the accepted ADR-008 choices; defer unresolved aggregate suppression policy.

## 9. Implementation record (2026-10-12)

- Added API request count and duration metrics with normalized methods, route templates, and bounded status codes. Metrics export is enabled by the Kubernetes deployment; host tests do not attempt to reach cluster DNS.
- Added a Prometheus-format endpoint to the existing Collector while preserving the trace `debug` exporter. A live scrape returned API request count/duration series with method, status, and route labels.
- A synthetic missing-workflow request returned the existing generic 404. Its UUID was absent from metrics and Collector output; traces retained the route template. Fixed the underlying leakage by sanitizing all FastAPI URL/path span attributes, removing workflow UUID span attributes, and making `WorkflowNotFound` messages generic.
- API image `localhost/ai-api:stage9.3` was built, loaded, and rolled out to kind. Outbound HTTPX spans redact claim/policy/customer/workflow path identifiers and query strings; six model-free synthetic requests verified templated URLs in the Collector. Suppressed HTTPX INFO URL logs and removed the remaining worker workflow-ID span attribute and warning-log values; a regression test reproduced the worker leak before the fix.
- Core Collector and Contrib node agent `0.162.0`, Prometheus `v3.15.0`, and Loki `3.7.8` are deployed. Prometheus reports its Collector target `up`; a subsequent query returned 185 API metric series, including histogram buckets.
- Loki accepted a benign OTLP log through the gateway, and an API stdout canary traversed CRI file parsing, the node agent, gateway, and Loki. Only `service_name` is indexed; Kubernetes pod identifiers remain structured metadata. The synthetic missing-workflow UUID was absent from collected logs. This is not a general privacy or trace/log-correlation claim.
- Log collection is allowlisted to ai-api, claims-service, and claims-risk-service. LiteLLM, frontend, infrastructure, and observability logs are excluded. The non-root node agent uses supplemental group 0 to read kind's root-group `0640` CRI files through a read-only mount. It starts at the current tail and does not persist offsets across restarts; downtime can lose logs.
- Prometheus requests a 2 GiB PVC with 3-day retention and a 1536 MB TSDB block cap; Loki requests 1 GiB with 72-hour compactor retention. Kind local-path PVC capacity is not a hard filesystem quota, and expiry/physical disk bounds have not been verified under load. Both backends stop the old replica before starting a replacement to avoid shared-directory locks. Collector/agent ConfigMap changes require explicit restarts.
- Focused Python regression suite: 78 passed. Kustomize rendering, `git diff --check`, and focused editor diagnostics passed. Actual pod resource use is unmeasured because the cluster Metrics API is unavailable.
- Full Python suite collection is blocked in the current `.venv` because `xgboost` and `scikit-learn` are not installed. No frontend files changed.

Stage 9 is closed for the approved local synthetic scope. The `stage9.4` API, `stage9.2` frontend, Tempo, Grafana, Prometheus, Loki, Collector, and node log agent are deployed and verified as noted below. Backend Services are ClusterIP and access is local port-forward only. Feedback note privacy/30-day cleanup confirmation is deferred; aggregate-feedback suppression policy is also deferred and the aggregate endpoint stays disabled.

## Follow-up implementation record (2026-10-12)

- Tempo `3.1.0` runs in monolithic mode with local storage and `backend_worker.compaction.block_retention: 24h`. The Collector exports traces to Tempo while retaining its debug exporter. An API health trace was found through Tempo service search; trace-by-ID lookup remains to be verified.
- Grafana `13.2.3` is ready with provisioned Prometheus, Loki, and Tempo data sources and a Stage 9 overview dashboard. Initial panels returned no data because Grafana's startup plugin preinstaller attempted to replace bundled datasources, then failed against the required read-only root filesystem. Set `GF_PLUGINS_PREINSTALL_DISABLED=true`; built-in Prometheus/Loki/Tempo plugins now register, all datasource health checks return 200, and the dashboard request-rate query returns samples through Grafana's proxy.
- API `stage9.4` source includes a span processor that maps only fixed operations/outcomes/known models to AI operation count/duration and actual token counters. Metrics exemplars are disabled. Focused AI metrics/privacy tests passed 107 tests; workflow, feedback contracts, and API regression tests passed 143 tests before final Stage 9.4 documentation changes.
- Removed RAG candidate/reranked/returned document IDs and ingestion `rag.doc_id` from spans. The focused retrieval span regression passed in dense, hybrid, and hybrid-rerank modes.
- Reviewer feedback API/store and tests enforce controlled ratings, optional fixed reason tags, 500-character note maximum, one optional workflow UUID or trace ID, no identity, sanitized receipt/error, and 30-day deletion. The dedicated schema/role and Secret exist in kind; the `claims_feedback` credential was verified against the feedback table and API `stage9.4` is deployed. Per user direction, defer the synthetic note privacy canary and live 30-day cleanup confirmation. Aggregate feedback remains disabled until its suppression policy is decided.
- Frontend adds reviewer feedback to the awaiting-review panel and a separate offline-evaluation view sourced from aggregate Stage 2 and Stage 5 results. It excludes raw cases and all claim/chunk/trace identifiers. Focused frontend suite: 30 passed; production build passed with existing dependency annotation warnings.
- API `stage9.4` and frontend `stage9.2` are built, loaded, and rolled out to the explicitly selected kind cluster; API health is 200. Tempo trace-by-ID returned 200. Grafana's bundled datasource plugins now remain registered with `GF_PLUGINS_PREINSTALL_DISABLED=true`; all three datasource health checks and dashboard queries were verified, including a zero-valued 5xx result. Prometheus HTTP/AI panel queries return samples. The focused Python suite passed 197 tests; frontend coverage passed 32 tests at 92.96% lines, and desktop/mobile Playwright passed 10 tests. User deferred the feedback note privacy canary and 30-day cleanup confirmation. Full Python suite collection remains blocked by missing `xgboost`/`scikit-learn`; physical storage/retention under load, log/trace correlation, and resource measurement remain unverified. The host's active kubectl context is an AKS cluster and was not changed.