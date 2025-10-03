# Security-MCP-Server Runtime Error Sub-Plan

## Error Recap
- `HydraTool` fails during discovery with: `'MCPConfig' object has no attribute 'circuit_breaker_enabled'`.
- `SqlmapTool` fails during discovery with: `'SqlmapTool' object has no attribute 'config'`.
- Stdio transport still raises when the `model-context-protocol` dependency is missing.

## Planned Fixes
- **HydraTool (`mcp_server/tools/hydra_tool.py`)**
  - Replace direct usage of `self.config.circuit_breaker_enabled` with guarded access to `self.config.circuit_breaker` dataclass fields.
  - Reinitialize the circuit breaker using the retrieved settings.

- **SqlmapTool (`mcp_server/tools/sqlmap_tool.py`)**
  - Reinstate `self.config = get_config()` before invoking `_setup_enhanced_features()` so the tool has configuration context.
  - Keep existing safeguards that require an explicit `-u/--url` flag.

- **Transport dependency**
  - Document that operators must either install `model-context-protocol` or set `MCP_SERVER_TRANSPORT=http` before running `python3 -m mcp_server.server`.

## Validation Steps
- Rerun `python3 -m mcp_server.server` after applying the code fixes to confirm all four tools load successfully.
- If stdio is required, install `model-context-protocol`; otherwise, export `MCP_SERVER_TRANSPORT=http` and confirm the HTTP server boots.
