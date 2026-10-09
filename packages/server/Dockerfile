# syntax=docker/dockerfile:1
# Build context: packages/server

FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---- runtime (default target) ----
FROM python:3.13-slim AS runtime
RUN useradd --create-home --uid 1000 scrappy \
    && mkdir -p /data /config && chown scrappy:scrappy /data /config
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    SCRAPPY_DATA_DIR=/data \
    SCRAPPY_CONFIG_DIR=/config
USER scrappy
VOLUME ["/data"]
# Config is mounted read-only at /config by compose.
ENTRYPOINT ["scrappy"]
CMD ["worker"]

# ---- browser (not built yet) ----
# Planned variant with Chromium/Camoufox for stealthy/dynamic engines:
#   FROM runtime AS browser
#   (install `scrappy[browser]` extra and run `playwright install --with-deps chromium`)
