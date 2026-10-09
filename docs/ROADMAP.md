# Roadmap - Enterprise AI Decision & Operations Platform

One evolving platform, built in 10 stages. First domain: insurance claims. Later reused
for banking (fraud), energy (predictive maintenance), telecom (network incidents).

Principle: implement mechanics in plain Python first; adopt frameworks only when they solve
a measured problem, recorded in an ADR.

| Stage | Name | Pattern | Status | Doc |
|-------|------|---------|--------|-----|
| 1 | Platform foundation on Kubernetes | AI Factory | Done | [01](01-stage1-foundation.md) |
| 2 | Document ingestion + RAG | Knowledge Intelligence | Done (2.4 top_k=20 live hybrid verification passed; 2.5 and 2.6 complete) | [02](02-stage2-rag-plan.md) |
| 3 | Claims Copilot (UI, structured investigation output) | Human-in-the-loop | Done (API/UI deployed; live brief and trace verified) | [03](03-stage3-claims-copilot-plan.md) |
| 4 | Claims tool-calling workflow (synthetic read-only Claims/Policy/Customer/Payments/Fraud APIs) | Bounded tool orchestration | Done (local synthetic scope reviewed and accepted; limitations documented) | [04](04-stage4-tool-calling-agent-plan.md), [handoff](04-stage4-handoff.md), [eval](eval/stage4-claims-agent-report.md) |
| 5 | Claims risk model (synthetic human-review referral) | Decision Intelligence | Done (local synthetic prototype; not production readiness) | [05](05-stage5-claims-risk-model-plan.md), [ADR-012](adr/ADR-012-stage5-risk-model.md), [eval](eval/stage5-risk-model-report.md) |
| 6 | Agent + ML + RAG orchestration | Hybrid AI | Done for user-reviewed local synthetic scope; limitations documented; not production-ready | [06](06-stage6-hybrid-ai-plan.md), [handoff](06-stage6-handoff.md), [eval](eval/stage6-hybrid-ai-report.md), [ADR-013](adr/ADR-013-stage6-hybrid-orchestration.md) |
| 7 | Human approval workflow | Governed autonomy | Done for the approved local synthetic scope; recovery/privacy gates passed; live Stage 6 workflow smoke deferred and not a Stage 8 dependency | [07 plan](07-stage7-human-approval-plan.md), [ADR-007](adr/ADR-007-workflow-engine-temporal.md) |
| 8 | Specialist agents (policy, fraud, evidence) - measured vs single agent | Multi-agent | - | - |
| 9 | AI observability / control tower (Prometheus, Grafana, Loki, Tempo) | AI Operations | - | - |
| 10 | Production platform: GitOps (Argo CD), Terraform, Kyverno, Vault, multi-domain | Enterprise AI Factory | - | - |

## Target repo layout (grows per stage)

```text
apps/          ai-api (S1), claims-service (S4), frontend (S3)
rag/           ingestion, retrieval (S2)
agents/        claims, fraud, evidence (S4, S8)
ml/            training, serving (S5)
data/          synthetic corpus (S2)
infrastructure/kind, kubernetes, terraform (S10)
observability/ otel, prometheus, grafana (S9)
tests/         unit, integration, evaluation, adversarial
docs/          stage docs, adr/, eval/, security.md, threat-model.md
```

## ADR index

| ADR | Topic | Stage | Status |
|-----|-------|-------|--------|
| 001 | Stage 1 local foundation stack | 1 | Accepted |
| 002 | Vector store: Qdrant | 2 | Accepted |
| 003 | Embeddings (OpenRouter) + reranker (TEI pod) | 2 | Accepted |
| 004 | Document model and chunking strategy | 2 | Accepted |
| 005 | Claims agent implementation (plain Python vs framework) | 4 | Accepted |
| 006 | Claims tool protocol (REST adapter vs MCP) | 4 | Accepted |
| 007 | Stage 7 workflow engine (Postgres-backed state machine) | 7 | Accepted | [ADR-007](adr/ADR-007-workflow-engine-temporal.md) |
| 008 | Observability stack expansion | 9 | - |
| 009 | Dense RAG query contract | 2 | Accepted |
| 010 | Hybrid retrieval and reranking contract | 2 | Accepted |
| 011 | Stage 3 frontend framework and delivery | 3 | Accepted |
| 012 | Stage 5 risk model and serving boundary | 5 | Accepted |
| 013 | Stage 6 hybrid claims orchestration | 6 | Accepted |

## Evaluation dimensions tracked from Stage 2 onward

Latency, token cost, retrieval recall/MRR, citation accuracy, faithfulness, failure rate,
human-escalation rate, operational complexity.
