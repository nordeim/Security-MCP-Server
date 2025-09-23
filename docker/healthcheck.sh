#!/bin/bash
# =============================================================================
# MCP Server Health Check Script (hardened)
# - Uses GET (not HEAD) for FastAPI compatibility
# - Accepts 200 and 207 (degraded) as healthy; 5xx considered unhealthy
# =============================================================================

set -Eeuo pipefail

readonly HEALTH_ENDPOINT="${MCP_HEALTH_ENDPOINT:-http://localhost:8080/health}"
readonly TIMEOUT="${MCP_HEALTH_TIMEOUT:-10}"

# Prefer curl: explicit status code evaluation
if command -v curl >/dev/null 2>&1; then
  # -s silent, -S show errors, -f fail on HTTP errors
  # We don't use -f because we want to inspect the code explicitly
  code="$(curl -sS --connect-timeout "${TIMEOUT}" --max-time "${TIMEOUT}" -o /dev/null -w "%{http_code}" -X GET "${HEALTH_ENDPOINT}" || true)"
  if [[ "${code}" == "200" || "${code}" == "207" ]]; then
    exit 0
  else
    exit 1
  fi
fi

# Fallback to wget: force GET by downloading to /dev/null
if command -v wget >/dev/null 2>&1; then
  # wget exits non-zero on HTTP errors (4xx/5xx), so this is sufficient
  wget --quiet --tries=1 --timeout="${TIMEOUT}" -O /dev/null "${HEALTH_ENDPOINT}" && exit 0 || exit 1
fi

# No HTTP client available
exit 1
