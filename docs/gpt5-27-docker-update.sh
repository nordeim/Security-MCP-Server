# Review summary and alignment

You’re close. The stack is coherent, but a few mismatches can bite you under real workloads. Below are precise issues and fixes, then a clear execution plan, and finally drop-in replacement files.

- **Config fallback not honored:** Entrypoint generates a fallback config at /app/config-local/config.yaml but doesn’t update MCP_CONFIG_PATH, so the app ignores it.
- **First-run permissions on named volumes:** Running as user mcp makes first-run writes fail if volumes are owned by root. Fix ownership before dropping privileges.
- **PID file mismatch:** You write the entrypoint’s PID, not the app’s.
- **Dual healthchecks:** Dockerfile and Compose both define healthchecks; they will drift. Keep one source of truth.
- **Scripts execute bits:** Global chmod can strip execute bits; re-apply explicitly after copying scripts.
- **venv consistency and pip:** Keep python:3.12-slim-trixie with /opt/venv, upgrade pip with pip install -U pip, and install your required modules directly.

---

## Execution plan

1. **Entrypoint hardening**
   - **Fix config fallback:** Export MCP_CONFIG_PATH to the fallback file when used.
   - **Ensure ownership:** If running as root, chown /app/config, /app/logs, /app/data to 1000:1000 on first run; then drop privileges to mcp before starting the app.
   - **Correct PID file:** Write the child app PID.
   - **Keep venv awareness:** Use the venv python found in PATH.

2. **Dockerfile adjustments**
   - **Retain venv:** Build /opt/venv in a builder stage, copy it into final.
   - **Upgrade pip & install packages directly:** pip install -U pip, then install the full list you provided into the venv.
   - **Minimal runtime:** Keep runtime slim; include tini, curl, wget, and optional gosu for safe privilege drop. Avoid -dev headers in final.
   - **Permissions:** Re-apply execute bits for scripts after copying.
   - **Healthcheck single source:** Keep HEALTHCHECK in the image using /healthcheck.sh.

3. **Compose alignment**
   - **Remove competing healthcheck for mcp-server:** Use the image’s healthcheck.
   - **Grafana healthcheck:** Use wget to avoid curl dependency.
   - **Ownership-friendly startup:** No changes needed to volumes; entrypoint handles chown.
   - **Optional depends_on semantics:** Only if you truly need Prometheus before app.

4. **Healthcheck script**
   - **Fast, deterministic check:** Use wget, fallback to curl, respect MCP_HEALTH_TIMEOUT, and use set -Eeuo pipefail.
   - **No extraneous logging:** Exit codes only.

5. **Validate**
   - **Build:** docker build -t mcp:local .
   - **Run:** docker compose up -d; verify mcp-server health=healthy, logs writable, config seeded, and PID file contains app PID.
   - **Shutdown:** docker stop; ensure graceful shutdown without SIGKILL unless timeout exceeded.

---

## Drop-in replacement: Dockerfile

```dockerfile
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
```

---

## Drop-in replacement: docker-compose.yml (focused updates)

