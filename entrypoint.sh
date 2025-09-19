#!/bin/bash
# =============================================================================
# MCP Server - Docker Entrypoint Script
# =============================================================================
# Initialization, configuration, and startup orchestration
# =============================================================================

set -e  # Exit on error
set -u  # Exit on undefined variable
set -o pipefail  # Exit on pipe failure

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
readonly SCRIPT_NAME="$(basename "$0")"
readonly MCP_HOME="${MCP_HOME:-/app}"
readonly MCP_CONFIG_PATH="${MCP_CONFIG_PATH:-/app/config/config.yaml}"
readonly MCP_LOG_PATH="${MCP_LOG_PATH:-/app/logs}"
readonly MCP_DATA_PATH="${MCP_DATA_PATH:-/app/data}"

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m' # No Color

# -----------------------------------------------------------------------------
# Logging Functions
# -----------------------------------------------------------------------------
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
    
    # Send SIGTERM to all processes
    if [[ -n "${MCP_PID:-}" ]]; then
        log_info "Stopping MCP Server (PID: ${MCP_PID})..."
        kill -TERM "${MCP_PID}" 2>/dev/null || true
        
        # Wait for graceful shutdown
        local timeout="${MCP_SERVER_SHUTDOWN_GRACE_PERIOD:-30}"
        local count=0
        
        while kill -0 "${MCP_PID}" 2>/dev/null && [[ ${count} -lt ${timeout} ]]; do
            sleep 1
            ((count++))
        done
        
        # Force kill if still running
        if kill -0 "${MCP_PID}" 2>/dev/null; then
            log_warn "Forcing shutdown after ${timeout} seconds..."
            kill -KILL "${MCP_PID}" 2>/dev/null || true
        fi
    fi
    
    log_info "Shutdown complete"
    exit 0
}

# Set up signal handlers
trap shutdown_handler SIGTERM SIGINT SIGQUIT

# -----------------------------------------------------------------------------
# Environment Validation
# -----------------------------------------------------------------------------
validate_environment() {
    log_info "Validating environment..."
    
    # Check required directories
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
    
    # Check Python installation
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed"
        exit 1
    fi
    
    # Check required tools
    local required_tools=("nmap" "masscan" "gobuster")
    for tool in "${required_tools[@]}"; do
        if ! command -v "${tool}" &> /dev/null; then
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
    
    # Check if config exists
    if [[ -f "${MCP_CONFIG_PATH}" ]]; then
        log_info "Using existing configuration: ${MCP_CONFIG_PATH}"
        return 0
    fi
    
    # Generate config from environment variables
    log_info "Generating configuration from environment variables..."
    
    cat > "${MCP_CONFIG_PATH}" <<EOF
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
    
    log_info "Configuration generated: ${MCP_CONFIG_PATH}"
}

# -----------------------------------------------------------------------------
# Database Migration (Optional)
# -----------------------------------------------------------------------------
run_migrations() {
    if [[ -n "${MCP_DATABASE_URL:-}" ]]; then
        log_info "Running database migrations..."
        
        # Add migration logic here if needed
        # python -m mcp_server.migrations.migrate
        
        log_info "Database migrations complete"
    fi
}

# -----------------------------------------------------------------------------
# Health Check Wait
# -----------------------------------------------------------------------------
wait_for_dependencies() {
    log_info "Checking dependencies..."
    
    # Wait for Prometheus if metrics are enabled
    if [[ "${MCP_METRICS_PROMETHEUS_ENABLED:-true}" == "true" ]]; then
        log_info "Waiting for Prometheus..."
        
        local max_attempts=30
        local attempt=0
        
        while [[ ${attempt} -lt ${max_attempts} ]]; do
            if curl -sf "http://prometheus:9090/-/ready" > /dev/null 2>&1; then
                log_info "Prometheus is ready"
                break
            fi
            
            ((attempt++))
            sleep 2
        done
        
        if [[ ${attempt} -eq ${max_attempts} ]]; then
            log_warn "Prometheus is not ready after ${max_attempts} attempts (continuing anyway)"
        fi
    fi
}

# -----------------------------------------------------------------------------
# Application Startup
# -----------------------------------------------------------------------------
start_application() {
    log_info "Starting MCP Server..."
    
    # Set Python path
    export PYTHONPATH="${MCP_HOME}:${PYTHONPATH:-}"
    
    # Change to application directory
    cd "${MCP_HOME}"
    
    # Start the application
    if [[ "${DEVELOPMENT_MODE:-false}" == "true" ]]; then
        log_warn "Running in DEVELOPMENT mode"
        exec python -m mcp_server.server --debug "$@"
    else
        exec python -m mcp_server.server "$@"
    fi
}

# -----------------------------------------------------------------------------
# Main Execution
# -----------------------------------------------------------------------------
main() {
    log_info "MCP Server Docker Entrypoint"
    log_info "Version: ${MCP_VERSION:-latest}"
    log_info "Environment: ${ENVIRONMENT:-production}"
    
    # Validate environment
    validate_environment
    
    # Generate or validate configuration
    generate_config
    
    # Run database migrations if needed
    run_migrations
    
    # Wait for dependencies
    wait_for_dependencies
    
    # Create PID file
    echo $$ > "${MCP_DATA_PATH}/mcp-server.pid"
    
    # Start application (exec replaces shell with Python process)
    start_application "$@" &
    MCP_PID=$!
    
    log_info "MCP Server started with PID: ${MCP_PID}"
    
    # Wait for application to exit
    wait "${MCP_PID}"
    EXIT_CODE=$?
    
    log_info "MCP Server exited with code: ${EXIT_CODE}"
    exit ${EXIT_CODE}
}

# Execute main function
main "$@"
