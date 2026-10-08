# The MCP server over Streamable HTTP, for hosting (Railway, Fly, Render, any container platform).
#
# Build context is the repo root:  docker build -f deploy/mcp/Dockerfile .
# Required env:  WOO_BASE_URL, WOO_CONSUMER_KEY, WOO_CONSUMER_SECRET
# Recommended:   WOO_MCP_TOKEN (bearer token clients must send), MCP_ALLOWED_HOSTS (public hostname)
# Platform:      PORT is honoured; GET /healthz answers 200 without auth for health checks.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8765
CMD ["sh", "-c", "woo-mcp --transport streamable-http --host 0.0.0.0 --port ${PORT:-8765} --allowed-hosts ${MCP_ALLOWED_HOSTS:-*}"]
