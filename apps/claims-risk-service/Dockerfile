FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV MODEL_PATH=/app/model/model.json
ENV MODEL_METADATA_PATH=/app/model/metadata.json

WORKDIR /app

COPY apps/claims-risk-service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY apps/claims-risk-service/main.py /app/main.py
COPY ml/__init__.py /app/ml/__init__.py
COPY ml/claims_risk/__init__.py /app/ml/claims_risk/__init__.py
COPY ml/claims_risk/dataset.py /app/ml/claims_risk/dataset.py
COPY ml/claims_risk/predictor.py /app/ml/claims_risk/predictor.py
COPY artifacts/claims-risk/model.json /app/model/model.json
COPY artifacts/claims-risk/metadata.json /app/model/metadata.json

USER 10001:10001
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
