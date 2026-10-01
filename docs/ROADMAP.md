# Roadmap - Enterprise AI Decision & Operations Platform

One evolving platform, built in 10 stages. First domain: insurance claims. Later reused
for banking (fraud), energy (predictive maintenance), telecom (network incidents).

Principle: implement mechanics in plain Python first; adopt frameworks only when they solve
a measured problem, recorded in an ADR.

| Stage | Name | Pattern | Status | Doc |
|-------|------|---------|--------|-----|
| 1 | Platform foundation on Kubernetes | AI Factory | Done | [01](01-stage1-foundation.md) |
| 2 | Document ingestion + RAG | Knowledge Intelligence | In progress | [02](02-stage2-rag-plan.md) |
| 3 | Claims Copilot (UI, structured investigation output) | Human-in-the-loop | - | - |
| 4 | Tool-calling agent (fake Claims/Policy/Customer/Payments/Fraud APIs) | Agentic workflow, MCP-style tools | - | - |
| 5 | Claims risk model (XGBoost/LightGBM) | Decision Intelligence | - | - |
| 6 | Agent + ML + RAG orchestration | Hybrid AI | - | - |
| 7 | Human approval workflow (Temporal) | Governed autonomy | - | - |
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
| 005 | Agent framework (plain Python vs framework) | 4 | - |
| 006 | Tool protocol (REST vs MCP) | 4 | - |
| 007 | Workflow engine (Temporal) | 7 | - |
| 008 | Observability stack expansion | 9 | - |

## Evaluation dimensions tracked from Stage 2 onward

Latency, token cost, retrieval recall/MRR, citation accuracy, faithfulness, failure rate,
human-escalation rate, operational complexity.
