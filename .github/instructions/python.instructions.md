---
applyTo: "apps/**/*.py,rag/**/*.py,agents/**/*.py,ml/**/*.py,tests/**/*.py"
description: Python conventions for platform services, RAG, agents and ML code.
---

- Python 3.12, full type hints, pydantic models for request/response and structured LLM output.
- Config via pydantic-settings env vars; no hardcoded URLs, keys or model names in logic.
- Call models only through LiteLLM (`/chat/completions`, `/embeddings`) with `Authorization: Bearer` master key.
- Wrap each AI step in an OTEL span (`rag.*`, `llm.*`, `tool.*`, `ml.*`); record model, token usage,
  latency, top_k, scores, doc ids. Never record secrets or raw PII.
- Return sanitized errors to clients (`HTTPException` with generic detail); log full context server-side.
- No LangChain/LlamaIndex/agent frameworks without an accepted ADR.
- Pure logic (chunking, prompt assembly, scoring, fusion) stays side-effect free and unit-tested with pytest.
- Every new or modified Python file starts with a concise module docstring explaining its purpose. Add concise comments/docstrings for meaningful responsibilities and non-obvious logic; avoid narrating obvious lines.
