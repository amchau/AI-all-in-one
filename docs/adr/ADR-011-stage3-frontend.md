# ADR-011 - Stage 3 Frontend Framework and Delivery

## Status

Accepted (2026-10-04)

## Context

Stage 3 adds a local handler-facing UI for a structured, citation-backed claims investigation
brief. The repository currently has a FastAPI backend and no frontend. The UI handles synthetic
claim data only and is deployed in the existing kind cluster. Browser requests must reach the
cluster-internal API without making that API externally accessible or enabling broad CORS.

## Options

| Criterion | React + Vite frontend | Plain HTML/JavaScript | UI served by FastAPI |
|-----------|-----------------------|-----------------------|---------------------|
| UI composition and typed API contract | Strong component and TypeScript support | Manual structure and typing | Mixed into backend application |
| Local development | Vite dev server and production build | Minimal tooling | Coupled to Python app lifecycle |
| Kubernetes delivery | Separate static frontend container | Separate static frontend container | Reuses API pod/image |
| Browser/API boundary | Same-origin reverse proxy | Same-origin reverse proxy | Same-origin by default |
| Operational overhead | Additional image and Deployment | Additional image and Deployment | No separate frontend workload |

## Decision

Use a separate React + Vite application under `apps/frontend`, built into a pinned static-serving
container and deployed alongside `ai-api` in the local kind cluster. Configure the frontend web
server to proxy same-origin `/api` requests to the internal `ai-api` Service. Keep the API
cluster-internal; do not add a broad CORS policy or public Ingress.

This choice matches the roadmap's target `apps/frontend` layout and gives the evidence-review UI
explicit typed request/response models without introducing a UI framework into the Python API.
The extra container and deployment are acceptable for this local Stage 3 learning target.

## Validation

- Build the frontend and container from a clean dependency lockfile.
- Verify `/api` proxy behavior from the browser-facing frontend Service.
- Render and deploy Kustomize resources; check container security context and resource bounds.
- Exercise answer, abstention, validation, and dependency-error states with Playwright.
- Verify the frontend remains usable at desktop and mobile viewport sizes.

## Consequences

- Positive: frontend/backend contracts stay explicit; UI presentation can evolve independently;
  browser traffic remains same-origin and the API Service stays internal.
- Negative: another dependency lockfile, image, Service, and Deployment must be maintained.
- Follow-up: authentication and access control are required before using real claims or exposing
  the UI beyond the local synthetic lab; those concerns are not solved by this decision.