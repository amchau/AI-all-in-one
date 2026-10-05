# ADR-006 - Claims Agent Tool Protocol

## Status

Proposed

## Context

Stage 4 needs a small set of synthetic business tools for a local Kubernetes claims investigation workflow. The model must choose only from a fixed, validated tool allowlist. The mock business APIs should have clear service boundaries without adding unnecessary services or protocol infrastructure to a laptop cluster.

## Options

| Criterion | REST-backed tool adapter | Standalone MCP server | In-process Python functions only |
|-----------|--------------------------|-----------------------|----------------------------------|
| Scale | Standard HTTP services; suitable for initial mock workload | Standard client/server protocol; supports multiple MCP clients and servers | Scales only with agent process; service boundaries are simulated |
| Latency | One internal HTTP hop per tool call | One internal protocol hop; similar local latency | Lowest, no network hop |
| Features / filtering | Typed domain endpoints and adapter-enforced allowlist; protocol semantics owned locally | Standardized discovery/invocation and ecosystem interoperability | Exact filtering possible, but no service/API contract validation |
| Operational burden (kind/laptop) | One modular mock service plus existing API deployment | Additional protocol server, deployment, configuration, and debugging | Minimal runtime burden |
| Kubernetes support | Mature HTTP patterns, probes, Services, and policy tooling | Runs on Kubernetes but needs MCP transport/deployment choices | Runs in existing API pod |
| Cost | OSS HTTP stack; no extra platform cost | OSS protocol; additional engineering and resource cost | No added service cost |
| Developer experience | Familiar typed APIs; explicit adapter code | Standard protocol across compatible clients; additional concepts and debugging | Simple to start; weaker simulation of real APIs |
| Cloud portability (Azure/AWS/GCP) | High; portable HTTP APIs and containers | High where MCP clients/servers are supported; ecosystem maturity varies | High as application code, but no independent service boundary |

## Decision

Recommend one modular internal REST service with separate typed endpoints for Claims, Policy, Customer, Payments, and Fraud, called through a small Python tool adapter. Expose only fixed LiteLLM tool/function definitions. Validate tool names and arguments before dispatch; disallow arbitrary URLs, SQL, generic execution, and mutations. Defer a standalone MCP server.

Status remains Proposed until the user accepts this architectural decision.

## Validation

- Contract-test every domain endpoint and its validation/not-found/error behavior.
- Verify the adapter rejects unknown tools and invalid arguments and dispatches only to allowlisted internal routes.
- Run bounded synthetic scenarios and assert the prohibited-action rate is zero.
- Render and deploy the internal service in local kind; verify tool-call traces contain bounded operational attributes but no narrative or full payload.
- Revisit MCP only if interoperability with multiple independent agent clients becomes a measured requirement.

## Consequences

Positive:
- The mock APIs exercise realistic service boundaries using familiar infrastructure.
- A single Deployment keeps local resource and operational cost low.
- The tool permission boundary stays application-owned and testable.

Negative:
- The adapter duplicates some mapping between model tool schemas and REST contracts.
- One service does not model independent domain-team deployment or scaling.
- MCP interoperability is deferred.

Follow-up:
- If later scope requires MCP, preserve the validated tool registry as the policy boundary and place the protocol adapter around it rather than widening permissions.