```yml
version: '3.8'

networks:
  mcp-public:
    name: mcp-public
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/24

  mcp-internal:
    name: mcp-internal
    driver: bridge
    internal: true
    ipam:
      config:
        - subnet: 172.29.0.0/24

volumes:
  mcp-config:
    name: mcp-config
    driver: local
  mcp-logs:
    name: mcp-logs
    driver: local
  mcp-data:
    name: mcp-data
    driver: local
  prometheus-data:
    name: prometheus-data
    driver: local
  grafana-data:
    name: grafana-data
    driver: local

services:
  mcp-server:
    container_name: mcp-server
    image: mcp-server:${MCP_VERSION:-latest}
    build:
      context: .
      dockerfile: Dockerfile
      args:
        PYTHON_VERSION: ${PYTHON_VERSION:-3.12}
      cache_from:
        - mcp-server:latest
    restart: unless-stopped

    networks:
      - mcp-public
      - mcp-internal

    ports:
      - "${MCP_SERVER_PORT:-8080}:8080"
      - "${MCP_METRICS_PORT:-9090}:9090"

    volumes:
      - mcp-config:/app/config:rw
      - mcp-logs:/app/logs:rw
      - mcp-data:/app/data:rw
      # Development-only bind mounts go in docker-compose.override.yml

    environment:
      MCP_SERVER_TRANSPORT: ${MCP_SERVER_TRANSPORT:-http}
      MCP_SERVER_HOST: 0.0.0.0
      MCP_SERVER_PORT: ${MCP_SERVER_PORT:-8080}
      TOOLS_PACKAGE: ${TOOLS_PACKAGE:-mcp_server.tools}
      TOOL_INCLUDE: ${TOOL_INCLUDE:-}
      TOOL_EXCLUDE: ${TOOL_EXCLUDE:-}
      MCP_MAX_ARGS_LEN: ${MCP_MAX_ARGS_LEN:-2048}
      MCP_MAX_STDOUT_BYTES: ${MCP_MAX_STDOUT_BYTES:-1048576}
      MCP_MAX_STDERR_BYTES: ${MCP_MAX_STDERR_BYTES:-262144}
      MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD: ${MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD:-5}
      MCP_CIRCUIT_BREAKER_RECOVERY_TIMEOUT: ${MCP_CIRCUIT_BREAKER_RECOVERY_TIMEOUT:-60}
      MCP_HEALTH_CHECK_INTERVAL: ${MCP_HEALTH_CHECK_INTERVAL:-30}
      MCP_HEALTH_CPU_THRESHOLD: ${MCP_HEALTH_CPU_THRESHOLD:-80}
      MCP_HEALTH_MEMORY_THRESHOLD: ${MCP_HEALTH_MEMORY_THRESHOLD:-80}
      MCP_METRICS_ENABLED: ${MCP_METRICS_ENABLED:-true}
      MCP_METRICS_PROMETHEUS_ENABLED: ${MCP_METRICS_PROMETHEUS_ENABLED:-true}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      LOG_FORMAT: "${LOG_FORMAT:-%(asctime)s %(levelname)s %(name)s %(message)s}"

    # Use image-defined healthcheck; avoid drift with compose healthcheck
    # healthcheck: (removed)

    # Only keep depends_on if truly required. If so, prefer health-based condition:
    depends_on:
      prometheus:
        condition: service_healthy

    deploy:
      resources:
        limits:
          cpus: '${MCP_CPU_LIMIT:-2.0}'
          memory: ${MCP_MEMORY_LIMIT:-1G}

    labels:
      - "prometheus.io/scrape=true"
      - "prometheus.io/port=9090"
      - "prometheus.io/path=/metrics"
      - "traefik.enable=true"
      - "traefik.http.routers.mcp.rule=Host(`mcp.local`)"
      - "traefik.http.services.mcp.loadbalancer.server.port=8080"

  prometheus:
    container_name: prometheus
    image: prom/prometheus:${PROMETHEUS_VERSION:-v2.45.0}
    restart: unless-stopped
    networks:
      - mcp-internal
      - mcp-public
    ports:
      - "${PROMETHEUS_PORT:-9091}:9090"
    volumes:
      - ./docker/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./docker/alerts.yml:/etc/prometheus/alerts.yml:ro
      - prometheus-data:/prometheus:rw
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=30d'
      - '--storage.tsdb.retention.size=10GB'
      - '--web.console.libraries=/usr/share/prometheus/console_libraries'
      - '--web.console.templates=/usr/share/prometheus/consoles'
      - '--web.enable-lifecycle'
      - '--web.enable-admin-api'
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 1G
        reservations:
          cpus: '0.25'
          memory: 128M
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:9090/-/healthy"]
      interval: 30s
      timeout: 10s
      retries: 3
    labels:
      - "prometheus.io/scrape=false"

  grafana:
    container_name: grafana
    image: grafana/grafana:${GRAFANA_VERSION:-10.0.0}
    restart: unless-stopped
    networks:
      - mcp-public
      - mcp-internal
    ports:
      - "${GRAFANA_PORT:-3000}:3000"
    volumes:
      - grafana-data:/var/lib/grafana:rw
      - ./docker/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./docker/grafana/dashboards:/var/lib/grafana/dashboards:ro
    environment:
      GF_SECURITY_ADMIN_USER: ${GRAFANA_ADMIN_USER:-admin}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-admin}
      GF_INSTALL_PLUGINS: ${GRAFANA_PLUGINS:-}
      GF_SERVER_ROOT_URL: ${GRAFANA_ROOT_URL:-http://localhost:3000}
      GF_ANALYTICS_REPORTING_ENABLED: 'false'
      GF_ANALYTICS_CHECK_FOR_UPDATES: 'false'
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
        reservations:
          cpus: '0.25'
          memory: 128M
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:3000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    depends_on:
      - prometheus
    labels:
      - "prometheus.io/scrape=false"

  node-exporter:
    container_name: node-exporter
    image: prom/node-exporter:${NODE_EXPORTER_VERSION:-v1.6.0}
    restart: unless-stopped
    networks:
      - mcp-internal
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 128M
        reservations:
          cpus: '0.1'
          memory: 32M
    labels:
      - "prometheus.io/scrape=true"
      - "prometheus.io/port=9100"

  cadvisor:
    container_name: cadvisor
    image: gcr.io/cadvisor/cadvisor:${CADVISOR_VERSION:-v0.47.0}
    restart: unless-stopped
    networks:
      - mcp-internal
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    privileged: true
    devices:
      - /dev/kmsg
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
        reservations:
          cpus: '0.1'
          memory: 64M
    labels:
      - "prometheus.io/scrape=true"
      - "prometheus.io/port=8080"
```

