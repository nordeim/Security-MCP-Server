# .env.example
```example
# ============================================================================
# MCP Server Configuration Template
# ============================================================================
# This file contains all configuration options for the MCP (Machine Control Protocol) Server
# Copy this file to .env and adjust values as needed for your environment
# 
# SECURITY WARNING: Never commit .env files with actual credentials to version control
# ============================================================================

# ============================================================================
# SERVER CONFIGURATION
# ============================================================================

# Server transport mode: "stdio" (standard I/O) or "http" (REST API)
# Default: stdio
MCP_SERVER_TRANSPORT=stdio

# HTTP server host (only used when transport=http)
# Default: 0.0.0.0 (all interfaces)
# For security, consider binding to 127.0.0.1 in production
MCP_SERVER_HOST=0.0.0.0

# HTTP server port (only used when transport=http)
# Default: 8080
MCP_SERVER_PORT=8080

# Maximum number of concurrent connections (HTTP transport)
# Default: 100
MCP_SERVER_MAX_CONNECTIONS=100

# Number of worker processes (HTTP transport)
# Default: 1
MCP_SERVER_WORKERS=1

# Graceful shutdown timeout in seconds
# Time to wait for active connections to close before forcing shutdown
# Default: 30
MCP_SERVER_SHUTDOWN_GRACE_PERIOD=30

# ============================================================================
# TOOL CONFIGURATION
# ============================================================================

# Python package path containing tool implementations
# Default: mcp_server.tools
TOOLS_PACKAGE=mcp_server.tools

# Comma-separated list of tool names to include (whitelist)
# Leave empty to include all available tools
# Example: NmapTool,MasscanTool
TOOL_INCLUDE=

# Comma-separated list of tool names to exclude (blacklist)
# Example: GobusterTool
TOOL_EXCLUDE=

# Default timeout for tool execution in seconds
# Can be overridden per tool or per execution
# Default: 300 (5 minutes)
MCP_DEFAULT_TIMEOUT_SEC=300

# Default concurrency limit for tools (number of simultaneous executions)
# Default: 2
MCP_DEFAULT_CONCURRENCY=2

# ============================================================================
# SECURITY CONFIGURATION
# ============================================================================

# Maximum length of tool arguments in bytes
# Prevents excessive memory usage from malformed requests
# Default: 2048
MCP_MAX_ARGS_LEN=2048

# Maximum stdout capture size in bytes (1 MiB)
# Default: 1048576
MCP_MAX_STDOUT_BYTES=1048576

# Maximum stderr capture size in bytes (256 KiB)
# Default: 262144
MCP_MAX_STDERR_BYTES=262144

# Allowed target patterns (comma-separated)
# Default: RFC1918,.lab.internal
MCP_SECURITY_ALLOWED_TARGETS=RFC1918,.lab.internal

# ============================================================================
# CIRCUIT BREAKER CONFIGURATION
# ============================================================================

# Number of failures before circuit opens
# Default: 5
MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5

# Recovery timeout in seconds after circuit opens
# Default: 60.0
MCP_CIRCUIT_BREAKER_RECOVERY_TIMEOUT=60.0

# Number of successes in half-open state before closing
# Default: 1
MCP_CIRCUIT_BREAKER_HALF_OPEN_SUCCESS_THRESHOLD=1

# ============================================================================
# HEALTH CHECK CONFIGURATION
# ============================================================================

# Health check interval in seconds
# Default: 30.0
MCP_HEALTH_CHECK_INTERVAL=30.0

# CPU usage threshold for health warnings (percentage)
# Default: 80.0
MCP_HEALTH_CPU_THRESHOLD=80.0

# Memory usage threshold for health warnings (percentage)
# Default: 80.0
MCP_HEALTH_MEMORY_THRESHOLD=80.0

# Disk usage threshold for health warnings (percentage)
# Default: 80.0
MCP_HEALTH_DISK_THRESHOLD=80.0

# Health check timeout in seconds
# Default: 10.0
MCP_HEALTH_TIMEOUT=10.0

# Comma-separated list of Python modules to check as dependencies
# Example: psutil,prometheus_client
MCP_HEALTH_DEPENDENCIES=

# ============================================================================
# METRICS CONFIGURATION
# ============================================================================

# Enable metrics collection
# Default: true
MCP_METRICS_ENABLED=true

# Enable Prometheus metrics endpoint
# Default: true
MCP_METRICS_PROMETHEUS_ENABLED=true

# Prometheus metrics port (when running separately)
# Default: 9090
MCP_METRICS_PROMETHEUS_PORT=9090

# Metrics collection interval in seconds
# Default: 15.0
MCP_METRICS_COLLECTION_INTERVAL=15.0

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

# Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL
# Default: INFO
LOG_LEVEL=INFO

# Log format string (Python logging format)
# Default: %(asctime)s %(levelname)s %(name)s %(message)s
LOG_FORMAT=%(asctime)s %(levelname)s %(name)s %(message)s

# Log file path (optional, logs to stdout if not set)
# Example: /var/log/mcp-server/mcp.log
MCP_LOGGING_FILE_PATH=

# Maximum log file size in bytes (10 MB)
# Default: 10485760
MCP_LOGGING_MAX_FILE_SIZE=10485760

# Number of log file backups to keep
# Default: 5
MCP_LOGGING_BACKUP_COUNT=5

# ============================================================================
# DATABASE CONFIGURATION (Optional)
# ============================================================================

# Database connection URL (if using database features)
# Example: postgresql://user:pass@localhost/mcp_db
# Default: empty (no database)
MCP_DATABASE_URL=

# Database connection pool size
# Default: 10
MCP_DATABASE_POOL_SIZE=10

# Maximum overflow connections above pool_size
# Default: 20
MCP_DATABASE_MAX_OVERFLOW=20

# Pool connection timeout in seconds
# Default: 30
MCP_DATABASE_POOL_TIMEOUT=30

# Time to recycle connections in seconds
# Default: 3600 (1 hour)
MCP_DATABASE_POOL_RECYCLE=3600

# ============================================================================
# DEVELOPMENT/DEBUG SETTINGS
# ============================================================================

# Enable debug mode (verbose logging, additional checks)
# WARNING: Never enable in production
# Default: false
DEBUG=false

# Enable development mode (auto-reload, debug endpoints)
# WARNING: Never enable in production
# Default: false
DEVELOPMENT_MODE=false

# ============================================================================
# OPTIONAL PERFORMANCE TUNING
# ============================================================================

# Enable uvloop for better async performance (if installed)
# Default: auto-detect
USE_UVLOOP=auto

# ============================================================================
# TOOL-SPECIFIC OVERRIDES (Optional)
# ============================================================================

# Override settings for specific tools
# Format: TOOL_<TOOLNAME>_<SETTING>=value

# Example: Custom timeout for Nmap tool (seconds)
# TOOL_NMAP_TIMEOUT=600

# Example: Custom concurrency for Masscan tool
# TOOL_MASSCAN_CONCURRENCY=1

# Example: Custom rate limit for Masscan
# TOOL_MASSCAN_RATE=1000

# ============================================================================
# NOTES
# ============================================================================
# 1. All timeout values are in seconds unless specified otherwise
# 2. All size limits are in bytes unless specified otherwise
# 3. Percentage thresholds should be between 0.0 and 100.0
# 4. Boolean values: true/false, yes/no, 1/0 are accepted
# 5. Empty values use the documented defaults
# 6. Comments starting with # are ignored
# ============================================================================

```

