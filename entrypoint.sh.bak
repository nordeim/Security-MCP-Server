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

# Set up environment
echo "Setting up environment..."
export PYTHONPATH="/opt/mcp-server:${PYTHONPATH}"

# Wait for dependencies
echo "Waiting for dependencies..."
if [ "$WAIT_FOR_DEPENDENCIES" = "true" ]; then
    # Wait for Prometheus if configured
    if [ -n "$PROMETHEUS_URL" ]; then
        echo "Waiting for Prometheus at $PROMETHEUS_URL..."
        until curl -f "$PROMETHEUS_URL/-/healthy" >/dev/null 2>&1; do
            echo "Prometheus is unavailable - sleeping"
            sleep 2
        done
        echo "Prometheus is up and running"
    fi
fi

# Check if configuration exists
if [ ! -f "/opt/mcp-server/config/config.yaml" ] && [ ! -f "/opt/mcp-server/config/config.json" ]; then
    echo "No configuration file found, using environment variables only"
fi

# Validate environment
echo "Validating environment..."
python -c "import mcp_server.main; print('Python environment is valid')" || {
    echo "Failed to validate Python environment"
    exit 1
}

# Start the application
echo "Starting Security MCP Server..."
exec python -m mcp_server.main
