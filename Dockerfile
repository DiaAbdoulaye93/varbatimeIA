# Single production image: the Angular build is served by FastAPI (IMPLEMENTATION.md §1).

# --- Stage 1: build the Angular dashboard ---
FROM node:24-slim AS frontend
WORKDIR /build
# Dependencies first, so this layer is cached until package-lock.json changes.
COPY frontend/package.json frontend/package-lock.json ./
# The cache mount keeps downloaded packages between builds (and between retries).
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund --fetch-retries=5
COPY frontend/ ./
RUN npx ng build --configuration production

# --- Stage 2: install the backend into a virtualenv with uv ---
FROM python:3.12-slim AS backend
COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /bin/uv
# Raise the timeout on slow links: docker build --build-arg UV_HTTP_TIMEOUT=300 .
ARG UV_HTTP_TIMEOUT=120
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_HTTP_TIMEOUT=${UV_HTTP_TIMEOUT}
WORKDIR /src
# Third-party dependencies first (cached until uv.lock changes), then the app itself.
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
# --no-editable installs app/ (prompts included) into the venv: the runtime needs no source.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable

# --- Stage 3: runtime ---
FROM python:3.12-slim
RUN useradd --create-home --uid 10001 app
COPY --from=backend /opt/venv /opt/venv
COPY --from=frontend /build/dist/frontend/browser /app/static
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/static
WORKDIR /app
USER app
EXPOSE 8000
# Port from $PORT when the platform sets one (Render: 10000), 8000 otherwise (K8s, local).
# --proxy-headers: the app runs behind a reverse proxy (Render, Kubernetes ingress).
# exec: uvicorn replaces the shell and receives the stop signal directly.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips '*'"]
