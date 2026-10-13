# Stage 10 - Production Platform Plan

Status: **Local-only scope approved; ADR-014 and ADR-015 accepted; offline policy tests implemented; Argo CD v3.5.5 experimentally installed on Kubernetes 1.37; canary sync pending**
Builds on: Stages 1-9; Stage 8 specialist agents remain deferred  
Scope: Local reference-platform prototypes for GitOps, policy governance, and secrets; Terraform and second-domain implementation remain gated

## 1. Goal

Establish local, testable platform delivery and governance patterns on the existing kind cluster while preserving the learning platform's explicit boundaries. The production target is deferred. Stage 10 must not present local prototypes as production controls or make cloud-specific infrastructure decisions before the target is selected.

The user approved starting local-only Stage 10 work on 2026-10-12. Argo CD, Terraform, Kyverno, and Vault are intended components, but their implementation details require accepted ADRs. This approval does not authorize cloud provisioning, real-data migration, enforcing policies, or production deployment.

## 2. Problem statement

Stages 1-9 provide a local synthetic-data platform, but do not establish repeatable GitOps delivery, infrastructure lifecycle, cluster policy governance, or centralized secret workflows. Stage 10 should demonstrate these capabilities without treating kind as production, copying lab credentials into a future environment, or assuming Stage 8 specialist-agent behavior. A second domain is desired, but its selection remains open.

## 3. Recommendation

Use kind as a disposable reference environment to prove Argo CD reconciliation and rollback, Kyverno policy testing and audit reporting, and a Vault integration using disposable synthetic secrets. Keep existing kind lifecycle scripts intact until any GitOps ownership change is reviewed. Start with Kyverno audit mode; enforcement requires a later explicit approval after findings and exceptions are reviewed.

Defer cloud-specific Terraform modules and remote state until a production target is selected. Do not add empty Terraform scaffolding. Evaluate a local Terraform experiment only if it manages a real, agreed resource and improves on the existing kind scripts. Define second-domain selection criteria now, but do not implement a domain slice until the user chooses the domain and approves its synthetic data, workflow, contracts, and evaluation.

## 4. Options and trade-offs

1. **Local reference platform (recommended):** exercise Argo CD, Kyverno audit, and Vault integration on kind. This is reversible and within the approved boundary, but does not prove cloud identity, durable secrets recovery, high availability, compliance, remote Terraform state, or production SLOs.
2. **Production-target design with local validation:** select a target and define identity, network, backup, recovery, and operational objectives before building cloud infrastructure. This reduces later rework, but those target decisions are deferred and must not be smuggled into the current implementation.
3. **Production deployment now:** provision a managed platform and deploy workloads. This may validate the end state more directly, but requires cloud, account, region, budget, tenancy, and security approvals. It is not in this Stage 10 authorization.
4. **Terraform now vs later:** a narrow local experiment is possible if it owns a meaningful resource; cloud modules, state backend, bootstrap identities, drift/import, and destroy protection need a selected target. Do not create modules that only look complete.
5. **Second domain now vs selection gate:** banking fraud, energy maintenance, or telecom incidents are candidates. Selecting one without the user would overstep; use synthetic-data availability, a clear workflow, privacy boundaries, measurable evaluation, and shared-contract reuse as selection criteria.
6. **Audit vs enforcement:** audit reveals likely impact without blocking current workloads. Enforcement can prevent unsafe resources, but premature policies or exemptions can break the platform. Keep enforcement gated on reviewed reports and separate approval.
7. **Vault prototype vs production design:** a local synthetic-secret prototype can test integration and rotation mechanics. It cannot prove production authentication, HA, backup, seal/unseal, or recovery; those require a target-specific design.

## 5. Approved local scope

Intended components, with exact configurations still subject to ADR approval:

The roadmap identifies these candidate capabilities:

- GitOps-managed Kubernetes application delivery, with Argo CD as the current candidate.
- Reproducible infrastructure provisioning with Terraform.
- Kubernetes policy enforcement with Kyverno.
- Centrally managed secrets with Vault.
- A second domain that demonstrates reuse of platform contracts without assuming Stage 8 agent decomposition.

