# Security-MCP-Server Remediation Plan

## Overview
This plan addresses the fatal stdio transport failure reported during runtime along with the tool import defects surfaced while reviewing the `mcp_server/` package. Each section lists a validated checklist for the file(s) requiring changes, with concise notes tying the action to specific problem areas observed in the source.

## Checklists

### `mcp_server/server.py`
- [ ] Guard `main_enhanced()` and `EnhancedMCPServer.run()` so that stdio transport is only attempted when `MCP_AVAILABLE` is `True`, otherwise emit a precise installation hint for `model-context-protocol`.
- [ ] Allow HTTP transport to proceed even when stdio dependencies are missing, ensuring graceful degradation instead of an unconditional `RuntimeError`.
- [ ] Update logging/messages near the existing `RuntimeError` to reference the exact package/module required (`mcp.server.stdio`).

> **Validation:** Verified at `mcp_server/server.py:320-386` that `main_enhanced()` currently raises `RuntimeError` whenever `MCP_AVAILABLE` is `False` and `transport == "stdio"`, leading to the observed crash when the `mcp` library is absent.

### `mcp_server/tools/hydra_tool.py`
- [ ] Replace the stray `elif` inside `_secure_hydra_args()` with a proper `if` clause (current code at `hydra_tool.py:272-287` causes a `SyntaxError`, blocking module import).
- [ ] Re-run lint/static analysis to confirm the function’s control flow now covers login/password parsing and reaches subsequent checks.
- [ ] Add/adjust unit coverage or manual tests to ensure sanitized defaults (e.g., enforced `-l`/`-P`) behave as expected.

> **Validation:** Inspected `_secure_hydra_args()` at `hydra_tool.py:270-352`; Python cannot compile the module because `elif` appears without an initial `if`, which matches the import failure observed during tool discovery.

### `mcp_server/tools/masscan_tool.py`
- [ ] Initialize `self.allow_intrusive` and `self.config_max_rate` **before** calling `_apply_config()` so logging inside `_apply_config()` no longer references undefined attributes (`masscan_tool.py:89-122`).
- [ ] Within `_apply_config()`, guard accesses to optional config sections (e.g., `self.config.security`) to avoid `AttributeError` when values are `None`.
- [ ] Add a regression test or runtime assertion that `self.config_max_rate` is set after configuration and no attribute errors surface during tool instantiation.

> **Validation:** Traced constructor at `masscan_tool.py:81-128`; `_apply_config()` logs `self.allow_intrusive` and `self.config_max_rate` before the attributes are defined, matching the AttributeError encountered during tool registration.

### `mcp_server/tools/nmap_tool.py`
- [ ] Define `self.allow_intrusive` and `self.allowed_flags` to safe defaults **before** invoking `_apply_config()` to prevent `TypeError: argument of type 'NoneType' is not iterable` when the method manipulates the list (`nmap_tool.py:98-156`).
- [ ] Harden `_apply_config()` against missing config sections so the logic gracefully skips intrusive-mode adjustments when `config.security` is `None`.
- [ ] Expand tests around script/flag filtering to confirm the baseline `BASE_ALLOWED_FLAGS` survives configuration overrides.

> **Validation:** In `nmap_tool.py:104-156`, `_apply_config()` attempts to remove `"-A"` from `self.allowed_flags` before the attribute is initialized, matching the discovery failure reproduced during review.

### `mcp_server/tools/sqlmap_tool.py`
- [ ] Replace the nonexistent `self.config.circuit_breaker_enabled` checks with the actual structure exported by `config.py` (e.g., inspect `self.config.circuit_breaker` dataclass) inside `_setup_enhanced_features()` (`sqlmap_tool.py:118-128`).
- [ ] While revisiting `_secure_sqlmap_args()`, ensure the fallback `-u` default is only injected when validation enforces a safe placeholder or raise a validation error instead of silently substituting.
- [ ] Add targeted tests confirming tool instantiation succeeds when optional circuit-breaker settings are absent.

> **Validation:** Reviewed `config.py` and confirmed it exposes `config.circuit_breaker` but not `circuit_breaker_enabled`, explaining the `AttributeError` thrown during `SqlmapTool` instantiation.

## Next Steps
1. Prioritize `mcp_server/server.py` changes to unblock stdio transport or guide operators toward installing `model-context-protocol`.
2. Address each tool module per the checklists to restore successful discovery and registration via `_load_tools_from_package()`.
3. Run the full tool discovery path (stdio and HTTP transports) to verify all checklist items clear the original runtime failure and import errors.
