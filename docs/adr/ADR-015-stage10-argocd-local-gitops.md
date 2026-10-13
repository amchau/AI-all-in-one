# ADR-015 - Stage 10 Argo CD Local GitOps

## Status

Accepted 2026-10-12 for the local canary design. User authorized experimental Argo CD v3.5.5 installation on kind Kubernetes v1.37 on 2026-10-13 despite the documented compatibility gap. Canary configuration/sync and workload ownership changes remain gated as described below.

## Context

Stage 10 is approved for local-only reference-platform work. Argo CD is an intended component, but the repository currently applies its Kustomize base through `scripts/deploy-stage1.sh`. That script also provisions Secrets, deletes and reapplies the RAG ingestion Job, and restarts Deployments. The base includes persistent volume claims and stateful services. Moving the whole base under a second reconciler without a deliberate cutover could cause conflicting writes, unwanted Job behavior, or data deletion.

The current kind API reports Kubernetes v1.37. The current Argo CD stable installation documentation lists Argo CD 3.5 as tested through Kubernetes v1.36. The user accepted this one-version gap for a local experiment only; installation is not evidence of compatibility or production readiness.

The repository builds and loads local images separately (`kind load`); Argo CD reconciles manifests but does not build images. Git desired state must be committed and available at a stable remote revision. The current local worktree has uncommitted changes and is not a valid GitOps source revision.

## Decision Drivers

- Demonstrate GitOps safely on kind without changing ownership of existing services.
- Keep the current Kustomize base and `deploy-stage1.sh` behavior intact during the prototype.
- Avoid pruning PVCs, namespaces, operational Jobs, or resources managed by other tools.
- Make rollback and break-glass procedures understandable and testable.
- Keep access local-only and avoid committing Git credentials or application secrets.
- Avoid claims of production compatibility, availability, or security based on kind.

## Options

| Criterion | Same-repo isolated canary (recommended) | Adopt current base immediately | Separate GitOps repository |
|---|---|---|---|
| Initial blast radius | One stateless canary in a pre-created namespace | All current platform resources, including PVCs and Jobs | One canary, but requires cross-repository wiring |
| Desired-state duplication | Adds a dedicated local canary path; leaves base canonical | Minimal duplication, but ownership overlaps with existing deploy script | Workload manifests or references cross repository boundaries |
| Rollback | Revert a committed Git change and manually sync | Requires coordinating script and Argo ownership, stateful rollback limits remain | Similar to canary, with additional repository promotion/credential handling |
| Secrets and credentials | Read-only Git credential is supplied outside Git if private source requires it; app Secrets stay external | Existing script provisions Secrets separately, creating competing responsibilities | Adds another repository credential and access-control boundary |
| Operational complexity | Low; manual sync and no pruning initially | High-risk transition and broad reconciliation policy | Higher repository and promotion overhead for a local prototype |
| Recommendation | Recommended for the first local proof | Defer until a separately reviewed cutover | Reconsider when multiple environments or teams require independent ownership |

## Decision

Propose the following local-only GitOps model:

1. **Source layout:** keep configuration in this repository. Add a dedicated kind canary path under `infrastructure/argocd/` or a small dedicated Kustomize overlay that references repository-owned manifests. Keep `infrastructure/kubernetes/base/` canonical and unchanged for the canary. Sync only committed, pushed revisions; do not use the developer's working tree as the desired-state source.
2. **Bootstrap and compatibility:** pin Argo CD v3.5.5 and its manifests. Bootstrap Argo CD separately from the application it manages; do not self-manage the Argo CD installation in this first slice. The v3.5.5 installation on Kubernetes v1.37 is an explicitly accepted local experiment outside the tested matrix.
3. **Permissions:** prefer namespace-scoped deployment permissions for a pre-created canary namespace. Restrict the Argo CD Project to the repository, canary path, destination cluster, namespace, and required namespaced kinds. Do not grant the canary Application permission to create cluster-scoped resources or manage the `ai-platform` namespace.
4. **Sync policy:** require manual sync. Keep automated sync and self-heal disabled initially. Keep pruning disabled, `allowEmpty` unset/false, and omit the cascading resource finalizer from the canary Application. Review diffs before each sync.
5. **Canary scope:** use one stateless workload with a pinned image; ensure local images are loaded to kind nodes before syncing. Argo CD does not build/load images. Never use a floating image tag. Do not include credentials, PVCs, data services, or the ingestion Job.
6. **Rollback:** use a Git revert of the last committed canary change followed by manual sync. Verify rollback with a reversible stateless field change. Do not rely on Argo CD rollback as the durable source-of-truth operation. Do not claim that a manifest rollback reverses data changes.
7. **Break-glass:** with manual sync there is no automatic reconciliation to pause. Make urgent direct changes only as needed, record them, commit the durable correction, review the diff, then manually sync. Git access credentials, if needed for a private source, are supplied as a read-only Kubernetes Secret outside Git.
8. **Workload adoption:** do not adopt `ai-platform` workloads in this ADR. Before any later adoption, define an explicit handoff so `scripts/deploy-stage1.sh` no longer applies Argo-owned workload manifests. Preserve its secret provisioning and operational-job duties only through a reviewed split. Explicitly exclude PVCs and `rag-ingest-job` until their lifecycle is separately designed.

