# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.10.7

# Stage 1: Get uv binary
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv_bin

# Stage 2: Final runtime image
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    PORT=8000 \
    TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken \
    FASTEMBED_CACHE_PATH=/app/.cache/fastembed

# Install system dependencies including Tesseract OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libtesseract-dev \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy uv binary
COPY --from=uv_bin /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy dependency specifications and project metadata
COPY pyproject.toml uv.lock README.md ./

# Install python dependencies without development packages
RUN uv sync --frozen --no-dev --no-install-project --no-cache

# Pre-download fastembed model and tiktoken encoding into image cache
RUN mkdir -p /app/.cache/tiktoken /app/.cache/fastembed && \
    .venv/bin/python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" && \
    .venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/app/.cache/fastembed')"

# Copy source code and scripts
COPY src/ ./src/
COPY Makefile ./

# Sync project package itself into the environment
RUN uv sync --frozen --no-dev --no-cache

# Create data and db mount directories
RUN mkdir -p /app/data /app/chroma_db

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Healthcheck testing /health endpoint
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=30 \
    CMD curl -f http://localhost:8000/health || exit 1

# Single uvicorn worker as required (embedded Chroma is not multi-process safe)
CMD ["uvicorn", "veltrix.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
