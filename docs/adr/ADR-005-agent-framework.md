# ADR-005 - Claims Agent Implementation

## Status

Proposed

## Context

Stage 4 needs a controlled tool-calling workflow for synthetic claims investigation on a local kind + Podman cluster. The repository principle is plain Python first, with visible prompting, retrieval, and tool loops; no agent framework is currently used. The agent must be bounded, testable, traceable, and prohibited from taking claim actions or making coverage decisions.

## Options

| Criterion | Plain Python bounded loop | LangChain | LlamaIndex / agent workflow |
|-----------|----------------------------|-----------|-----------------------------|
| Scale | Sufficient for the small bounded Stage 4 tool set; app can scale horizontally | Supports larger integrations; adds framework abstractions | Strong for retrieval-centric workflows; broader than current need |
| Latency | Minimal orchestration overhead | Small additional dispatch/serialization overhead | Small additional orchestration overhead |
| Features / filtering | Exact allowlist and schemas implemented explicitly; no implicit tools | Broad tool/memory integrations; requires careful framework-level restrictions | Broad retrieval/tool integrations; requires careful restriction |
| Operational burden (kind/laptop) | No new runtime or model service | Dependency and upgrade surface in API image | Dependency and upgrade surface in API image |
| Kubernetes support | Standard Python container and existing deployment pattern | Standard Python container | Standard Python container |
| Cost | No framework license or hosted service | OSS core; possible hosted extras are optional | OSS core; possible hosted extras are optional |
| Developer experience | Mechanics visible and directly unit-testable; more glue code | Familiar abstractions; framework behavior can obscure execution | Convenient RAG integration; overlaps existing plain-Python RAG package |
| Cloud portability (Azure/AWS/GCP) | High; standard Python, HTTP, and OTEL | High; Python package availability | High; Python package availability |

## Decision

Recommend plain Python with a bounded, explicit tool-selection/execution loop using LiteLLM tool/function calling. Keep the allowlist, schemas, iteration limits, and failure behavior visible in repository code. Do not add a framework dependency for the initial workflow.

Status remains Proposed until the user accepts this architectural decision.

## Validation

- Unit-test tool allowlisting, argument/response validation, turn and call limits, tool failures, malformed model output, and prohibited actions without live providers.
- Run fixed synthetic scenarios and report tool-selection correctness, required-fact coverage, unsupported assertions, failures, latency, and prohibited-action rate (must be zero).
- Review whether plain Python causes measured maintenance or correctness problems before proposing framework adoption.

## Consequences

Positive:
- Execution policy and tool permissions stay explicit and auditable.
- No additional framework dependency or runtime burden on kind.
- The same interfaces remain portable across cloud Kubernetes environments.

Negative:
- The project owns loop mechanics, validation, and error handling.
- Adding advanced memory, planning, or workflow features later may require more application code.

Follow-up:
- Revisit only if Stage 4 tests or later stages show a concrete limitation; compare alternatives and record measurements in a new ADR or amendment.