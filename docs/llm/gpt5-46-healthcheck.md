### Problem summary

- Your healthcheck script uses `wget --spider`, which issues a HEAD request. FastAPI’s `/health` only supports GET, so HEAD returns 405 and Docker marks the container as unhealthy.
- Curl path is okay (uses GET), but you’re not checking status codes explicitly. Your endpoint can return 200 (healthy), 207 (degraded), or 503 (unhealthy).

---

### Fix plan

- Force GET for both curl and wget.
- Treat HTTP 200 and 207 as healthy; treat anything else (e.g., 503) as unhealthy.
- Prefer curl for explicit status-code checks; fall back to wget in GET mode (wget exits non-zero on HTTP errors like 4xx/5xx).

---

### Drop-in replacement healthcheck.sh

```bash
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
```

---

### Dockerfile healthcheck entry

You can keep your existing line:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["/healthcheck.sh"]
```

Optionally, if your app startup can take longer under heavy load, increase `start_period` (e.g., to 120s).

---

### Validation checklist

- Rebuild and start:
  - docker compose up --build -d
- Confirm health transitions:
  - docker ps should show mcp-server as healthy.
- Tail logs:
  - docker logs -f mcp-server
- Probe endpoint manually:
  - curl -i http://localhost:8080/health
  - Expect 200 (healthy) or 207 (degraded). The healthcheck script will treat both as healthy and only fail on 5xx.

https://copilot.microsoft.com/shares/DjwiLo3D28hM2kbf9hQAr
