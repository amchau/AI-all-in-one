# Stage 10 - Production Platform Plan

Status: **Draft; awaiting user review and approval**  
Builds on: Stages 1-9; Stage 8 specialist agents remain deferred  
Scope: Enterprise platform hardening, GitOps, infrastructure as code, policy enforcement, secrets, and a second domain

## 1. Goal

Prepare the platform for a production-oriented deployment model while preserving the learning platform's explicit boundaries. Stage 10 must establish a user-approved target environment, security and reliability objectives, infrastructure lifecycle, deployment controls, and a measured path to a second business domain.

This document is a planning draft. It does not authorize infrastructure changes, cloud provisioning, real-data migration, or production deployment.

## 2. Candidate scope

The roadmap identifies these candidate capabilities:

- GitOps-managed Kubernetes application delivery, with Argo CD as the current candidate.
- Reproducible infrastructure provisioning with Terraform.
- Kubernetes policy enforcement with Kyverno.
- Centrally managed secrets with Vault.
- A second domain that demonstrates reuse of platform contracts without assuming Stage 8 agent decomposition.

The candidates are not final architecture choices. Record each selected architecture in an ADR and get user approval before implementation.

## 3. Out of scope until approved

- Choosing a cloud, subscription, region, Kubernetes service, network topology, or production tenancy.
- Provisioning or modifying cloud resources.
- Importing real customer, insurance, banking, energy, or telecom data.
- Treating the local kind Stage 9 stack as a production security, availability, retention, or compliance control.
- Selecting a second domain or inferring specialist agents from Stage 8.
- Applying enforcing policies before their audit results and exemptions are reviewed.

## 4. Planning workstreams

1. **Requirements and target:** identify operators, users, data classification, regulatory obligations, supported domains, target environment, regions, availability goals, RTO/RPO, SLOs, budget, and ownership.
2. **Platform topology:** compare managed Kubernetes and deployment boundaries; define identity, network, ingress/egress, DNS, certificates, observability, backup, and recovery needs.
3. **Infrastructure lifecycle:** define Terraform module boundaries, state backend and access, bootstrap sequence, drift handling, import/migration strategy, and destroy protections.
4. **Application delivery:** define GitOps repository boundaries, environment promotion, secret references, image provenance, rollout/rollback, drift remediation, and break-glass operations.
5. **Policy and supply chain:** inventory workloads and cluster permissions; introduce Kyverno in audit mode first; define policy tests, exceptions, ownership, and the gate for enforcement.
6. **Secrets and identity:** decide Vault deployment or managed service, workload identity integration, secret rotation, recovery, audit, and migration from Kubernetes Secrets. Never copy current synthetic credentials into production.
7. **Domain reuse:** select a second domain with the user, identify shared versus domain-specific API/data/evaluation contracts, and define a representative vertical slice. Keep Stage 8 specialist behavior out of scope unless separately requested and planned.
8. **Stage 9 transition:** decide which telemetry, retention, dashboards, feedback, and evaluation contracts carry forward; close the Stage 9 deferred checks separately from production acceptance.

## 5. Decisions requiring ADRs

- Cloud and Kubernetes target, environment separation, region strategy, and network architecture.
- Terraform state backend, module boundaries, ownership, and bootstrap lifecycle.
- GitOps controller, repository model, promotion strategy, and break-glass process.
- Kyverno policy set, audit-to-enforce criteria, exception process, and policy ownership.
- Vault or managed secret service, identity/authentication mechanism, recovery, and rotation.
- Production observability backend, telemetry data classification, sampling, access, and retention.
- Second domain, its user journey, data boundary, success metrics, and evaluation methodology.

No decision is made in this draft.

## 6. Acceptance gates

- User-approved requirements and target architecture with threat model and data classification.
- Accepted ADRs for every listed platform decision before implementation.
- Infrastructure plan reviewed before apply; protected state, least-privilege identities, and safe bootstrap/recovery tested.
- GitOps promotion, rollback, drift detection, and break-glass paths tested in a non-production environment.
- Kyverno policy tests pass in audit mode before any enforcing rollout; exceptions are explicit, owned, and expiring.
- Secret rotation and recovery are tested without exposing secret values or copying lab secrets.
- Backup/restore, availability, SLO, RTO/RPO, and resource/cost objectives are measured against the approved workload.
- A user-selected second-domain slice passes its own functional, privacy, and evaluation gates without changing the insurance domain's behavior.
- Documentation distinguishes verified production controls from local synthetic Stage 9 capabilities; no production-readiness claim precedes the gates.

## 7. Stage 9 carryovers

The following are deferred from Stage 9 and do not block closure of its approved local synthetic scope, but must be resolved before relying on those controls for production:

- Confirm feedback-note absence from logs, spans, metrics, and dashboards using the configured credential.
- Confirm 30-day cleanup behavior with an accelerated test clock or controlled database fixture.
- Decide the aggregate-feedback suppression policy before enabling aggregate reads.
- Measure retention under load, physical storage bounds, resource use, and trace/log correlation.
- Resolve the full Python test-suite dependency gap and complete the production threat/privacy review.

## 8. Review requested

Approve, amend, or reject this scope before Stage 10 implementation. In particular, confirm the target environment, operational objectives, second domain, and whether Argo CD, Terraform, Kyverno, and Vault remain the intended candidates.
