FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY apps/ai-api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY apps/ai-api/main.py /app/main.py
COPY apps/ai-api/http_metrics.py /app/http_metrics.py
COPY apps/ai-api/workflow_store.py /app/workflow_store.py
COPY apps/ai-api/workflow_worker.py /app/workflow_worker.py
COPY agents/ /app/agents/
COPY ml/ /app/ml/
COPY rag/ /app/rag/
COPY data/generated/ /app/data/generated/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
