# Copilot instructions

Read and follow [AGENTS.md](../AGENTS.md) - it is the single source of truth for project
context, current stage, conventions, commands, and known gotchas.

Key rules:

- Work stage by stage per [docs/ROADMAP.md](../docs/ROADMAP.md); implement only the approved stage plan.
- Record architectural choices as ADRs in `docs/adr/` and let the user decide.
- Plain Python first; all model calls via LiteLLM; every AI step gets an OTEL span.
- Never print or commit secrets; `.env` is local only.
