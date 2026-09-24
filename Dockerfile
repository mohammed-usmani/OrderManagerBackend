# Saffron & Smoke — voice ordering backend (FastAPI + Pipecat + Gemini Live).
# Host-agnostic: listens on $PORT. Local dev uses the same image via
# docker-compose.yml.

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

# Pipecat loads NLTK's punkt_tab tokenizer at import and would otherwise try to
# download it on every cold start. Bake it into the image instead.
ENV NLTK_DATA=/usr/local/share/nltk_data
RUN python -c "import nltk; nltk.download('punkt_tab', download_dir='$NLTK_DATA', quiet=True)"

# Run as an unprivileged user; the app never needs to write to /app.
RUN useradd --system --uid 10001 --no-create-home app
USER app

# The host may inject PORT (default 8080). main.py reads it.
ENV PORT=8080
EXPOSE 8080

ENTRYPOINT ["./docker-entrypoint.sh"]
