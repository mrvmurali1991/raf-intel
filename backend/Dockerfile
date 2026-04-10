# ---------------------------------------------------------------------------
# RAF Intelligence — Backend (FastAPI) Multi-Stage Production Image
# ---------------------------------------------------------------------------

# Stage 1: Build — install compiled dependencies, then discard compilers
FROM python:3.11.9-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libffi-dev \
        libssl-dev \
        default-libmysqlclient-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime — slim image without compilers
FROM python:3.11.9-slim AS runtime

WORKDIR /app

# Only runtime C libraries (no gcc/g++)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libmariadb3 \
        libffi8 \
        libssl3 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user
RUN groupadd --gid 1001 appuser && \
    useradd  --uid 1001 --gid appuser --no-create-home appuser

COPY --chown=appuser:appuser app/ ./app/

RUN mkdir -p /app/uploads /app/logs /app/data/submissions && \
    chmod 700 /app/uploads /app/logs /app/data/submissions && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8500

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8500/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8500", "--workers", "1"]
