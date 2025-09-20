#!/bin/bash
# =============================================================================
# MCP Server - Docker Entrypoint Script (updated)
# =============================================================================
# Robust initialization, config generation (writable fallback), and startup
# =============================================================================

set -euo pipefail

readonly SCRIPT_NAME="$(basename "$0")"
readonly MCP_HOME="${MCP_HOME:-/app}"
readonly MCP_CONFIG_PATH="${MCP_CONFIG_PATH:-/app/config/config.yaml}"
readonly MCP_LOG_PATH="${MCP_LOG_PATH:-/app/logs}"
readonly MCP_DATA_PATH="${MCP_DATA_PATH:-/app/data}"
readonly MCP_SERVER_SHUTDOWN_GRACE_PERIOD="${MCP_SERVER_SHUTDOWN_GRACE_PERIOD:-30}"

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*" >&2
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

# -----------------------------------------------------------------------------
# Signal Handlers
# -----------------------------------------------------------------------------
shutdown_handler() {
    log_info "Received shutdown signal, initiating graceful shutdown..."

    if [[ -n "${MCP_PID:-}" ]]; then
        log_info "Stopping MCP Server (PID: ${MCP_PID})..."
        kill -TERM "${MCP_PID}" 2>/dev/null || true

        local timeout="${MCP_SERVER_SHUTDOWN_GRACE_PERIOD}"
        local count=0

        while kill -0 "${MCP_PID}" 2>/dev/null && [[ ${count} -lt ${timeout} ]]; do
            sleep 1
            ((count++))
        done

        if kill -0 "${MCP_PID}" 2>/dev/null; then
            log_warn "Forcing shutdown after ${timeout} seconds..."
            kill -KILL "${MCP_PID}" 2>/dev/null || true
        fi
    fi

    log_info "Shutdown complete"
    exit 0
}

trap shutdown_handler SIGTERM SIGINT SIGQUIT

# -----------------------------------------------------------------------------
# Environment Validation
# -----------------------------------------------------------------------------
validate_environment() {
    log_info "Validating environment..."

    # Ensure core directories exist
    for dir in "${MCP_HOME}" "${MCP_LOG_PATH}" "${MCP_DATA_PATH}"; do
        if [[ ! -d "${dir}" ]]; then
            log_error "Required directory does not exist: ${dir}"
            exit 1
        fi
        if [[ ! -w "${dir}" ]]; then
            log_error "Directory is not writable: ${dir}"
            exit 1
        fi
    done

    # MCP config directory: may be read-only if user mounted config; warn but don't fail
    local config_dir
    config_dir="$(dirname "${MCP_CONFIG_PATH}")"
    if [[ ! -d "${config_dir}" ]]; then
        log_warn "Config directory does not exist: ${config_dir} (it will be created if writable fallback used)"
    fi
    if [[ ! -w "${config_dir}" ]]; then
        log_warn "Config directory is not writable: ${config_dir} (entrypoint will use fallback if needed)"
    fi

    # Check Python: accept 'python' or 'python3'
    if command -v python >/dev/null 2>&1; then
        PY_EXEC="$(command -v python)"
    elif command -v python3 >/dev/null 2>&1; then
        PY_EXEC="$(command -v python3)"
    else
        log_error "Python is not installed in the container PATH"
        exit 1
    fi
    log_info "Using Python executable: ${PY_EXEC}"

    # Check required tools (warn if missing)
    local required_tools=("nmap" "masscan" "gobuster")
    for tool in "${required_tools[@]}"; do
        if ! command -v "${tool}" >/dev/null 2>&1; then
            log_warn "Tool not found: ${tool} (some features may be unavailable)"
        fi
    done

    log_info "Environment validation complete"
}

# -----------------------------------------------------------------------------
# Configuration Generation
# -----------------------------------------------------------------------------
generate_config() {
    log_info "Generating configuration..."

    local config_dir
    config_dir="$(dirname "${MCP_CONFIG_PATH}")"

    # Determine target config path: prefer configured path if writable, else fallback
    if [[ -w "${config_dir}" ]]; then
        TARGET_CONFIG="${MCP_CONFIG_PATH}"
    else
        log_warn "Config directory ${config_dir} not writable. Using fallback /app/config-local/config.yaml"
        mkdir -p /app/config-local
        TARGET_CONFIG="/app/config-local/config.yaml"
    fi

    if [[ -f "${TARGET_CONFIG}" ]]; then
        log_info "Using existing configuration: ${TARGET_CONFIG}"
        return 0
    fi

    log_info "Creating configuration at ${TARGET_CONFIG}"
    cat > "${TARGET_CONFIG}" <<EOF
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

    log_info "Configuration generated: ${TARGET_CONFIG}"
}

# -----------------------------------------------------------------------------
# Database Migrations (Optional)
# -----------------------------------------------------------------------------
run_migrations() {
    if [[ -n "${MCP_DATABASE_URL:-}" ]]; then
        log_info "Running database migrations..."
        # If migrations are implemented, call them here
        # "${PY_EXEC}" -m mcp_server.migrations.migrate
        log_info "Database migrations complete"
    fi
}

# -----------------------------------------------------------------------------
# Dependency Wait (optional)
# -----------------------------------------------------------------------------
wait_for_dependencies() {
    log_info "Checking dependencies..."
    if [[ "${MCP_METRICS_PROMETHEUS_ENABLED:-true}" == "true" ]]; then
        log_info "Waiting for Prometheus to be ready..."
        local max_attempts=30
        local attempt=0
        while [[ ${attempt} -lt ${max_attempts} ]]; do
            if command -v curl >/dev/null 2>&1 && curl -sf "http://prometheus:9090/-/ready" >/dev/null 2>&1; then
                log_info "Prometheus is ready"
                break
            fi
            if command -v wget >/dev/null 2>&1 && wget -q --spider "http://prometheus:9090/-/ready" >/dev/null 2>&1; then
                log_info "Prometheus is ready"
                break
            fi
            ((attempt++))
            sleep 2
        done

        if [[ ${attempt} -eq ${max_attempts} ]]; then
            log_warn "Prometheus did not become ready after ${max_attempts} attempts; continuing"
        fi
    fi
}

# -----------------------------------------------------------------------------
# Application Startup
# -----------------------------------------------------------------------------
start_application() {
    log_info "Starting MCP Server..."

    export PYTHONPATH="${MCP_HOME}:${PYTHONPATH:-}"

    cd "${MCP_HOME}"

    if [[ "${DEVELOPMENT_MODE:-false}" == "true" ]]; then
        log_warn "Running in DEVELOPMENT mode"
        exec "${PY_EXEC}" -m mcp_server.server --debug "$@"
    else
        exec "${PY_EXEC}" -m mcp_server.server "$@"
    fi
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
main() {
    log_info "MCP Server Docker Entrypoint"
    log_info "Version: ${MCP_VERSION:-latest}"
    log_info "Environment: ${ENVIRONMENT:-production}"

    validate_environment
    generate_config
    run_migrations
    wait_for_dependencies

    # Create PID file
    echo $$ > "${MCP_DATA_PATH}/mcp-server.pid"

    # Start application in background so we can capture PID and handle signals
    start_application "$@" &
    MCP_PID=$!

    log_info "MCP Server started with PID: ${MCP_PID}"

    # Wait for application to exit and forward exit code
    wait "${MCP_PID}"
    EXIT_CODE=$?

    log_info "MCP Server exited with code: ${EXIT_CODE}"
    exit ${EXIT_CODE}
}

main "$@"
