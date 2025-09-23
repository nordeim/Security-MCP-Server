### Goals for a safe override

- Preserve entrypoint and startup validation (no command/entrypoint overrides).
- Allow source-code bind mounts for iterative development without breaking config or volumes.
- Keep container environment in dev mode but avoid risky Python runtime env overrides.
- Only add optional dev conveniences that won’t trigger restart loops if host paths are empty.

---

### Key changes from the original override

- Removed the debugpy command override. This prevents bypassing `/entrypoint.sh`.
- Mounted source directories as read-only to avoid accidental runtime mutations:
  - `./mcp_server` → `/app/mcp_server:ro`
  - `./scripts` → `/app/scripts:ro`
  - `./tests` → `/app/tests:ro` (optional; your app doesn’t need tests at runtime)
- Do not mount the entire `./config` directory by default (it can shadow `/app/config` with an empty host folder). If you need dev configs, mount the single file `./config/config.yaml` as read-only.
- Set `DEVELOPMENT_MODE=true` and `DEBUG=true`, but leave Python runtime env (PYTHONUNBUFFERED, PYTHONDONTWRITEBYTECODE) to the image defaults.
- Added optional 5678 port for future debugging without assuming the app will open it.

---

### Drop-in replacement docker-compose.override.yml

```yaml
# Safe development override: preserves entrypoint, avoids config shadowing, and uses read-only bind mounts.

# Compose v2+: omit obsolete 'version' key

services:
  mcp-server:
    # Use the same build context/image as base; cache hints are fine but not required here.
    build:
      context: .
      dockerfile: Dockerfile
      cache_from:
        - mcp-server:latest

    # Bring in the .env for convenience; base Compose already maps critical vars via `environment`.
    env_file:
      - .env

    # Development flags (safe): do not override Python runtime env here.
    environment:
      DEVELOPMENT_MODE: 'true'
      DEBUG: 'true'
      LOG_LEVEL: DEBUG

    # Bind mounts for hot iteration — read-only to prevent accidental writes.
    # NOTE: Do NOT mount the entire ./config directory by default; it can hide baked configs.
    volumes:
      - ./mcp_server:/app/mcp_server:ro
      - ./scripts:/app/scripts:ro
      - ./tests:/app/tests:ro
      # If you need to test a local config, mount the single file (read-only):
      # - ./config/config.yaml:/app/config/config.yaml:ro

    # Expose dev debug port without changing the command/entrypoint.
    # This is harmless if nothing listens on 5678.
    ports:
      - "5678:5678"

    # Keep resource limits modest; you can bump them in dev if needed.
    # Do not change entrypoint/command — we rely on base entrypoint.
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 1G
```

---

### Validation checklist

- Parse and merge:
  - Run `docker compose config` and confirm the merged service:
    - Does not override `command` or `entrypoint`.
    - Keeps base `depends_on` and healthchecks.
- Startup:
  - `docker compose -f docker-compose.yml -f docker-compose.override.yml up --build -d`
  - `docker logs -f mcp-server` should show entrypoint logs, venv Python path, HTTP deps OK, Prometheus wait, then server start.
- Bind mounts:
  - `docker exec -it mcp-server ls -l /app/mcp_server /app/scripts /app/tests` show content from host as read-only.
  - Ensure `/app/config/config.yaml` exists either from image or explicit single-file mount.
- Optional debugging:
  - If you later enable a debug server on 0.0.0.0:5678, the port mapping is already in place.

---

### If you still need debugpy

If you want to run under debugpy but keep entrypoint validations, add a small toggle the app/entrypoint can honor (e.g., `MCP_DEBUGPY_LISTEN=0.0.0.0:5678`) and have `/entrypoint.sh` exec `python -m debugpy --listen "$MCP_DEBUGPY_LISTEN" -m mcp_server.server` only when that variable is set. That approach preserves all startup guardrails and avoids the restart loop caused by bypassing the entrypoint.

https://copilot.microsoft.com/shares/Ls1PHGLGgb1fdPoXbDsKN