# Dockerfile
```txt
# =============================================================================
# MCP Server - Production Dockerfile
# =============================================================================
# Multi-stage build for security and size optimization
# Final image size: ~150MB (from ~900MB)
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Python Builder
# -----------------------------------------------------------------------------
FROM python:3.12-slim-trixie AS python-builder

# Build arguments for flexibility
ARG PYTHON_VERSION=3.12
ARG PIP_VERSION=23.3.1
ARG SETUPTOOLS_VERSION=69.0.2

# Install build dependencies
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

# Install Python dependencies
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# -----------------------------------------------------------------------------
# Stage 2: Tool Builder
# -----------------------------------------------------------------------------
FROM ubuntu:22.04 AS tool-builder

# Install security tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap \
    masscan \
    gobuster \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Download and verify tool signatures (example for gobuster)
RUN mkdir -p /opt/tools/bin

# -----------------------------------------------------------------------------
# Stage 3: Final Production Image
# -----------------------------------------------------------------------------
FROM python:3.12-slim-trixie

# Metadata
LABEL maintainer="MCP Server Team"
LABEL version="2.0.0"
LABEL description="Production MCP Server with security tools"
LABEL org.opencontainers.image.source="https://github.com/org/mcp-server"
LABEL org.opencontainers.image.vendor="MCP"
LABEL org.opencontainers.image.licenses="MIT"

# Security: Create non-root user
RUN groupadd -r mcp --gid=1000 && \
    useradd -r -g mcp --uid=1000 --home-dir=/app --shell=/bin/bash mcp

# Install runtime dependencies and security tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap \
    masscan \
    gobuster \
    curl \
    ca-certificates \
    libssl-dev \
    libffi-dev \
    tini \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /tmp/* \
    && rm -rf /var/tmp/*

# Copy virtual environment from builder
COPY --from=python-builder /opt/venv /opt/venv

# Set environment variables
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=UTF-8 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=UTC \
    MCP_HOME=/app \
    MCP_CONFIG_PATH=/app/config/config.yaml \
    MCP_LOG_PATH=/app/logs

# Create application directories
RUN mkdir -p /app/config /app/logs /app/data /app/scripts && \
    chown -R mcp:mcp /app

# Set working directory
WORKDIR /app

# Copy application code
COPY --chown=mcp:mcp mcp_server/ /app/mcp_server/
COPY --chown=mcp:mcp scripts/ /app/scripts/
COPY --chown=mcp:mcp config/ /app/config/

# Copy entrypoint and health check scripts
COPY --chown=mcp:mcp docker/entrypoint.sh /entrypoint.sh
COPY --chown=mcp:mcp docker/healthcheck.sh /healthcheck.sh
RUN chmod +x /entrypoint.sh /healthcheck.sh

# Security: Set proper permissions
RUN chmod -R 750 /app && \
    chmod -R 640 /app/config/* && \
    chmod -R 660 /app/logs && \
    chmod -R 660 /app/data

# Create volume mount points
VOLUME ["/app/config", "/app/logs", "/app/data"]

# Expose ports
EXPOSE 8080 9090

# Switch to non-root user
USER mcp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["/healthcheck.sh"]

# Use tini for proper signal handling
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]

# Default command
CMD ["python", "-m", "mcp_server.server"]

```

