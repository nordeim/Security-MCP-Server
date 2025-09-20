# =============================================================================
# MCP Server - Production Dockerfile (venv, python:3.12-slim-trixie)
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Python Builder
# -----------------------------------------------------------------------------
FROM python:3.12-slim-trixie AS python-builder

ENV VENV_PATH=/opt/venv
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc python3-dev libssl-dev libffi-dev git \
    && rm -rf /var/lib/apt/lists/*

# Create and activate virtual environment
RUN python -m venv "${VENV_PATH}"
ENV PATH="${VENV_PATH}/bin:${PATH}"

# Upgrade pip and install required packages directly
RUN pip install -U pip && \
    pip install --no-cache-dir \
      fastapi uvicorn[standard] pydantic pyyaml prometheus-client structlog \
      aiofiles aiodocker circuitbreaker httpx requests jsonschema \
      python-dateutil cryptography ipaddress psutil \
      pytest pytest-asyncio pytest-cov black flake8 mypy bandit

# If you still have local packages to install (e.g., your app itself)
# COPY mcp_server/ /tmp/mcp_server/
# RUN pip install --no-cache-dir /tmp/mcp_server

# -----------------------------------------------------------------------------
# Stage 2: Final Production Image
# -----------------------------------------------------------------------------
FROM python:3.12-slim-trixie

LABEL maintainer="MCP Server Team"
LABEL version="2.0.0"
LABEL description="Production MCP Server with security tools"
LABEL org.opencontainers.image.source="https://github.com/nordeim/Security-MCP-Server"
LABEL org.opencontainers.image.vendor="MCP"
LABEL org.opencontainers.image.licenses="MIT"

# Create non-root user
RUN groupadd -r mcp --gid=1000 && \
    useradd -r -g mcp --uid=1000 --home-dir=/app --shell=/bin/bash mcp

# Minimal runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap masscan gobuster \
    curl wget ca-certificates \
    tini gosu \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=python-builder /opt/venv /opt/venv

# Environment
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=UTF-8 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=UTC \
    MCP_HOME=/app \
    MCP_CONFIG_PATH=/app/config/config.yaml \
    MCP_LOG_PATH=/app/logs \
    MCP_DATA_PATH=/app/data

# Create app directories with safe defaults
RUN mkdir -p /app/config /app/logs /app/data /app/scripts && \
    chown -R mcp:mcp /app && \
    find /app -type d -exec chmod 750 {} + && \
    find /app -type f -exec chmod 640 {} +

WORKDIR /app

# Copy app code with ownership
COPY --chown=mcp:mcp mcp_server/ /app/mcp_server/
COPY --chown=mcp:mcp scripts/ /app/scripts/
COPY --chown=mcp:mcp config/ /app/config/

# Entrypoint and healthcheck scripts (ensure exec bits)
COPY --chown=mcp:mcp docker/entrypoint.sh /entrypoint.sh
COPY --chown=mcp:mcp docker/healthcheck.sh /healthcheck.sh
RUN chmod -R 750 /app/scripts && \
    find /app/scripts -type f -name "*.sh" -exec chmod 750 {} + && \
    chmod 750 /entrypoint.sh /healthcheck.sh

# Declare volumes for writable paths
VOLUME ["/app/logs", "/app/data", "/app/config"]

# Expose ports
EXPOSE 8080 9090

# Run entrypoint as root to fix ownership on first run, then drop to mcp
USER root

# Healthcheck using script (single source of truth)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["/healthcheck.sh"]

# Use tini for proper signal handling
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]

# Default command
CMD ["python", "-m", "mcp_server.server"]
