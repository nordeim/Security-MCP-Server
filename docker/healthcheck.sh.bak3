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
