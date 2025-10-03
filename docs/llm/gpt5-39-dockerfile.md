### Findings against the current Dockerfile

- Virtual environment is built correctly and copied to the final image, and PATH is set to prefer `/opt/venv/bin`. Good.
- Development-only packages (pytest, black, flake8, mypy, bandit) are installed into the production venv. This increases image size and attack surface without runtime value.
- No build-time sanity check to ensure FastAPI/Uvicorn (and Prometheus client) import successfully from the venv.
- Entrypoint runs as root (expected) to handle first-run ownership, then uses gosu to drop privileges. Good.
- Healthcheck script is present and executable. Good.
- Permissions are strict (`750/640`), which is consistent with your privilege model. Good.
- Using `tini` for proper signal handling is correct.
- Exposes 8080/9090 and declares volumes aligned with Compose. Good.

What we’ll change:
- Split runtime vs dev deps: keep runtime-only packages in the venv; optionally allow dev deps via a build arg if needed.
- Add build-time import validation for critical runtime deps to catch misconfigurations early.
- Add `VIRTUAL_ENV` to environment for better introspection and consistency.
- Keep everything else functionally identical to remain drop-in.

---

### Drop‑in replacement Dockerfile (hardened, deterministic, slimmer runtime)

```dockerfile
# =============================================================================
# MCP Server - Production Dockerfile (venv, python:3.12-slim-trixie)
# Hardened, deterministic PATH, runtime-only deps in venv, build-time sanity
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Python Builder (creates /opt/venv with runtime deps)
# -----------------------------------------------------------------------------
FROM python:3.12-slim-trixie AS python-builder

ARG VENV_PATH=/opt/venv
ARG INSTALL_DEV=false

ENV VENV_PATH=${VENV_PATH}

# Build deps only in builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc python3-dev libssl-dev libffi-dev git \
  && rm -rf /var/lib/apt/lists/*

# Create and activate virtual environment
RUN python -m venv "${VENV_PATH}"
ENV PATH="${VENV_PATH}/bin:${PATH}"

# Upgrade pip and install runtime packages
# Note: dev/test/lint packages optional via INSTALL_DEV for CI images
RUN pip install -U pip && \
    pip install --no-cache-dir \
      fastapi uvicorn[standard] pydantic pyyaml prometheus-client structlog \
      aiofiles aiodocker circuitbreaker httpx requests jsonschema \
      python-dateutil cryptography ipaddress psutil

# Optionally include development tools (controlled via build arg)
RUN if [ "${INSTALL_DEV}" = "true" ]; then \
      pip install --no-cache-dir pytest pytest-asyncio pytest-cov black flake8 mypy bandit ; \
    fi

# Build-time sanity check: ensure critical deps import from venv
RUN python - <<'PY'
import sys
print("[BUILD] Python:", sys.executable, sys.version.split()[0])
for m in ("fastapi", "uvicorn", "prometheus_client"):
    __import__(m)
print("[BUILD] Critical runtime deps import OK")
PY

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

# Create non-root user/group with deterministic uid/gid
ARG MCP_UID=1000
ARG MCP_GID=1000
RUN groupadd -r mcp --gid=${MCP_GID} && \
    useradd -r -g mcp --uid=${MCP_UID} --home-dir=/app --shell=/bin/bash mcp

# Minimal runtime packages only
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap masscan gobuster \
    curl wget ca-certificates \
    tini gosu \
  && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=python-builder /opt/venv /opt/venv

# Environment
ENV VIRTUAL_ENV="/opt/venv" \
    PATH="/opt/venv/bin:${PATH}" \
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

# Default command (entrypoint will exec with venv python)
CMD ["python", "-m", "mcp_server.server"]
```

---

### Validation checklist

- Build:
  - `docker compose build --no-cache` shows “[BUILD] Critical runtime deps import OK”.
  - Image size decreases (dev deps excluded by default).
- Runtime:
  - `docker compose up -d` and `docker logs -f mcp-server` show “Using Python executable: /opt/venv/bin/python”.
  - No `RuntimeError` about FastAPI/Uvicorn; entrypoint’s “HTTP deps present” appears.
- Inter-service:
  - With the updated Compose (Prometheus readiness healthcheck and `depends_on`), mcp-server no longer restart-loops during cold starts.
- Privilege safety:
  - First-run ownership fixes still occur; thereafter process runs as `mcp` via gosu inside entrypoint.
- Health:
  - `/healthcheck.sh` continues to pass once the server is up; Prometheus readiness waits are non-fatal and logged with clear attempt counters.

If you want to produce a CI image with dev tooling baked in, build with `--build-arg INSTALL_DEV=true`; the production Compose continues using the slim runtime by default.

https://copilot.microsoft.com/shares/7GVYwKEPhtU9NNVrUvktU