Record each implementation architecture in an ADR and get user approval before building that slice. Accepted local Kyverno policy scope: [ADR-014](adr/ADR-014-stage10-kyverno-policy-governance.md). Proposed local Argo CD GitOps model: [ADR-015](adr/ADR-015-stage10-argocd-local-gitops.md).

## 6. Out of scope until separately approved

- Choosing a cloud, subscription, region, Kubernetes service, network topology, or production tenancy.
- Provisioning or modifying cloud resources.
- Importing real customer, insurance, banking, energy, or telecom data.
- Treating the local kind Stage 9 stack as a production security, availability, retention, or compliance control.
- Selecting a second domain or inferring specialist agents from Stage 8.
- Applying enforcing policies before their audit results and exemptions are reviewed.

## 7. Implementation workstreams

1. **Scope baseline:** inventory current manifests, workload identities, secret references, deployment scripts, and security controls without printing secret values. Preserve existing lifecycle scripts until replacement behavior is tested.
2. **ADRs:** propose decisions for Argo CD local source/promotion/rollback, Terraform boundary, Kyverno audit/testing/exception workflow, and Vault synthetic-only prototype. Implement each slice only after its ADR is accepted.
3. **GitOps:** add Argo CD to kind with pinned images and bounded resources; test sync, drift correction, failed rollout, rollback, and break-glass recovery. Keep access cluster-internal/local-only.
4. **Policy governance:** use Kyverno in audit mode; test policies against rendered manifests and inspect reports on kind. Document policy ownership and reviewed exceptions. No admission enforcement in this authorization.
5. **Secrets:** test one narrowly scoped workload integration with disposable synthetic values; verify expected access, denied access, rotation, restart/recovery behavior, and audit without exposing values. Do not migrate existing credentials.
6. **Terraform:** decide whether there is a meaningful local resource to manage. Otherwise defer Terraform implementation until provider/target selection; document target-dependent state and lifecycle needs.
7. **Second domain:** present candidates and criteria for user selection. A domain vertical slice is conditional, not a prerequisite for the local platform slices; do not infer Stage 8 agents.
8. **Handoff:** record measured outcomes, known limitations, and deferred decisions. Keep Stage 9's explicitly deferred privacy/retention checks visible; their prior deferral does not become a production assurance.

## 8. Decisions requiring ADRs

- Cloud and Kubernetes target, environment separation, region strategy, and network architecture.
- Terraform state backend, module boundaries, ownership, and bootstrap lifecycle.
- GitOps controller, repository model, promotion strategy, and break-glass process.
- Kyverno policy set, audit-to-enforce criteria, exception process, and policy ownership.
- Vault or managed secret service, identity/authentication mechanism, recovery, and rotation.
- Production observability backend, telemetry data classification, sampling, access, and retention.
- Second domain, its user journey, data boundary, success metrics, and evaluation methodology.

The component shortlist is user-approved; the implementation choices below remain proposed until their ADRs are accepted. Cloud/production decisions remain deferred.

## 9. Acceptance gates

- Accepted ADR for a slice before implementing that slice; no change to current workload ownership until migration/rollback is tested.
- GitOps reconciliation, intentional drift correction, failed rollout, rollback, and documented break-glass operation pass on kind.
- Kyverno tests cover passing and failing fixtures; audit findings on rendered/current resources are reviewed, categorized, and assigned. No policy is enforced without separate approval.
- Synthetic-only secret integration demonstrates least-privilege access, denial, rotation, recovery/restart, and no value leakage; local Vault limitations are explicit.
- Terraform is either tied to an approved local resource with a useful lifecycle test or clearly deferred; no empty modules or cloud apply.
- Local CPU/memory/storage use is measured where supported, and unmeasured capacity/durability claims are called out.
- A second-domain slice passes its own functional, privacy, and evaluation gates only if selected and separately scoped; insurance behavior remains unchanged.
- Documentation clearly distinguishes local prototypes from production controls. No production-readiness claim is made.

## 10. Clarifications and standing decisions

