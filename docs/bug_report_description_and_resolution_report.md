# NmapTool Argument Validation Failure — Diagnosis and Resolution Report

## 1. Summary
- **Issue**: `NmapTool` rejected both user-supplied and internally generated arguments, making scans impossible.
- **Status**: Resolved in this iteration.
- **Primary Fixes**:
  - Relaxed base token sanitization to respect subclass-provided allowlists and numeric values.
  - Declared explicit ` _EXTRA_ALLOWED_TOKENS` and `_FLAGS_REQUIRE_VALUE` for `NmapTool`.
  - Added regression tests ensuring validation and optimization cooperate.

## 2. Impact Assessment
- **Operational impact**: All HTTP-triggered Nmap scans failed with `validation_error` responses prior to the fix.
- **User experience**: Coding agents (e.g., Claude Code) could not execute Nmap, blocking network reconnaissance workflows.
- **Blast radius**: Confined to `NmapTool`; other tools (Gobuster, Masscan, etc.) were unaffected.

## 3. Environment & Context
- **Repository**: `Security-MCP-Server`
- **Relevant paths**:
  - `mcp_server/base_tool.py`
  - `mcp_server/tools/nmap_tool.py`
  - `tests/test_nmap_tool.py`
- **Testing**: `pytest tests/test_nmap_tool.py`
- **HTTP reproduction command**:
  ```bash
  curl -sS -X POST http://localhost:8080/tools/NmapTool/execute \
    -H "Content-Type: application/json" \
    -d '{"target":"192.168.2.0/24","extra_args":"-O"}'
  ```

## 4. Initial Diagnosis
- The server injected defaults (`-T4`, `--max-parallelism=10`, `-Pn`, `--top-ports=1000`) and immediately rejected them.
- Manual attempts to pre-include defaults surfaced an endless cascade of "Disallowed token" errors.
- Bypassing `_parse_and_validate_args()` still failed, implicating the shared `_sanitize_tokens()` logic in `MCPBaseTool`.
- Curl responses confirmed validator failures while no actual Nmap execution occurred.

## 5. Troubleshooting Timeline
1. **Re-read `mcp_server/tools/nmap_tool.py`**: Confirmed optimizer adds defaults and allowed flag list lacked inline-value variants.
2. **Attempted to replace `startswith` logic**: Insufficient; validation still failed because base sanitization ran afterwards.
3. **Examined `_sanitize_tokens()` in `mcp_server/base_tool.py`**: Found it disallowed tokens lacking a matching flag base, including numeric values.
4. **Added targeted unit tests**: Initial tests failed, confirming empty optimized output when validation rejected defaults.
5. **Refined sanitizer and tool metadata**: Introduced `_EXTRA_ALLOWED_TOKENS` and `_FLAGS_REQUIRE_VALUE`, updated sanitizer to respect them.
6. **Re-ran tests and curl**: Tests passed; HTTP execution succeeded, noting only expected operational warnings (timeouts, root requirements).

## 6. Root Cause Analysis
- **Primary cause**: The shared sanitizer enforced `self.allowed_flags` without understanding that certain tokens are *values* rather than flags.
- **Contributing factors**:
  - `NmapTool` optimizer injected tokens not present in `allowed_flags` (e.g., `--max-parallelism=10`).
  - Numeric values such as `200` for `--top-ports` are not flags, yet sanitizer treated them as such and rejected them.
  - Lack of regression tests allowed prior refactors to miss the interaction between tool-level optimization and base-level sanitization.

## 7. Resolution Details
- **File** `mcp_server/base_tool.py`
  - Adjusted `_sanitize_tokens()` to:
    - Permit dash-prefixed tokens and numeric literals even if the strict regex fails.
    - Track flags that require subsequent value tokens via `self._FLAGS_REQUIRE_VALUE`.
    - Accept value tokens for those flags and emit clear errors if a required value is missing.
- **File** `mcp_server/tools/nmap_tool.py`
  - Declared `_EXTRA_ALLOWED_TOKENS` for optimizer defaults.
  - Declared `_FLAGS_REQUIRE_VALUE` so the base class knows which flags consume value tokens.
- **File** `tests/test_nmap_tool.py`
  - Added `run_tool()` helper returning both validated and optimized argument strings.
  - Added tests verifying:
    - `-O` survives validation and optimization.
    - Optimizer defaults appear even when user passes no `extra_args`.
    - Combined user + optimizer arguments remain single-sourced (no duplicates, values retained).

## 8. Verification
- **Unit tests**: `pytest tests/test_nmap_tool.py` → `3 passed`.
- **HTTP smoke tests**:
  - `/24` scan times out after 300 seconds (expected default timeout behavior).
  - `/32` scan succeeds, returning service/version details and confirming validator acceptance.
- **Operational warnings**: OS detection (`-O`) still requires root privileges, consistent with upstream Nmap behavior.

## 9. Follow-up Recommendations
- Document default timeout expectations and provide guidance for large CIDR scans (e.g., set `timeout_sec` or use narrower ranges).
- Expand regression coverage for other tools that rely on optimizer defaults.
- Consider centralizing tool metadata (flags, value expectations) to reduce duplication across tools.

## 10. Programming Guide — Avoiding Similar Pitfalls
- **Define explicit metadata**:
  - Use `_EXTRA_ALLOWED_TOKENS` for non-standard but safe tokens introduced automatically.
  - Provide `_FLAGS_REQUIRE_VALUE` for any flag that expects a separate argument.
- **Keep validation single-sourced**:
  - Perform argument sanitation in one place (the base class) while letting tools supply metadata instead of re-validating downstream.
- **Normalize optimizer output**:
  - Emit flag/value pairs in forms the validator expects (either `--flag=value` or `--flag value`, not a mix without metadata).
- **Write regression tests**:
  - For every tool, add unit tests covering empty, default-only, and combined argument scenarios.
  - Use integration tests (curl or client scripts) to catch discrepancies between validation and runtime behavior.
- **Surface clear errors**:
  - Favor informative `validation_error` messages that point directly to misconfigured tokens.
- **Monitor operational constraints**:
  - Ensure timeouts, privilege requirements, and other runtime conditions are documented and configurable.

## 11. Appendix — Key Commands
```bash
pytest tests/test_nmap_tool.py

curl -sS -X POST http://localhost:8080/tools/NmapTool/execute \
  -H "Content-Type: application/json" \
  -d '{"target":"192.168.2.132/32","extra_args":"-sV --top-ports 200"}'
```
