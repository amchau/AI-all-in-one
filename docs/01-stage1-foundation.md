# Stage 1 - Platform Foundation

## Scope

Build local platform base for enterprise AI experiments.

Included:

- kind cluster foundation
- Core data services: PostgreSQL, Qdrant, MinIO
- LLM gateway: LiteLLM
- API service: FastAPI
- Telemetry foundation: OpenTelemetry Collector

Not included yet:

- RAG ingestion pipeline
- Claims domain workflows
- Temporal workflow engine
- Multi-agent runtime
- Full observability stack (Prometheus, Grafana, Loki, Tempo)

## Runtime flow

1. Client calls `ai-api` endpoint.
2. API calls LiteLLM (`/chat/completions`).
3. LiteLLM forwards the call to Groq's `openai/gpt-oss-20b` model.
4. API probes PostgreSQL, Qdrant, MinIO.
5. API exports traces to OTEL collector.

## Validate stage

- `kubectl -n ai-platform get pods`
- `curl http://127.0.0.1:8000/healthz`
- `curl -X POST http://127.0.0.1:8000/v1/investigate ...`
- `kubectl -n ai-platform logs deploy/otel-collector --tail=200`

## Known constraints

- LiteLLM requires a valid `GROQ_API_KEY` in `.env`.
- Stateful services are currently `emptyDir` for speed; data is non-persistent.
- Secrets are local/dev placeholders.
