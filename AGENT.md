# 🛡️ Security MCP Server — Agent Reference

## Project Snapshot
- **Core Role**: `mcp_server/server.py` hosts `EnhancedMCPServer`, orchestrating Model Context Protocol (MCP) transports (HTTP & stdio), wiring configuration, tool registry, health checks, and metrics.
- **Primary Capabilities**: unified execution of security tooling with guardrails (circuit breakers, strict validation, resource limits, observability).
- **Key Documents Reviewed**: `README.md`, `CLAUDE.md`, `docs/Project Architecture Document.md` — all align with the implemented code.

## Architectural Layers
- **Transport Layer**: HTTP via FastAPI/Uvicorn, stdio via MCP reference server; auto fallback based on availability.
- **Tool Registry**: `_load_tools_from_package()` discovers `MCPBaseTool` subclasses in `mcp_server/tools/`, honoring `TOOL_INCLUDE`/`TOOL_EXCLUDE` filters.
- **Execution Pipeline** (`MCPBaseTool.run()`):
  - Validate input with `ToolInput` (RFC1918 / `.lab.internal`, metacharacter filtering).
  - Enforce concurrency via semaphores and circuit breakers (`circuit_breaker.py`).
  - Spawn subprocesses with resource limits (`_set_resource_limits()`, `_spawn()`), truncated outputs, timeout handling.
  - Emit normalized `ToolOutput` + metrics hooks.
- **Resilience & Observability**:
  - `HealthCheckManager` schedules prioritized checks (system resources, tool availability, process health) exposed via `/health` and `/events` (SSE).
  - `MetricsManager` + Prometheus integration supply `/metrics` endpoint; per-tool execution stats and system-wide counters.

## Tool Implementations (`mcp_server/tools/`)
- **`NmapTool`**: enforces network size caps, flag allowlists, script category policies, auto-injects safe performance flags (e.g., `-T4`, `--top-ports 1000`).
- **`MasscanTool`**: rate-limits scans, validates ports/interfaces, toggles intrusive banner grabbing via config.
- **`GobusterTool`**: mode-aware (dir/dns/vhost), validates targets (URL vs domain), enforces wordlist/thread safety.
- **`HydraTool`**: preserves HTTP form payload tokens via placeholder sanitizer, injects safe defaults (`-l admin`, `-P /usr/share/wordlists/common-passwords.txt`) when missing, enforces RFC1918 / `.lab.internal` targets, clamps threads.
- **`SqlmapTool`**: mandates `--batch`, clamps `--risk`/`--level`, restores query parameters after sanitizer placeholders, rejects disallowed characters early.
- All tools load shared policy from `get_config()` (intrusive enablement, timeouts, concurrency).

## Configuration & Policy (`mcp_server/config.py`)
- Layered load order: defaults → YAML/JSON file → environment variables.
- Provides hot reload via `reload_config()` with validation (e.g., transport whitelist, threshold bounds).
- `SecurityConfig` governs max argument length, timeouts, `allow_intrusive` switch consumed by tools.

## Circuit Breakers (`mcp_server/circuit_breaker.py`)
- Async-safe breaker with adaptive recovery, jitter, Prometheus counters/gauges.
- Applies per-tool instance, preventing cascading failures and surfacing status in health checks.

## Health Monitoring (`mcp_server/health.py`)
- Prioritized checks (0: critical → 2: informational) determine overall status (`healthy`, `degraded`, `unhealthy`).
- Background monitor task feeds HTTP `/health` responses and SSE events.

## Deployment & Operations
- **`scripts/mcp_server_launcher.sh`**: turnkey bootstrap (APT tool install, venv creation, env export, server launch) — intended for local/agent startup.
- **`Dockerfile`**: multi-stage build producing hardened runtime with bundled binaries, non-root `mcp` user, `tini` entrypoint, healthcheck script.
- **`docker-compose.yml`**: stacks MCP server with Prometheus, Grafana, node-exporter, cadvisor on segregated networks, prewired scrape labels.

## Extension Playbook
1. Subclass `MCPBaseTool` in `mcp_server/tools/`, define `command_name`, `allowed_flags`, override `_execute_tool()` only when necessary.
2. Register supporting binaries in launcher script & Docker image to satisfy health checks.
3. Update docs (`README.md`, `docs/`) and metrics/alerts if the new tool introduces novel failure modes.

## Testing Workflow
  - Activate the shared environment: `source /opt/venv/bin/activate`
  - Run targeted regression suites: `pytest tests/test_gobuster_tool.py tests/test_masscan_tool.py tests/test_hydra_tool.py tests/test_sqlmap_tool.py`
  - Full suite: `pytest`

## Quick Reference Endpoints
- `GET /health` → aggregated status with per-check metadata.
- `GET /tools` → tool registry snapshot (enabled state, descriptions, safety metadata).
- `POST /tools/{ToolName}/execute` → validated execution path (requires enabled tool and safe inputs).
- `GET /events` → Server-Sent Events stream of health updates.
- `GET /metrics` → Prometheus-formatted metrics (falls back to JSON summary if Prometheus unavailable).

---
*Maintained for AI coding assistants needing fast situational awareness of the Security MCP Server codebase.*
