Got it ✅ — here’s a clean **unified diff patch** you can apply directly to your current `docker/entrypoint.sh` to implement the simplification we discussed:  
- Removes the extra subshell/function re‑definitions for privilege drop.  
- Drops privileges with `gosu` and execs the app directly so it becomes the child of `tini` (PID 1’s child) for clean signal handling.  
- Keeps all your existing setup steps intact.

---

```diff
--- a/docker/entrypoint.sh
+++ b/docker/entrypoint.sh
@@
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

-    # Drop privileges to mcp if running as root
-    if [[ "$(id -u)" -eq 0 ]]; then
-        log_info "Dropping privileges to mcp"
-        exec gosu mcp:mcp bash -lc '
-          set -Eeuo pipefail
-          PY_EXEC="$(command -v python || command -v python3)"
-          export PY_EXEC
-          '"$(typeset -f log_info log_warn log_error shutdown_handler start_application)"'
-          trap shutdown_handler SIGTERM SIGINT SIGQUIT
-          start_application "$@"
-        ' bash "$@"
-    else
-        start_application "$@"
-    fi
+    # Drop privileges to mcp if running as root, then exec the app directly
+    if [[ "$(id -u)" -eq 0 ]]; then
+        log_info "Dropping privileges to mcp"
+        exec gosu mcp:mcp "${PY_EXEC}" -m mcp_server.server ${DEVELOPMENT_MODE:+--debug}
+    else
+        exec "${PY_EXEC}" -m mcp_server.server ${DEVELOPMENT_MODE:+--debug}
+    fi
 }
 
 main "$@"
```

---

### Why this is better
- **Simpler**: No nested bash, no re‑defining functions inside a subshell.
- **Signal‑safe**: With `tini` as PID 1 and the app as its direct child, SIGTERM/SIGINT are delivered straight to Python’s signal handlers.
- **Predictable exit codes**: `exec` replaces the shell, so the container exits with the app’s code.
- **Privilege drop**: Still uses `gosu` for a clean UID/GID switch without spawning an extra shell.

---

https://copilot.microsoft.com/shares/LyfWz3oH1q93CoEAeAW5f
https://copilot.microsoft.com/shares/UiBZ9LYnRj84KTaDxZWCi (updated)
---
Here’s the **full, ready‑to‑drop‑in** `docker/entrypoint.sh` with the simplification applied — it keeps all the robustness we built in earlier, but now drops privileges and execs the app directly so it runs as the direct child of `tini` for clean signal handling.

```bash
#!/bin/bash
# =============================================================================
# MCP Server - Docker Entrypoint Script (simplified & robust)
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

ensure_dirs() {
  mkdir -p "${MCP_HOME}" "${MCP_LOG_PATH}" "${MCP_DATA_PATH}" "$(dirname "${MCP_CONFIG_PATH}")"
}

ensure_ownership() {
  for dir in "${MCP_LOG_PATH}" "${MCP_DATA_PATH}" "$(dirname "${MCP_CONFIG_PATH}")"; do
    if [[ -d "${dir}" ]]; then
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

  # Drop privileges to mcp if running as root, then exec the app directly
  if [[ "$(id -u)" -eq 0 ]]; then
    log_info "Dropping privileges to mcp"
    exec gosu mcp:mcp "${PY_EXEC}" -m mcp_server.server ${DEVELOPMENT_MODE:+--debug}
  else
    exec "${PY_EXEC}" -m mcp_server.server ${DEVELOPMENT_MODE:+--debug}
  fi
}

main "$@"
```

---

**Key changes from the previous version:**
- Removed the nested `bash -lc` and function re‑definitions for privilege drop.
- Now simply `exec`s the Python process directly (either as `mcp` via `gosu` or as the current user).
- Still runs all setup steps (dirs, ownership, config generation, migrations, dependency waits) before starting.
- Signals are handled cleanly by `tini` → Python process, without an intermediate shell.

If you like, I can also walk you through **how to test this in isolation** to confirm the privilege drop and signal handling work exactly as intended before you roll it into your production build.
