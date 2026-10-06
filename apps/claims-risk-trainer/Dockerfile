FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY ml/requirements-training.txt /app/requirements-training.txt
RUN pip install --no-cache-dir -r /app/requirements-training.txt

COPY ml/__init__.py /app/ml/__init__.py
COPY ml/claims_risk/ /app/ml/claims_risk/
COPY data/risk/ /app/data/risk/

USER 10001:10001
ENTRYPOINT ["python", "-m", "ml.claims_risk.run_training"]
