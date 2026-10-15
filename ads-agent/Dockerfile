# The ads agent as an Agent Runtime container. `agents-cli deploy` has Agent
# Runtime build it from this project; to build and test it locally:
#
#   docker build -t ads-agent .
#
# Holds everything the skills run besides Python: uv, ffmpeg, and the genmedia
# MCP servers, plus every skill script's dependencies, installed at build time
# so containers start warm and make no package downloads at run time.
FROM python:3.12-slim

ARG GENMEDIA_VERSION=3.20.0

ENV PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR=/opt/uv-cache \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /uvx /usr/local/bin/

# genmedia-veo, genmedia-omni, and genmedia-avtool (prebuilt Go binaries).
RUN curl -sSLf "https://github.com/GoogleCloudPlatform/vertex-ai-creative-studio/releases/download/v${GENMEDIA_VERSION}/genmedia-mcp-servers_linux_amd64.tar.gz" \
        | tar -xz -C /tmp \
    && mv /tmp/mcp-veo-go /tmp/mcp-omni-go /tmp/mcp-avtool-go /usr/local/bin/ \
    && rm -f /tmp/mcp-*-go

WORKDIR /app

# The agent's own dependencies, cached separately from the code.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY .agents/ .agents/
COPY ads_agent/ ads_agent/

# Each skill script declares its dependencies inline; install them all now.
RUN for script in .agents/skills/*/scripts/*.py; do \
        if head -1 "$script" | grep -q "uv run"; then uv sync --script "$script" --quiet; fi; \
    done

ENV GOOGLE_GENAI_USE_VERTEXAI=TRUE \
    UV_OFFLINE=1

EXPOSE 8080
CMD ["sh", "-c", "exec .venv/bin/uvicorn ads_agent.fast_api_app:app --host 0.0.0.0 --port ${PORT:-8080}"]
