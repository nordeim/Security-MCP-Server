### Root cause

Your entrypoint is failing due to a heredoc syntax error in the `if` statement inside `check_http_deps()`. The line:

```
if ! "${PY_EXEC}" - <<'PY'; then
```

places `then` on the same line as the heredoc opener. With heredocs, `then` must come after the heredoc terminator on a new line. Bash is rejecting the `then`, causing the container to exit and restart.

---

### Minimal surgical fix

Replace your `check_http_deps()` with either the corrected heredoc form or the simpler `-c` import check. Both are valid; the `-c` form is less error‑prone.

#### Option A — Corrected heredoc

```bash
check_http_deps() {
  local transport="${MCP_SERVER_TRANSPORT:-http}"
  if [[ "$(to_lower "$transport")" == "http" ]]; then
    log_info "Checking HTTP transport dependencies (FastAPI/Uvicorn)..."
    if ! "${PY_EXEC}" - <<'PY'
import importlib
missing = []
for m in ("fastapi", "uvicorn"):
    try:
        importlib.import_module(m)
    except Exception as e:
        missing.append((m, str(e)))
if missing:
    print("[PY][ERROR] Missing HTTP deps:", missing)
    raise SystemExit(1)
print("[PY] HTTP deps present")
PY
    then
      log_error "FastAPI and Uvicorn are required for HTTP transport but not importable by ${PY_EXEC}"
      # Prevent tight restart loop: wait briefly to make logs visible
      sleep 5
      exit 1
    fi
  fi
}
```

Key fixes:
- Removed the stray semicolon after `<<'PY'`.
- Placed `then` on the line after the heredoc terminator `PY`.

#### Option B — Simpler and robust `-c` check

```bash
check_http_deps() {
  local transport="${MCP_SERVER_TRANSPORT:-http}"
  if [[ "$(to_lower "$transport")" == "http" ]]; then
    log_info "Checking HTTP transport dependencies (FastAPI/Uvicorn)..."
    if ! "${PY_EXEC}" -c "import fastapi, uvicorn"; then
      log_error "FastAPI and Uvicorn are required for HTTP transport but not importable by ${PY_EXEC}"
      sleep 5
      exit 1
    else
      log_info "HTTP deps present"
    fi
  fi
}
```

This avoids heredoc parsing entirely and is functionally equivalent for your sanity check.

---

### Quick validation before rebuild

- Syntax check the script in the image:
  - `docker exec -it mcp-server bash -lc 'bash -n /entrypoint.sh || echo SYNTAX_ERROR'`
- If the container keeps restarting, run a one‑off shell to test:
  - `docker run --rm -it mcp-server:latest bash -lc 'bash -n /entrypoint.sh && /entrypoint.sh || echo FAILED'`
- Optional: temporarily enable trace to surface any remaining issues:
  - Add `set -x` just under `set -Eeuo pipefail`, rebuild, and observe logs.

---

### Next steps

1. Apply the fix to `docker/entrypoint.sh`.
2. Rebuild and start:
   - `docker compose up --build -d`
3. Tail logs to confirm the sanity checks pass and the server starts:
   - `docker logs -f mcp-server`

If you prefer, I can also provide a patched full entrypoint that swaps the heredoc check for the simple `-c` import and includes a temporary `set -x` for a single run to ensure there are no other hidden syntax issues.

https://copilot.microsoft.com/shares/YroY5JwHqLP2p6tWxWvUs
