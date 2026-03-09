# Piper TTS Service - CPU Optimized (Low Latency)
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download MEDIUM models (faster inference than high)
RUN mkdir -p /app/models \
    # English US (ryan-medium) ~60MB
    && wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/ryan/medium/en_US-ryan-medium.onnx" \
        -O /app/models/en_US-ryan-medium.onnx \
    && wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/ryan/medium/en_US-ryan-medium.onnx.json" \
        -O /app/models/en_US-ryan-medium.onnx.json \
    # Spanish Mexico (ald-medium) ~60MB
    && wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/es/es_MX/ald/medium/es_MX-ald-medium.onnx" \
        -O /app/models/es_MX-claude-medium.onnx \
    && wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/es/es_MX/ald/medium/es_MX-ald-medium.onnx.json" \
        -O /app/models/es_MX-claude-medium.onnx.json

# App code
COPY app/ ./app/

RUN mkdir -p /audio

ENV MODELS_DIR=/app/models
ENV BASE_URL=http://localhost:8000
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Single worker to avoid model duplication in memory
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