- Local kind implementation first; production target selection and deployment later.
- Argo CD, Terraform, Kyverno, and Vault are intended components; ADRs still govern exact configuration and build boundaries.
- Second-domain selection is deferred. Candidate options are banking fraud, energy maintenance, and telecom incidents.
- Stage 8 specialist agents remain deferred.
- Python files created or modified going forward should include a concise module docstring that explains the file's purpose. Add comments/docstrings for meaningful responsibilities or non-obvious logic; avoid line-by-line narration.

## 11. Stage 9 carryovers

The following are deferred from Stage 9 and do not block closure of its approved local synthetic scope, but must be resolved before relying on those controls for production:

- Confirm feedback-note absence from logs, spans, metrics, and dashboards using the configured credential.
- Confirm 30-day cleanup behavior with an accelerated test clock or controlled database fixture.
- Decide the aggregate-feedback suppression policy before enabling aggregate reads.
- Measure retention under load, physical storage bounds, resource use, and trace/log correlation.
- Resolve the full Python test-suite dependency gap and complete the production threat/privacy review.

## 12. Implementation status

Approved to begin local-only work on 2026-10-12. ADR-014 is accepted for offline fixture testing and rendered-manifest evaluation. Two audit-only policies and the local runner are implemented; the Kyverno controller remains deferred because Kubernetes v1.37 exceeds its documented tested range through v1.35. ADR-015 is accepted for the local Argo CD canary design. At the user's direction, Argo CD v3.5.5 was installed experimentally into `argocd` on kind Kubernetes v1.37 on 2026-10-13, despite Argo CD 3.5's documented tested range ending at v1.36. All Argo deployments, the controller StatefulSet, CRDs, and the API health endpoint are verified. No canary Application is registered or synced yet: the same-repository configuration is uncommitted, the origin is private, and no read-only repository credential has been supplied to Argo. Production target, Terraform state/backend, Vault production operation, policy enforcement, and second domain remain open/deferred.

## 13. First slice implementation record (2026-10-12)

- Added offline Kyverno policies for CPU/memory requests and limits, disabled privilege escalation, dropped capabilities, and non-root execution. Policies use audit behavior; they are not installed in the cluster.
- Added compliant/noncompliant Pod fixtures and `scripts/test-kyverno-policies.sh`, pinned to the locally validated Kyverno CLI v1.18.1. The runner performs fixture tests and evaluates the Kustomize-rendered base without applying resources.
- Fixture suite: 8 expected results passed. Rendered base: 47 resources evaluated, 52 policy passes and 12 audit warnings. Resource requests/limits had no findings. Non-root was missing from claims-frontend, Grafana, Loki, Prometheus, Tempo, and the OTel log agent; Postgres and Qdrant were missing all three hardening fields.
- This is an offline manifest evaluation, not a cluster PolicyReport or production security claim. Active kind Kubernetes v1.37 is outside the currently documented Kyverno tested support range (through v1.35); controller installation and live audit remain deferred pending a compatible cluster/version decision.

## 14. Argo CD install record (2026-10-13)

- Installed the upstream namespace-scoped Argo CD v3.5.5 bundle and CRDs through the pinned `infrastructure/argocd/bootstrap` Kustomize entry point. Added bounded CPU/memory for all controller containers and init containers; patched explicit non-root on upstream containers that omitted it. No ingress, NodePort, LoadBalancer, Application, or Git repository credential was created.
- Server-side dry-run passed on Kubernetes v1.37. The first client-side apply failed on a CRD exceeding the 256 KiB last-applied-annotation limit after partially creating resources; reran using server-side apply with a one-time field ownership transfer for resources created by that attempt.
- All six Argo CD Deployments and the application-controller StatefulSet became Ready. Applications, ApplicationSets, and AppProjects CRDs are registered. All Services are ClusterIP; upstream NetworkPolicies are present. A temporary localhost-only port-forward returned HTTP 200 from `/healthz` and was stopped.
- This remains an unsupported/unverified local experiment: Argo CD 3.5's documented tested Kubernetes versions stop at v1.36, while kind is v1.37. No production-readiness claim. Canary sync waits for these local changes to be committed/pushed and for an intentionally supplied read-only credential to the private origin; do not copy a personal SSH key or print credentials.