# docker-compose.override.yml
```yml
# =============================================================================
# Development Override Configuration
# =============================================================================
# Use for local development: docker-compose up
# Automatically loaded by docker-compose
# =============================================================================

version: '3.8'

services:
  mcp-server:
    # Use local build for development
    build:
      context: .
      dockerfile: Dockerfile
      cache_from:
        - mcp-server:latest
    
    # Mount source code for hot reload
    volumes:
      - ./mcp_server:/app/mcp_server:ro
      - ./tests:/app/tests:ro
      - ./scripts:/app/scripts:ro
      - ./config:/app/config:ro
    
    # Development environment variables
    environment:
      DEVELOPMENT_MODE: 'true'
      DEBUG: 'true'
      LOG_LEVEL: DEBUG
      # Disable production optimizations
      PYTHONUNBUFFERED: '1'
      PYTHONDONTWRITEBYTECODE: '1'
    
    # Exposed ports for debugging
    ports:
      - "8080:8080"    # API
      - "9090:9090"    # Metrics
      - "5678:5678"    # Python debugger
    
    # Override command for development
    command: ["python", "-m", "debugpy", "--listen", "0.0.0.0:5678", "-m", "mcp_server.server"]
    
    # Disable resource limits in development
    deploy:
      resources:
        limits:
          cpus: '4.0'
          memory: 2G

  prometheus:
    # Development Prometheus config
    volumes:
      - ./docker/prometheus-dev.yml:/etc/prometheus/prometheus.yml:ro
    
    # More verbose logging
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/usr/share/prometheus/console_libraries'
      - '--web.console.templates=/usr/share/prometheus/consoles'
      - '--web.enable-lifecycle'
      - '--web.enable-admin-api'
      - '--log.level=debug'

```

