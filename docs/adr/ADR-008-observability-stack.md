# ADR-008 - Stage 9 Observability Stack

## Status

Accepted (2026-10-12)

## Context

The local platform currently exports OpenTelemetry traces to a Collector `debug` exporter. Stage 9 calls for Prometheus, Grafana, Loki, and Tempo, plus operational AI visibility and evaluation/feedback views. Stage 8 specialist agents are deferred until requirements exist, so the telemetry model must not couple to a particular agent decomposition.

The accepted scope is local synthetic use, OpenTelemetry-based collection, local port-forward access, offline evaluation views, and runtime feedback with a 500-character optional note, 30-day retention, optional workflow UUID or trace ID linkage, and no reviewer identity.

## Decision Drivers

- Fit the existing kind + Podman and Kustomize deployment.
- Preserve existing OTLP traces and trace IDs.
- Keep sensitive narratives, evidence, feedback notes, and identifiers out of telemetry labels/spans/logs and dashboards.
- Bound local CPU, memory, storage, and retention.
- Keep application/agent instrumentation generic for possible Stage 8 work.

## Options

| Concern | Option A | Option B | Recommendation |
|---|---|---|---|
| Backend packaging | Direct pinned Kustomize manifests | Helm charts vendored/pinned and rendered by Kustomize | Direct manifests for a small local footprint, if backend config remains maintainable; otherwise pin charts rather than install imperatively |
| Kubernetes logs | OTel Collector Contrib DaemonSet `filelog` receiver | Separate Fluent Bit agent | OTel agent to central OTel gateway, matching the selected OTel pipeline; requires node log mounts and loop prevention |
| Metrics path | App OTLP metrics to Collector Prometheus exporter, scraped by Prometheus | Prometheus exporter endpoint in every app | Collector exporter to centralize configuration and keep app transport OTLP |
| Feedback persistence | Isolated Postgres schema and least-privilege role | In-memory/local file storage | Postgres, reusing platform operations while isolating credentials and schema |
| Dashboard access | Cluster-internal + port-forward | NodePort/Ingress | Cluster-internal + port-forward; no public exposure |

## Decision

Use native Kustomize manifests: pinned backend resources; an OTel Contrib node agent with CRI log parsing forwarding to the existing OTel Collector gateway; OTLP app metrics translated by the Collector's Prometheus exporter; isolated Postgres feedback persistence; and Grafana reachable only through port-forward.

Use Prometheus `v3.15.0`, Grafana `13.2.3`, Loki `3.7.8`, Tempo `3.1.0`, and core/Contrib OpenTelemetry Collector `0.162.0`. Use PVC/retention bounds of Prometheus 2 GiB/3 days, Loki 1 GiB/3 days, and Tempo 1 GiB/24 hours; Grafana state is ephemeral.

Run Tempo in monolithic mode (`-target=all`) with local storage. This local single-process mode accepts OTLP directly and does not require Kafka; the distributed architecture does require a Kafka-compatible queue.

Use low-cardinality operational metrics and versioned offline evaluation records. Keep human feedback distinct from workflow dispositions and model outputs. Ratings are `useful`, `needs_review`, or `unable_to_assess`; optional reason tags are `grounding`, `completeness`, `relevance`, `safety`, and `other`. Do not store reviewer identity. Retain feedback for 30 days and cap optional notes at 500 characters. Store at most one workflow UUID or trace ID reference per feedback record. Never export note text or identifiers to telemetry or dashboards.

Resource requests/limits and the feedback schema/role/secret provisioner must be recorded and tested before deployment. The feedback store uses a dedicated schema, role, and Secret, with no workflow-state mutation or reviewer identity.

## Consequences

Positive:

- Reuses existing OpenTelemetry instrumentation and local Postgres operations.
- Keeps future specialist agent metrics extensible without defining Stage 8 behavior now.
- Separates operational health, offline evaluation, and human feedback.

Tradeoffs:

- The local observability stack increases host CPU, memory, and disk use.
- Kubernetes log collection needs a node-level agent and read-only access to container log paths.
- Feedback adds a new API, UI control, schema, isolated credential, and data-retention obligation.
- Local port-forward and synthetic-only use do not establish production access controls or readiness.

## Validation

- Verify Kustomize render, pod security contexts, resources, PVC bounds, and retention.
- Confirm Prometheus targets/metrics, Tempo trace lookup, Loki log query, and Grafana provisioning.
- Test feedback schema/role privileges, bounds, 30-day deletion, and UI/API errors.
- Run a unique synthetic note canary and verify it is absent from logs, traces, metrics, and dashboards.
- Record resource use and list all measurement/quality limitations.