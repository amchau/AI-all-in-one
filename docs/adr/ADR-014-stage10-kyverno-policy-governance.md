# ADR-014 - Stage 10 Kyverno Policy Governance

## Status

Accepted 2026-10-12 for offline policy tests and rendered-manifest evaluation only. Controller installation and cluster audit remain deferred.

## Context

Stage 10 has approval for local-only work on the existing kind cluster. Kyverno is an intended component, but no policy set or enforcement behavior has been approved. Current Kubernetes conventions require resource requests/limits and container hardening (`allowPrivilegeEscalation: false`, dropped capabilities, and `runAsNonRoot` where supported). Existing workloads must be inventoried before a policy is adopted; controls that depend on image support or writable paths need explicit exceptions or workload changes.

The goal of the first Kyverno slice is to expose gaps without blocking deployments. Local policy results are not evidence of production security or compliance. Cloud target selection and any production enforcement remain deferred.

The active kind cluster reports Kubernetes v1.37. The current Kyverno release guidance lists tested compatibility through Kubernetes v1.35, so a controller rollout is not authorized on this cluster. Offline fixture and manifest checks use the locally installed Kyverno CLI v1.18.1, and the runner enforces that version. Revisit the controller version matrix before installing Kyverno.

## Decision

Use Kyverno for policy authoring and offline audit evaluation. Pin the local CLI at v1.18.1 for the first test slice. Select and pin a controller/chart version only after its compatibility with the chosen Kubernetes version is confirmed. Integrate installation with the approved GitOps path when that ADR is accepted; until then, do not add Kyverno runtime resources or alter the cluster.

For the first slice:

- Author a small set of validation policies derived from the repository's existing Kubernetes conventions.
- Evaluate policies with both passing and intentionally failing fixtures using the Kyverno CLI test format, then render the current Kustomize base and review findings.
- Use audit/reporting behavior only. Do not add mutate, generate, image verification, or admission-enforcement rules in this slice.
- Record each finding with the affected manifest/workload, severity, owner, remediation or explicit exception, and follow-up. Exceptions must be narrow, reviewed, and documented.
- Keep policy enforcement as a separate future approval after policy results and exceptions are reviewed.

## Options

| Criterion | Kyverno | Gatekeeper | Kubernetes ValidatingAdmissionPolicy |
|---|---|---|---|
| User direction | Explicitly named as intended | Not selected | Not selected |
| Policy model | Kubernetes-native YAML policies and a dedicated CLI/test format | Constraint Templates and Constraints, commonly using Rego | Native admission policy/binding resources using CEL |
| Local audit/testing | Supports policy tests and policy reports; suitable for rendered-manifest and kind evaluation | Supports audit and test workflows, but requires learning Rego and its constraint model | No external policy controller for core validation, but testing/reporting workflow differs and feature coverage depends on Kubernetes version |
| Operational cost | Adds a controller and CRDs; versions and resource use must be bounded | Adds a controller and CRDs; Rego expertise is an added cost | Lowest added runtime footprint for supported validations; does not provide Kyverno's broader policy workflow |
| Recommendation | Preferred for the approved prototype because it matches user intent and offers policy test/report workflows | Viable alternative if Rego is a platform standard | Viable for a smaller native-only policy set; reconsider if minimizing controllers becomes the priority |

## Alternatives considered

- **Gatekeeper:** mature policy-as-code option with Rego and constraint templates. Rejected for this first local slice because Kyverno is already the user-selected candidate and adding Rego would introduce a second policy language without a demonstrated need.
- **ValidatingAdmissionPolicy:** native Kubernetes CEL policies can reduce controller overhead. Not selected for this slice because the user intends Kyverno and the policy testing/reporting and broader policy lifecycle differ. Reconsider if controller footprint becomes the dominant constraint.
- **Immediate enforcement:** rejected because it can block current workloads before audit findings and exceptions are understood, contrary to the approved staged rollout.

## Validation

Offline slice verification:

- Run `bash scripts/test-kyverno-policies.sh` to execute fixture tests and evaluate rendered Kustomize resources using the pinned CLI. The manifest audit uses `--audit-warn`, preserving findings as warnings while allowing actual evaluation errors to fail the command.
- Review every reported finding and exception with an owner. Confirm no policy has enforcement behavior enabled.
- Recheck the official Kyverno/Kubernetes support matrix before a future controller install; test on a supported cluster and confirm a known violation is reported but not rejected.
- Record CLI version, observed local resource use where measurable, and known gaps. Do not claim production readiness.

## Consequences

Positive:

- Policy impact can be measured against current resources before any admission gate is introduced.
- Tests make intended pass/fail behavior reviewable and repeatable.
- Findings and exceptions become owned work rather than silent policy drift.

Trade-offs and deferred work:

- Kyverno adds controller/CRD operational cost to the local cluster.
- Audit reports do not prevent unsafe changes.
- Policy results depend on the pinned Kyverno/Kubernetes versions and must be revalidated after upgrades.
- Production policy ownership, exception expiry workflow, enforcement, cloud-specific controls, and compliance mapping need later decisions.