# docker-compose.yml
```yml
# =============================================================================
# MCP Server - Docker Compose Stack
# =============================================================================
# Production-ready orchestration with monitoring and observability
# =============================================================================

version: '3.8'

# =============================================================================
# Networks
# =============================================================================
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

# =============================================================================
# Volumes
# =============================================================================
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

# =============================================================================
# Services
# =============================================================================
services:
  # ---------------------------------------------------------------------------
  # MCP Server - Main Application
  # ---------------------------------------------------------------------------
  mcp-server:
    container_name: mcp-server
    image: mcp-server:${MCP_VERSION:-latest}
    build:
      context: .
      dockerfile: Dockerfile
      args:
        PYTHON_VERSION: ${PYTHON_VERSION:-3.12}
    
    restart: unless-stopped
    
    networks:
      - mcp-public
      - mcp-internal
    
    ports:
      - "${MCP_SERVER_PORT:-8080}:8080"
      - "${MCP_METRICS_PORT:-9090}:9090"
    
    volumes:
      - mcp-config:/app/config:ro
      - mcp-logs:/app/logs:rw
      - mcp-data:/app/data:rw
      - ./config:/app/config-local:ro
    
    environment:
      # Server configuration
      MCP_SERVER_TRANSPORT: ${MCP_SERVER_TRANSPORT:-http}
      MCP_SERVER_HOST: 0.0.0.0
      MCP_SERVER_PORT: ${MCP_SERVER_PORT:-8080}
      
      # Tool configuration
      TOOLS_PACKAGE: ${TOOLS_PACKAGE:-mcp_server.tools}
      TOOL_INCLUDE: ${TOOL_INCLUDE:-}
      TOOL_EXCLUDE: ${TOOL_EXCLUDE:-}
      
      # Security settings
      MCP_MAX_ARGS_LEN: ${MCP_MAX_ARGS_LEN:-2048}
      MCP_MAX_STDOUT_BYTES: ${MCP_MAX_STDOUT_BYTES:-1048576}
      MCP_MAX_STDERR_BYTES: ${MCP_MAX_STDERR_BYTES:-262144}
      
      # Circuit breaker
      MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD: ${MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD:-5}
      MCP_CIRCUIT_BREAKER_RECOVERY_TIMEOUT: ${MCP_CIRCUIT_BREAKER_RECOVERY_TIMEOUT:-60}
      
      # Health checks
      MCP_HEALTH_CHECK_INTERVAL: ${MCP_HEALTH_CHECK_INTERVAL:-30}
      MCP_HEALTH_CPU_THRESHOLD: ${MCP_HEALTH_CPU_THRESHOLD:-80}
      MCP_HEALTH_MEMORY_THRESHOLD: ${MCP_HEALTH_MEMORY_THRESHOLD:-80}
      
      # Metrics
      MCP_METRICS_ENABLED: ${MCP_METRICS_ENABLED:-true}
      MCP_METRICS_PROMETHEUS_ENABLED: ${MCP_METRICS_PROMETHEUS_ENABLED:-true}
      
      # Logging
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      LOG_FORMAT: ${LOG_FORMAT:-%(asctime)s %(levelname)s %(name)s %(message)s}
    
    deploy:
      resources:
        limits:
          cpus: '${MCP_CPU_LIMIT:-2.0}'
          memory: ${MCP_MEMORY_LIMIT:-1G}
        reservations:
          cpus: '${MCP_CPU_RESERVATION:-0.5}'
          memory: ${MCP_MEMORY_RESERVATION:-256M}
    
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    
    depends_on:
      - prometheus
    
    labels:
      - "prometheus.io/scrape=true"
      - "prometheus.io/port=9090"
      - "prometheus.io/path=/metrics"
      - "traefik.enable=true"
      - "traefik.http.routers.mcp.rule=Host(`mcp.local`)"
      - "traefik.http.services.mcp.loadbalancer.server.port=8080"

  # ---------------------------------------------------------------------------
  # Prometheus - Metrics Collection
  # ---------------------------------------------------------------------------
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

  # ---------------------------------------------------------------------------
  # Grafana - Visualization (Optional)
  # ---------------------------------------------------------------------------
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
      test: ["CMD-SHELL", "curl -f http://localhost:3000/api/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
    
    depends_on:
      - prometheus
    
    labels:
      - "prometheus.io/scrape=false"

  # ---------------------------------------------------------------------------
  # Node Exporter - Host Metrics (Optional)
  # ---------------------------------------------------------------------------
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

  # ---------------------------------------------------------------------------
  # Cadvisor - Container Metrics (Optional)
  # ---------------------------------------------------------------------------
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

# docker/entrypoint.sh
```sh
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