---

## Drop-in replacement: docker/entrypoint.sh

```bash
#!/bin/bash
# =============================================================================
# MCP Server - Docker Entrypoint Script (hardened)
# =============================================================================

set -Eeuo pipefail

readonly SCRIPT_NAME="$(basename "$0")"
readonly MCP_HOME="${MCP_HOME:-/app}"
readonly MCP_CONFIG_PATH="${MCP_CONFIG_PATH:-/app/config/config.yaml}"
readonly MCP_LOG_PATH="${MCP_LOG_PATH:-/app/logs}"
readonly MCP_DATA_PATH="${MCP_DATA_PATH:-/app/data}"
readonly MCP_SERVER_SHUTDOWN_GRACE_PERIOD="${MCP_SERVER_SHUTDOWN_GRACE_PERIOD:-30}"
readonly MCP_UID=1000
readonly MCP_GID=1000

# Colors
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m'

log_info(){ echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn(){ echo -e "${YELLOW}[WARN]${NC} $*" >&2; }
log_error(){ echo -e "${RED}[ERROR]${NC} $*" >&2; }

shutdown_handler() {
  log_info "Received shutdown signal; initiating graceful shutdown..."
  if [[ -n "${MCP_PID:-}" ]]; then
    kill -TERM "${MCP_PID}" 2>/dev/null || true
    local timeout="${MCP_SERVER_SHUTDOWN_GRACE_PERIOD}"
    local count=0
    while kill -0 "${MCP_PID}" 2>/dev/null && [[ ${count} -lt ${timeout} ]]; do
      sleep 1; ((count++))
    done
    if kill -0 "${MCP_PID}" 2>/dev/null; then
      log_warn "Forcing shutdown after ${timeout}s..."
      kill -KILL "${MCP_PID}" 2>/dev/null || true
    fi
  fi
  log_info "Shutdown complete"
  exit 0
}
trap shutdown_handler SIGTERM SIGINT SIGQUIT

ensure_dirs() {
  mkdir -p "${MCP_HOME}" "${MCP_LOG_PATH}" "${MCP_DATA_PATH}" "$(dirname "${MCP_CONFIG_PATH}")"
}

ensure_ownership() {
  for dir in "${MCP_LOG_PATH}" "${MCP_DATA_PATH}" "$(dirname "${MCP_CONFIG_PATH}")"; do
    if [[ -d "${dir}" ]]; then
      # Only chown if not already owned by mcp to avoid churn
      if [[ "$(stat -c '%u:%g' "${dir}")" != "${MCP_UID}:${MCP_GID}" ]]; then
        log_info "Fixing ownership for ${dir}"
        chown -R "${MCP_UID}:${MCP_GID}" "${dir}" || log_warn "Could not chown ${dir}"
      fi
    fi
  done
}

validate_environment() {
  log_info "Validating environment..."
  local py_exec=""
  if command -v python >/dev/null 2>&1; then
    py_exec="$(command -v python)"
  elif command -v python3 >/dev/null 2>&1; then
    py_exec="$(command -v python3)"
  else
    log_error "Python is not installed in PATH"; exit 1
  fi
  PY_EXEC="${py_exec}"
  log_info "Using Python executable: ${PY_EXEC}"

  local tools=("nmap" "masscan" "gobuster")
  for t in "${tools[@]}"; do
    command -v "${t}" >/dev/null 2>&1 || log_warn "Tool not found: ${t}"
  done
  log_info "Environment validation complete"
}

generate_config() {
  log_info "Generating configuration..."
  local config_dir; config_dir="$(dirname "${MCP_CONFIG_PATH}")"
  local target_config="${MCP_CONFIG_PATH}"

  if [[ ! -w "${config_dir}" ]]; then
    log_warn "Config dir ${config_dir} not writable. Using fallback /app/config-local/config.yaml"
    mkdir -p /app/config-local
    target_config="/app/config-local/config.yaml"
    export MCP_CONFIG_PATH="${target_config}"
    log_warn "MCP_CONFIG_PATH overridden to ${MCP_CONFIG_PATH}"
  fi

  if [[ -f "${target_config}" ]]; then
    log_info "Using existing configuration: ${target_config}"
    return 0
  fi

  log_info "Creating configuration at ${target_config}"
  cat > "${target_config}" <<EOF
# Auto-generated configuration
# Generated at: $(date -u +"%Y-%m-%d %H:%M:%S UTC")

server:
  host: "${MCP_SERVER_HOST:-0.0.0.0}"
  port: ${MCP_SERVER_PORT:-8080}
  transport: "${MCP_SERVER_TRANSPORT:-http}"
  workers: ${MCP_SERVER_WORKERS:-1}
  max_connections: ${MCP_SERVER_MAX_CONNECTIONS:-100}
  shutdown_grace_period: ${MCP_SERVER_SHUTDOWN_GRACE_PERIOD:-30}

tool:
  default_timeout: ${MCP_DEFAULT_TIMEOUT_SEC:-300}
  default_concurrency: ${MCP_DEFAULT_CONCURRENCY:-2}

circuit_breaker:
  failure_threshold: ${MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD:-5}
  recovery_timeout: ${MCP_CIRCUIT_BREAKER_RECOVERY_TIMEOUT:-60}
  half_open_success_threshold: ${MCP_CIRCUIT_BREAKER_HALF_OPEN_SUCCESS_THRESHOLD:-1}

health:
  check_interval: ${MCP_HEALTH_CHECK_INTERVAL:-30}
  cpu_threshold: ${MCP_HEALTH_CPU_THRESHOLD:-80}
  memory_threshold: ${MCP_HEALTH_MEMORY_THRESHOLD:-80}
  disk_threshold: ${MCP_HEALTH_DISK_THRESHOLD:-80}
  timeout: ${MCP_HEALTH_TIMEOUT:-10}

metrics:
  enabled: ${MCP_METRICS_ENABLED:-true}
  prometheus_enabled: ${MCP_METRICS_PROMETHEUS_ENABLED:-true}
  collection_interval: ${MCP_METRICS_COLLECTION_INTERVAL:-15}

logging:
  level: "${LOG_LEVEL:-INFO}"
  format: "${LOG_FORMAT:-%(asctime)s %(levelname)s %(name)s %(message)s}"
  file_path: "${MCP_LOG_PATH}/mcp-server.log"
  max_file_size: ${MCP_LOGGING_MAX_FILE_SIZE:-10485760}
  backup_count: ${MCP_LOGGING_BACKUP_COUNT:-5}
EOF
  log_info "Configuration generated: ${target_config}"
}

run_migrations() {
  if [[ -n "${MCP_DATABASE_URL:-}" ]]; then
    log_info "Running database migrations..."
    # "${PY_EXEC}" -m mcp_server.migrations.migrate
    log_info "Database migrations complete"
  fi
}

wait_for_dependencies() {
  log_info "Checking dependencies..."
  if [[ "${MCP_METRICS_PROMETHEUS_ENABLED:-true}" == "true" ]]; then
    log_info "Waiting for Prometheus to be ready..."
    local max_attempts=30 attempt=0
    while [[ ${attempt} -lt ${max_attempts} ]]; do
      if command -v curl >/dev/null 2>&1 && curl -sf "http://prometheus:9090/-/ready" >/dev/null 2>&1; then
        log_info "Prometheus is ready"; break
      fi
      if command -v wget >/dev/null 2>&1 && wget -q --spider "http://prometheus:9090/-/ready"; then
        log_info "Prometheus is ready"; break
      fi
      ((attempt++)); sleep 2
    done
    if [[ ${attempt} -eq ${max_attempts} ]]; then
      log_warn "Prometheus did not become ready; continuing"
    fi
  fi
}

start_application() {
  log_info "Starting MCP Server..."
  export PYTHONPATH="${MCP_HOME}:${PYTHONPATH:-}"
  cd "${MCP_HOME}"
  local cmd=( "${PY_EXEC}" -m mcp_server.server )
  [[ "${DEVELOPMENT_MODE:-false}" == "true" ]] && log_warn "Running in DEVELOPMENT mode" && cmd+=( --debug )
  exec "${cmd[@]}"
}

main() {
  log_info "MCP Server Docker Entrypoint"
  log_info "Version: ${MCP_VERSION:-latest}"
  log_info "Environment: ${ENVIRONMENT:-production}"

  ensure_dirs
  ensure_ownership
  validate_environment
  generate_config
  run_migrations
  wait_for_dependencies

  # Drop privileges to mcp if running as root
  if [[ "$(id -u)" -eq 0 ]]; then
    log_info "Dropping privileges to mcp"
    exec gosu mcp:mcp bash -lc '
      set -Eeuo pipefail
      PY_EXEC="$(command -v python || command -v python3)"
      export PY_EXEC
      '"$(typeset -f log_info log_warn log_error shutdown_handler start_application)"'
      trap shutdown_handler SIGTERM SIGINT SIGQUIT
      start_application "$@"
    ' bash "$@"
  else
    start_application "$@"
  fi
}

main "$@"
```

