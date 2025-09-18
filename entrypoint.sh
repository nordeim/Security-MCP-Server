#!/bin/bash
set -e

# Function to handle signals
cleanup() {
    echo "Received shutdown signal, cleaning up..."
    # Add any cleanup logic here
    exit 0
}

# Trap signals
trap cleanup SIGTERM SIGINT

# Initialize directories
echo "Initializing directories..."
mkdir -p /var/log/mcp-server
mkdir -p /var/lib/mcp-server

# Set up environment (append PYTHONPATH if not present)
echo "Setting up environment..."
if [ -z "${PYTHONPATH}" ]; then
  export PYTHONPATH="/opt/mcp-server"
else
  export PYTHONPATH="/opt/mcp-server:${PYTHONPATH}"
fi

# Wait for dependencies
echo "Waiting for dependencies..."
if [ "${WAIT_FOR_DEPENDENCIES:-false}" = "true" ]; then
    # Wait for Prometheus if configured
    if [ -n "${PROMETHEUS_URL}" ]; then
        if ! command -v curl >/dev/null 2>&1; then
            echo "curl is required to wait for dependencies but is not installed. Skipping wait."
        else
            echo "Waiting for Prometheus at ${PROMETHEUS_URL}..."
            max_attempts=60
            attempt=1
            until curl -fsS "${PROMETHEUS_URL}/-/healthy" >/dev/null 2>&1; do
                if [ $attempt -ge $max_attempts ]; then
                    echo "Timed out waiting for Prometheus (${max_attempts} attempts)."
                    break
                fi
                echo "Prometheus is unavailable - sleeping (attempt: ${attempt})"
                attempt=$((attempt + 1))
                sleep 2
            done
            echo "Prometheus wait loop finished"
        fi
    fi
fi

# Check if configuration exists
if [ ! -f "/opt/mcp-server/config/config.yaml" ] && [ ! -f "/opt/mcp-server/config/config.json" ]; then
    echo "No configuration file found at /opt/mcp-server/config, using environment variables only"
fi

# Validate environment
echo "Validating environment..."
python - <<'PY'
import sys
try:
    import importlib
    importlib.import_module("mcp_server.main")
    print("Python environment is valid")
except Exception as e:
    print("Python environment validation failed:", e)
    sys.exit(1)
PY

# Start the application
echo "Starting Security MCP Server..."
exec python -m mcp_server.main
