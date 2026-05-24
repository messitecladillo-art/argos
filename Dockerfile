# ── Argos — production Dockerfile ──────────────────
# Build:  docker build -t argos .
# Run:    docker run -p 5050:5050 -v ./data:/app/data --env-file .env argos
#
# For China mainland mirrors, uncomment the pip index lines below.

# ── Stage 1: build dependencies ──────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /app

# China mirror: RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/install --no-deps -r requirements.txt && \
    pip install --prefix=/install -r requirements.txt

# ── Stage 2: runtime ────────────────────────────────────────
FROM python:3.13-slim AS runtime

LABEL org.opencontainers.image.title="Argos"
LABEL org.opencontainers.image.description="Self-evolving multi-agent collaboration system"
LABEL org.opencontainers.image.licenses="MIT"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system argos && useradd --system --gid argos --create-home argos
WORKDIR /app

COPY --from=builder /install /usr/local

COPY . .
RUN chown -R argos:argos /app

USER argos

RUN mkdir -p /app/data

EXPOSE 5050

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://127.0.0.1:5050/api/argos/status || exit 1

ENV PORT=5050 \
    FLASK_DEBUG=0 \
    PYTHONUNBUFFERED=1

VOLUME ["/app/data"]

CMD ["uvicorn", "argos.asgi:create_asgi_app", "--factory", \
     "--host", "0.0.0.0", "--port", "5050", \
     "--ws", "wsproto", \
     "--log-level", "info", \
     "--no-access-log"]
