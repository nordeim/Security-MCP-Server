# Security-MCP-Server Codebase Overview

## Top-Level Packages
- **`mcp_server/`**: Primary Python package delivering configuration, orchestration, telemetry, and tool integrations for the MCP server runtime.
- **`docs/`**: Extensive historical documentation, prompts, and investigative notes for prior debugging and deployment efforts.
- **`CLAUDE.md`**: High-level architectural vision used to align project goals (captured separately in `security-mcp-architecture-overview.md`).

## Core Modules in `mcp_server/`
- **`server.py`**: The production entry point. Discovers tool plugins, applies environment filters, and instantiates `EnhancedMCPServer`. Provides HTTP and stdio transports, optional uvloop setup, Prometheus integration, and graceful shutdown management. Key responsibilities:
  - `_load_tools_from_package()` dynamically imports `MCPBaseTool` subclasses, applying include/exclude filters.
  - `EnhancedMCPServer` binds tool registry, health checks, metrics, signal handlers, and MCP server integration when the `mcp` library is present.
  - `run()` dispatches to stdio or HTTP transport based on configuration, raising when dependencies are absent.
  - `main_enhanced()` orchestrates environment bootstrap, tool loading, and lifecycle execution.

- **`base_tool.py`**: Abstract foundation for all security tools.
  - Defines `ToolInput`/`ToolOutput` Pydantic models with strict validation (private network targets, metacharacter filtering, output truncation bounds).
  - Implements concurrency control via per-event-loop semaphores, circuit breaker integration, and asynchronous subprocess spawning with resource limits (CPU, memory, file descriptors).
  - Provides error handling helpers producing structured telemetry and recovery hints.

- **`config.py`**: Thread-safe configuration loader supporting defaults, YAML/JSON file overrides, environment variables, validation, and hot reload.
  - `MCPConfig` aggregates sectional dataclasses (`DatabaseConfig`, `SecurityConfig`, etc.) and clamps values to safe bounds.
  - `get_config()` exposes a singleton accessor with optional recreation for tests.

- **`circuit_breaker.py`**: Asynchronous circuit breaker implementation with Prometheus metrics, exponential backoff, jitter, and statistics tracking. Integrates seamlessly with tools through `CircuitBreaker` and related context helpers.

- **`health.py`**: Asynchronous health monitoring framework.
  - Provides built-in checks for system resources, process vitality, dependency availability, and tool readiness.
  - `HealthCheckManager` coordinates periodic execution, prioritization (critical/important/informational), SSE-ready summaries, and history tracking.

- **`metrics.py`**: Centralized metrics management.
  - Supplies singleton `MetricsManager`, per-tool `ToolMetrics`, and Prometheus registration helpers.
  - Tracks execution counts, percentiles, timeout/error rates, and system-level request counters.

- **`server-stdio.py` / `server-dpsk-patch.py`**: Alternative or historical server variants retaining legacy behavior; useful for regression comparison but not referenced by the primary entry point.

## Tool Implementations in `mcp_server/tools/`
All tools inherit from `MCPBaseTool`, adding validation, argument shaping, and policy enforcement before delegating to the shared subprocess runner.

- **`gobuster_tool.py`**: Implements mode-aware validation (`dir`, `dns`, `vhost`), wordlist safety checks, thread limits, URL/domain authorization, and automatic argument optimization (timeouts, quiet mode, retries).

- **`hydra_tool.py`**: Focuses on credential testing with strict target validation, default authentication safeguards, thread caps, and password list restrictions. Reinitializes circuit breaker settings based on configuration.

- **`masscan_tool.py`**: Applies RFC1918 target enforcement, rate limiting (configurable), port specification validation, and automatic tuning of scan parameters. Enforces conservative defaults when configuration parsing fails.

- **`nmap_tool.py`**: Enforces network size thresholds, script whitelists, port specification filters, and optional intrusive features based on configuration. Adds automatic performance tuning (timing template, parallelism, host discovery suppression).

- **`sqlmap_tool.py`**: Restricts operations to low-risk SQL injection tests, validates target URLs, constrains risk/level flags, and injects safe defaults (batch mode, limited techniques, conservative timing).

## Observed Stability Issues During Review
- **`mcp_server/tools/hydra_tool.py`** currently fails to import due to a stray `elif` at line 275, preventing tool discovery.
- **`mcp_server/tools/masscan_tool.py`** logs `config_max_rate` attribute errors because defaults are set *after* `_apply_config()` references them.
- **`mcp_server/tools/nmap_tool.py`** triggers `'NoneType'` errors when configuration assumes pre-initialized flag lists and `allow_intrusive` state.
- **`mcp_server/tools/sqlmap_tool.py`** expects `MCPConfig` to expose attributes like `circuit_breaker_enabled` that do not exist, leading to instantiation failure.
- **`EnhancedMCPServer` stdio transport** requires the external `mcp` package; absence results in the runtime error observed when invoking `python3 -m mcp_server.server` with `MCP_SERVER_TRANSPORT=stdio`.

## External Tool Dependencies
- The MCP server relies on native binaries for its bundled tools. Ensure the following commands are installed and on the server's `PATH`: `gobuster`, `hydra`, `masscan`, `nmap`, and `sqlmap`.
- Each tool availability health check in `mcp_server/health.py` calls `_resolve_command()` from `MCPBaseTool`; missing executables surface as degraded health and `Command not found` errors in `mcp_client.py` results.
- After installing binaries, re-run `/health` or `python3 mcp_client.py` to confirm that `tool_availability` and individual `tool_*` checks report `healthy`.

These findings guide upcoming remediation and align with the runtime error logs supplied by the user.
