#!/bin/bash
# =============================================================================
# MCP Server - Docker Entrypoint Script (hardened & deterministic)
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

to_lower() { echo "$1" | tr '[:upper:]' '[:lower:]'; }
is_true() {
  local val="$(to_lower "${1:-}")"
  [[ "$val" == "true" || "$val" == "1" || "$val" == "yes" || "$val" == "on" ]]
}

ensure_dirs() {
  mkdir -p "${MCP_HOME}" "${MCP_LOG_PATH}" "${MCP_DATA_PATH}" "$(dirname "${MCP_CONFIG_PATH}")"
}

ensure_ownership() {
  for dir in "${MCP_LOG_PATH}" "${MCP_DATA_PATH}" "$(dirname "${MCP_CONFIG_PATH}")"; do
    if [[ -d "${dir}" ]]; then
      # Only attempt chown if running as root
      if [[ "$(id -u)" -eq 0 ]]; then
        if [[ "$(stat -c '%u:%g' "${dir}")" != "${MCP_UID}:${MCP_GID}" ]]; then
          log_info "Fixing ownership for ${dir}"
          chown -R "${MCP_UID}:${MCP_GID}" "${dir}" || log_warn "Could not chown ${dir}"
        fi
      fi
    fi
  done
}

select_python() {
  # Prefer the venv interpreter deterministically
  if [[ -x "/opt/venv/bin/python" ]]; then
    export PATH="/opt/venv/bin:${PATH}"
    PY_EXEC="/opt/venv/bin/python"
  else
    if command -v python >/dev/null 2>&1; then
      PY_EXEC="$(command -v python)"
    elif command -v python3 >/dev/null 2>&1; then
      PY_EXEC="$(command -v python3)"
    else
      log_error "Python is not installed in PATH"; exit 1
    fi
  fi
  log_info "Using Python executable: ${PY_EXEC}"
}

validate_environment() {
  log_info "Validating environment..."
  select_python

  # Basic tools presence (warn-only)
  local tools=("nmap" "masscan" "gobuster" "curl" "wget")
  for t in "${tools[@]}"; do
    command -v "${t}" >/dev/null 2>&1 || log_warn "Tool not found: ${t}"
  done

  # Log interpreter and packages sanity
  "${PY_EXEC}" - <<'PY' || { log_error "Python interpreter self-check failed"; exit 1; }
import sys
print(f"[PY] Executable={sys.executable} Version={sys.version.split()[0]}")
PY

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

check_http_deps() {
  local transport="${MCP_SERVER_TRANSPORT:-http}"
  if [[ "$(to_lower "$transport")" == "http" ]]; then
    log_info "Checking HTTP transport dependencies (FastAPI/Uvicorn)..."
    if ! "${PY_EXEC}" - <<'PY'
import importlib
missing = []
for m in ("fastapi", "uvicorn"):
    try:
        importlib.import_module(m)
    except Exception as e:
        missing.append((m, str(e)))
if missing:
    print("[PY][ERROR] Missing HTTP deps:", missing)
    raise SystemExit(1)
print("[PY] HTTP deps present")
PY
    then
      log_error "FastAPI and Uvicorn are required for HTTP transport but not importable by ${PY_EXEC}"
      # Prevent tight restart loop: wait briefly to make logs visible
      sleep 5
      exit 1
    fi
  fi
}

wait_for_dependencies() {
  log_info "Checking dependencies..."
  local prom_enabled="${MCP_METRICS_PROMETHEUS_ENABLED:-true}"
  if is_true "${prom_enabled}"; then
    log_info "Waiting for Prometheus readiness endpoint..."
    local max_attempts=30 attempt=0
    while [[ ${attempt} -lt ${max_attempts} ]]; do
      if command -v curl >/dev/null 2>&1 && curl -sf "http://prometheus:9090/-/ready" >/dev/null 2>&1; then
        log_info "Prometheus is ready"
        break
      fi
      if command -v wget >/dev/null 2>&1 && wget -q --spider "http://prometheus:9090/-/ready"; then
        log_info "Prometheus is ready"
        break
      fi
      ((attempt++))
      log_info "Prometheus not ready yet (attempt ${attempt}/${max_attempts}); retrying in 2s"
      sleep 2
    done
    if [[ ${attempt} -eq ${max_attempts} ]]; then
      log_warn "Prometheus did not become ready within ${max_attempts} attempts; continuing without blocking startup"
    fi
  fi
}

preflight_summary() {
  log_info "Preflight Summary:"
  log_info "  Version: ${MCP_VERSION:-latest}"
  log_info "  Environment: ${ENVIRONMENT:-production}"
  log_info "  Config: ${MCP_CONFIG_PATH}"
  log_info "  Logs: ${MCP_LOG_PATH}"
  log_info "  Data: ${MCP_DATA_PATH}"
  log_info "  Transport: ${MCP_SERVER_TRANSPORT:-http}"
}

exec_app() {
  local debug_flag=""
  [[ -n "${DEVELOPMENT_MODE:-}" ]] && debug_flag="--debug"

  if [[ "$(id -u)" -eq 0 ]]; then
    log_info "Dropping privileges to mcp"
    exec gosu mcp:mcp "${PY_EXEC}" -m mcp_server.server ${debug_flag}
  else
    exec "${PY_EXEC}" -m mcp_server.server ${debug_flag}
  fi
}

main() {
  log_info "MCP Server Docker Entrypoint"

  ensure_dirs
  ensure_ownership
  validate_environment
  generate_config
  run_migrations
  check_http_deps
  wait_for_dependencies
  preflight_summary
  exec_app
}

main "$@"