Notes:
- We simplified the supervision: after dropping to mcp, we exec the app so it becomes the child of tini and receives signals directly. That removes the need to manually background and manage MCP_PID and ensures correct PID in process tables. If you do want a PID file, consider having the app write it.

---

## Drop-in replacement: docker/healthcheck.sh

```bash
#!/bin/bash
# =============================================================================
# MCP Server Health Check Script (hardened)
# =============================================================================

set -Eeuo pipefail

readonly HEALTH_ENDPOINT="${MCP_HEALTH_ENDPOINT:-http://localhost:8080/health}"
readonly TIMEOUT="${MCP_HEALTH_TIMEOUT:-10}"

if command -v wget >/dev/null 2>&1; then
  wget --quiet --tries=1 --timeout="${TIMEOUT}" --spider "${HEALTH_ENDPOINT}" >/dev/null 2>&1 && exit 0 || exit 1
elif command -v curl >/dev/null 2>&1; then
  curl -sf --connect-timeout "${TIMEOUT}" --max-time "${TIMEOUT}" "${HEALTH_ENDPOINT}" >/dev/null 2>&1 && exit 0 || exit 1
else
  exit 1
fi
```

---

## Final validation checklist

- **Build:** docker build -t mcp:local .
- **Start:** docker compose up -d; verify:
  - **Ownership:** Files in /app/config, /app/logs, /app/data are owned by 1000:1000.
  - **Config:** MCP_CONFIG_PATH points to the fallback when config dir is read-only; app reads it.
  - **Health:** mcp-server container transitions to healthy; /health responds.
  - **Grafana health:** Passes with wget-based check.
  - **Shutdown:** docker stop mcp-server gracefully exits within MCP_SERVER_SHUTDOWN_GRACE_PERIOD.
- **venv:** python resolves to /opt/venv/bin/python inside the container.
- **Pip modules:** python -c "import fastapi,uvicorn,pydantic,yaml,prometheus_client,structlog,aiofiles,aiodocker,httpx,requests,jsonschema,dateutil,cryptography,ipaddress,psutil" succeeds.

If you want, I can also add a minimal /health implementation stub in your app using FastAPI and expose /metrics via prometheus-client to ensure the healthcheck and metrics endpoints line up with this infra.

https://copilot.microsoft.com/shares/Vben4zhcpybCbMHidqUvj
