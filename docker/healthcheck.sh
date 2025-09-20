#!/bin/bash
# =============================================================================
# MCP Server Health Check Script (updated)
# =============================================================================
# Tries wget first, then curl, respects MCP_HEALTH_TIMEOUT
# =============================================================================

set -e

readonly HEALTH_ENDPOINT="${MCP_HEALTH_ENDPOINT:-http://localhost:8080/health}"
readonly TIMEOUT="${MCP_HEALTH_TIMEOUT:-10}"

# Try wget, then curl. Fail if both missing or endpoint unhealthy.
if command -v wget >/dev/null 2>&1; then
    wget --quiet --tries=1 --timeout="${TIMEOUT}" --spider "${HEALTH_ENDPOINT}" >/dev/null 2>&1 && exit 0 || exit 1
elif command -v curl >/dev/null 2>&1; then
    curl -sf --max-time "${TIMEOUT}" "${HEALTH_ENDPOINT}" >/dev/null 2>&1 && exit 0 || exit 1
else
    # Neither wget nor curl is available; fail healthcheck explicitly.
    exit 1
fi
