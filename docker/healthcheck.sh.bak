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
