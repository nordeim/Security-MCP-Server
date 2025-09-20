# =============================================================================
# MCP Server - Production Dockerfile (updated)
# =============================================================================
# Multi-stage build for security and size optimization
# Final image: compact and production-ready
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Python Builder
# -----------------------------------------------------------------------------
FROM python:3.12-slim-trixie AS python-builder

ARG PYTHON_VERSION=3.12
ARG PIP_VERSION=23.3.1
ARG SETUPTOOLS_VERSION=69.0.2

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    python3-dev \
    libssl-dev \
    libffi-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and setuptools
RUN pip install --no-cache-dir --upgrade \
    pip==${PIP_VERSION} \
    setuptools==${SETUPTOOLS_VERSION} \
    wheel

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements first for layer caching
COPY requirements.txt /tmp/requirements.txt

# Install Python dependencies into venv
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# -----------------------------------------------------------------------------
# Stage 2: Tool Builder (kept for tool packaging; optional)
# -----------------------------------------------------------------------------
FROM ubuntu:22.04 AS tool-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap \
    masscan \
    gobuster \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/tools/bin

# -----------------------------------------------------------------------------
# Stage 3: Final Production Image
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

# Install runtime dependencies (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap \
    masscan \
    gobuster \
    curl \
    ca-certificates \
    libssl-dev \
    libffi-dev \
    tini \
    wget \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Copy virtual environment from builder
COPY --from=python-builder /opt/venv /opt/venv

# Environment
ENV PATH="/opt/venv/bin:$PATH" \
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

# Create app directories and ensure ownership and safe permissions
RUN mkdir -p /app/config /app/logs /app/data /app/scripts && \
    chown -R mcp:mcp /app && \
    # Preserve execute bit for directories; make files non-world-readable by default
    find /app -type d -exec chmod 750 {} + && \
    find /app -type f -exec chmod 640 {} + && \
    # Ensure logs/data/scripts are writable/executable by owner
    chmod 750 /app/logs /app/data /app/scripts || true

WORKDIR /app

# Copy app code with ownership for non-root user
COPY --chown=mcp:mcp mcp_server/ /app/mcp_server/
COPY --chown=mcp:mcp scripts/ /app/scripts/
COPY --chown=mcp:mcp config/ /app/config/

# Copy entrypoint and healthcheck scripts
COPY --chown=mcp:mcp docker/entrypoint.sh /entrypoint.sh
COPY --chown=mcp:mcp docker/healthcheck.sh /healthcheck.sh
RUN chmod +x /entrypoint.sh /healthcheck.sh

# Declare volumes for runtime-writable paths
VOLUME ["/app/config", "/app/logs", "/app/data"]

# Expose ports
EXPOSE 8080 9090

# Switch to non-root user
USER mcp

# Healthcheck using script
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["/healthcheck.sh"]

# Use tini for proper signal handling
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]

# Default command
CMD ["python", "-m", "mcp_server.server"]