## Alternatives Considered

- **Immediate full-base adoption:** rejected for the first slice because `deploy-stage1.sh` and Argo CD would both manage resources, while pruning or Job reconciliation could affect state or operations.
- **Automated sync/self-heal from the start:** deferred. It reduces manual deployment steps, but can overwrite direct changes and the official documentation notes that rollback is unavailable while automated sync is enabled. First prove manual sync, review, and Git-revert behavior.
- **Automatic pruning:** deferred. Pruning is a deletion operation; the current base contains PVCs and Jobs. Keep it disabled until each resource class has reviewed deletion semantics and ownership.
- **Separate GitOps repository:** deferred. It may fit later environment promotion or team separation, but adds another credential and source boundary without current multi-environment requirements.
- **App-of-apps bootstrap:** deferred. A single canary does not need another controller ownership layer, and cascading deletion behavior increases the initial failure surface.

## Validation

After this ADR is accepted and Kubernetes compatibility is resolved:

- Render and validate the canary Kustomize path locally; confirm it contains no Secret values, PVCs, namespace creation, or non-canary resources.
- Verify Argo CD version compatibility against the chosen Kubernetes version before install; pin the Argo CD image/manifests and record resource requests/limits.
- Verify the Argo Project cannot sync outside the approved repository path, destination namespace, and allowed resource kinds.
- Confirm initial sync is manual and Application configuration has automated sync, self-heal, prune, `allowEmpty`, and cascading finalization disabled.
- Sync a canary change, introduce drift, inspect the diff, manually resync, and verify the desired state is restored.
- Revert a committed stateless change and manually sync; verify rollback and confirm no data-bearing resources are managed.
- Delete the canary Application non-cascading and verify the expected orphan/cleanup behavior before considering later adoption.
- Confirm no Argo CD Service is exposed by NodePort/Ingress and access is through local port-forward only.
- The v3.5.5 namespace-scoped install was rendered, server-side dry-run validated, applied with server-side ownership, and verified Ready on kind Kubernetes v1.37. Services are ClusterIP and API `/healthz` returned HTTP 200 over a stopped localhost-only port-forward.
- Canary registration/sync remains unverified. The origin is private and requires a deliberately provided read-only Git credential; no personal SSH key or secret was copied to Argo CD.
- Record exact image/version tags, resource use where measurable, and limitations. Do not claim production readiness.

## Consequences

Positive:

- Establishes a reversible GitOps proof without changing ownership of the existing platform.
- Makes repo source, sync, deletion, rollback, and emergency correction explicit.
- Keeps build/image loading and manifest reconciliation as separate responsibilities.

Trade-offs and deferred work:

- Manual sync is less automated and requires a committed remote revision.
- A canary proves the GitOps loop, not a safe migration of the current platform.
- Local registry/image distribution, multiple environments, promotion, automated sync, pruning, workload adoption, and production access control remain future decisions.
- Argo CD controller compatibility with Kubernetes v1.37 is unverified; the user authorized this local experiment despite the version gap.
- Canary sync remains pending a committed/pushed local source revision and an approved read-only credential for the private repository.
