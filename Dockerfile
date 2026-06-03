# Saffron & Smoke — voice ordering backend (FastAPI + Pipecat + Gemini Live).
# Built for Cloud Run (listens on $PORT, scales to zero). Local dev uses the
# same image via ../docker-compose.yml.

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# libgomp1 is required at runtime by onnxruntime (Pipecat's Silero VAD).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /app

# 1) Dependency layer — cached unless pyproject/uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) Application code.
COPY . .
RUN uv sync --frozen --no-dev

# Cloud Run injects PORT (default 8080). main.py reads it.
ENV PORT=8080
EXPOSE 8080

ENTRYPOINT ["./docker-entrypoint.sh"]