```

# docker/healthcheck.sh
```sh
#!/bin/bash
# =============================================================================
# MCP Server Health Check Script
# =============================================================================
# Used by Docker HEALTHCHECK instruction
# =============================================================================

set -e

# Configuration
readonly HEALTH_ENDPOINT="${HEALTH_ENDPOINT:-http://localhost:8080/health}"
readonly TIMEOUT="${HEALTH_CHECK_TIMEOUT:-10}"

# Perform health check
if curl -sf --max-time "${TIMEOUT}" "${HEALTH_ENDPOINT}" > /dev/null; then
    exit 0  # Healthy
else
    exit 1  # Unhealthy
fi

```

# docker/prometheus.yml
```yml
# =============================================================================
# Prometheus Configuration for MCP Server
# =============================================================================
# Metrics collection and monitoring configuration
# =============================================================================

# -----------------------------------------------------------------------------
# Global Configuration
# -----------------------------------------------------------------------------
global:
  # How frequently to scrape targets
  scrape_interval: 15s
  
  # How frequently to evaluate rules
  evaluation_interval: 15s
  
  # Scrape timeout
  scrape_timeout: 10s
  
  # External labels to attach to metrics
  external_labels:
    monitor: 'mcp-monitor'
    environment: 'production'
    region: 'us-east-1'

# -----------------------------------------------------------------------------
# Alertmanager Configuration
# -----------------------------------------------------------------------------
alerting:
  alertmanagers:
    - static_configs:
        - targets:
          # - 'alertmanager:9093'
      # Timeout for sending alerts
      timeout: 10s
      # Path prefix for Alertmanager
      path_prefix: /alertmanager

# -----------------------------------------------------------------------------
# Rule Files
# -----------------------------------------------------------------------------
rule_files:
  - '/etc/prometheus/alerts.yml'
  # - '/etc/prometheus/recording_rules.yml'

