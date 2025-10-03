# HTTP Transport Dependency Sub-Plan

## Error Summary
- Running `python3 -m mcp_server.server` with `MCP_SERVER_TRANSPORT=http` still raises `RuntimeError: HTTP transport requested but FastAPI/Uvicorn are missing, and stdio fallback is unavailable`.
- Log message `transport.http_deps_missing falling_back=stdio hint='pip install fastapi uvicorn sse-starlette prometheus-client'` indicates the FastAPI import block failed, likely because `sse_starlette` and/or `prometheus_client` are not installed in the runtime environment.

## Planned Actions
- **Install missing packages**
  - Run `pip install sse-starlette prometheus-client` inside the active virtual environment to satisfy the additional FastAPI dependencies imported in `mcp_server/server.py`.
- **Verify transport availability**
  - Re-run `python3 -m mcp_server.server` with `MCP_SERVER_TRANSPORT=http` and confirm the HTTP server starts without falling back to stdio.
- **Optional:** If HTTP still fails, capture traceback and inspect `FASTAPI_AVAILABLE`/`UVICORN_AVAILABLE` branches in `mcp_server/server.py` to identify any remaining missing modules.

## Validation Steps
1. After installation, check `pip show sse-starlette prometheus-client` to confirm both packages are present.
2. Re-run the server and ensure no `transport.http_deps_missing` warning appears.
3. Hit the `/health` endpoint (e.g., `curl http://127.0.0.1:8080/health`) to verify HTTP endpoints respond once the server is running.
