---
description: Draft an Architecture Decision Record comparing options for a platform decision.
---

Draft a new ADR in `docs/adr/` using [ADR-000-template.md](../../docs/adr/ADR-000-template.md).

1. Use the next free number from the ADR index in [docs/ROADMAP.md](../../docs/ROADMAP.md).
2. Compare at least 2-3 options against: scale, latency, filtering/features, operational burden
   on kind/laptop, Kubernetes support, cost, developer experience, cloud portability
   (Azure/AWS/GCP equivalents).
3. Recommend one option but set Status to `Proposed`; the user decides.
4. List how the decision will be validated (eval metric, benchmark, or smoke test).
5. Update the ADR index in `docs/ROADMAP.md`.

Decision topic: ${input:topic}
