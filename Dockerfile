FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ── dependency layer (cached unless requirements.txt changes) ──────────────
FROM base AS deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ── runtime image ──────────────────────────────────────────────────────────
FROM base AS runtime

# Non-root user — principle of least privilege
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Copy installed packages from deps stage
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy source — exclude dev/test files via .dockerignore
COPY --chown=appuser:appgroup . .

USER appuser

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/health')"

CMD ["uvicorn", "backend:app", "--host", "0.0.0.0", "--port", "8765", \
     "--log-level", "info", "--workers", "1"]