# -----------------------------------------------------------------------------
# Scrape Configurations
# -----------------------------------------------------------------------------
scrape_configs:
  # ---------------------------------------------------------------------------
  # Prometheus Self-Monitoring
  # ---------------------------------------------------------------------------
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']
    metrics_path: /metrics
    scrape_interval: 10s
    
    # Metadata labels
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        replacement: 'prometheus'

  # ---------------------------------------------------------------------------
  # MCP Server Metrics
  # ---------------------------------------------------------------------------
  - job_name: 'mcp-server'
    static_configs:
      - targets: ['mcp-server:9090']
    metrics_path: /metrics
    scrape_interval: 15s
    scrape_timeout: 10s
    
    # Add custom labels
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        replacement: 'mcp-server-primary'
      - target_label: service
        replacement: 'mcp'
      - target_label: component
        replacement: 'server'
    
    # Metric relabeling
    metric_relabel_configs:
      # Drop debug metrics in production
      - source_labels: [__name__]
        regex: 'debug_.*'
        action: drop
      
      # Keep only important metrics
      - source_labels: [__name__]
        regex: '(mcp_tool_execution_.*|mcp_health_.*|mcp_circuit_breaker_.*|up)'
        action: keep

  # ---------------------------------------------------------------------------
  # Node Exporter (Host Metrics)
  # ---------------------------------------------------------------------------
  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
    scrape_interval: 30s
    
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        replacement: 'docker-host'
      - target_label: job
        replacement: 'node'

  # ---------------------------------------------------------------------------
  # cAdvisor (Container Metrics)
  # ---------------------------------------------------------------------------
  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
    scrape_interval: 30s
    
    # Container-specific relabeling
    metric_relabel_configs:
      # Extract container name
      - source_labels: [container_label_com_docker_compose_service]
        target_label: service
      
      # Keep only relevant container metrics
      - source_labels: [__name__]
        regex: 'container_(cpu|memory|network|disk)_.*'
        action: keep
      
      # Drop metrics for pause containers
      - source_labels: [container_name]
        regex: 'POD|pause'
        action: drop

  # ---------------------------------------------------------------------------
  # Grafana Metrics (Optional)
  # ---------------------------------------------------------------------------
  - job_name: 'grafana'
    static_configs:
      - targets: ['grafana:3000']
    metrics_path: /metrics
    scrape_interval: 30s
    
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        replacement: 'grafana'

  # ---------------------------------------------------------------------------
  # Service Discovery for Docker Swarm (Optional)
  # ---------------------------------------------------------------------------
  # - job_name: 'docker-swarm'
  #   dockerswarm_sd_configs:
  #     - host: unix:///var/run/docker.sock
  #       role: tasks
  #   
  #   relabel_configs:
  #     # Only keep containers with prometheus labels
  #     - source_labels: [__meta_docker_container_label_prometheus_io_scrape]
  #       regex: 'true'
  #       action: keep
  #     
  #     # Use container label for job name
  #     - source_labels: [__meta_docker_container_label_prometheus_io_job]
  #       target_label: job
  #     
  #     # Use container name as instance
  #     - source_labels: [__meta_docker_container_name]
  #       target_label: instance

  # ---------------------------------------------------------------------------
  # DNS Service Discovery (Optional)
  # ---------------------------------------------------------------------------
  # - job_name: 'dns-discovery'
  #   dns_sd_configs:
  #     - names:
  #         - '_prometheus._tcp.mcp.local'
  #       type: 'SRV'
  #       refresh_interval: 30s

# -----------------------------------------------------------------------------
# Remote Write Configuration (Optional)
# -----------------------------------------------------------------------------
# remote_write:
#   - url: 'https://prometheus-remote.example.com/api/v1/write'
#     remote_timeout: 30s
#     write_relabel_configs:
#       - source_labels: [__name__]
#         regex: 'mcp_.*'
#         action: keep
#     queue_config:
#       capacity: 10000
#       max_shards: 5
#       max_samples_per_send: 1000

# -----------------------------------------------------------------------------
# Remote Read Configuration (Optional)
# -----------------------------------------------------------------------------
# remote_read:
#   - url: 'https://prometheus-remote.example.com/api/v1/read'
#     read_recent: true

# -----------------------------------------------------------------------------
# Storage Configuration
# -----------------------------------------------------------------------------
# storage:
#   tsdb:
#     retention:
#       time: 30d
#       size: 10GB

```

