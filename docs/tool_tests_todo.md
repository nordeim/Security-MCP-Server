# Tool Test Implementation Plan — TODO

## Overview
- **Objective**: Develop high-confidence pytest coverage for the refactored tools (`GobusterTool`, `MasscanTool`, `HydraTool`, `SqlmapTool`) that verifies argument sanitation, safety defaults, and error pathways introduced during the refactor.
- **Strategy**: Unit-test helper methods directly where possible, and exercise asynchronous `run()`/`_execute_tool()` flows with patched subprocess execution to avoid invoking real binaries.
- **Shared Harness Requirements**:
  - [ ] Create reusable fixtures/utilities in `tests/conftest.py` to instantiate tools with patched `_resolve_command` (always returning `/usr/bin/true`) and `_spawn` (returning canned `ToolOutput`).
  - [ ] Provide helper to assert `ToolOutput` objects produced by validation errors include expected `error_type` and metadata fields.
  - [ ] Ensure tests run under `pytest` with `pytest.mark.asyncio` for async entry points and maintain compatibility with existing `tests/test_nmap_tool.py` structure.
  - [ ] Add documentation in the test files referencing `docs/tool_refactor_todo.md` to ease traceability.

## `tests/test_gobuster_tool.py`
### Goals
- Validate integration with `MCPBaseTool._parse_args()` and mode extraction.
- Confirm defaults injected by `_ensure_target_argument()` and `_optimize_mode_args()` are idempotent.
- Ensure validation errors return `ToolOutput` via `_create_error_output()`.

### Planned Test Cases
- [ ] **test_mode_extraction_and_target_injection**: Ensure `dir` mode without `-u` adds target URL and passes through sanitizer.
- [ ] **test_dns_mode_rejects_url_target**: Verify `run()` returns `ToolOutput` validation error when `dns` mode target is URL.
- [ ] **test_invalid_flag_rejected_by_base_sanitizer**: Call `_parse_and_validate_args()` with disallowed flag and assert `ToolOutput` returned.
- [ ] **test_optimizer_does_not_duplicate_defaults**: Confirm repeated invocation with user-specified defaults keeps single instance.

### Implementation Checklist
- [ ] Add async fixture to patch `_spawn` to return successful `ToolOutput` containing synthetic stdout.
- [ ] Patch `_resolve_command` to deterministic path.
- [ ] Use `pytest.mark.parametrize` for mode/target combinations when feasible.
- [ ] Assert logger warnings via `caplog` where meaningful (e.g., filtered extensions).

## `tests/test_masscan_tool.py`
### Goals
- Validate `_parse_and_validate_args()` integration with base sanitizer and rate/port semantics.
- Confirm `_apply_safety_limits()` injects defaults without duplication.
- Ensure validation errors surface as `ToolOutput` with metadata.

### Planned Test Cases
- [ ] **test_rate_clamped_to_config_max**: Instantiate tool, set `config_max_rate`, supply excessive `--rate`, ensure sanitized output clamped and log warning captured.
- [ ] **test_port_spec_validation_success_and_failure**: Parameterize valid vs invalid port specs, checking success string vs `ToolOutput` error.
- [ ] **test_banners_blocked_when_intrusive_disabled**: Ensure `--banners` omitted unless `allow_intrusive` set.
- [ ] **test_apply_safety_limits_injects_defaults_once**: Confirm no duplication when defaults already present.

### Implementation Checklist
- [ ] Mock `get_config()` via monkeypatch to control `max_scan_rate` and `allow_intrusive`.
- [ ] Use helper to inspect returned string tokens vs `ToolOutput` objects.
- [ ] Exercise `_apply_safety_limits()` with string output from parser to ensure compatibility.
- [ ] Verify warning logs through `caplog` (e.g., `masscan.rate_limited`).

## `tests/test_hydra_tool.py`
### Goals
- Exercise placeholder-based sanitizer bridge for HTTP form payloads.
- Validate default injections for login/password and thread restrictions.
- Ensure unauthorized targets and malformed payloads raise structured errors.

### Planned Test Cases
- [ ] **test_placeholder_payload_restoration**: Provide `http-post-form` payload containing `^`/`&`; assert sanitized output restores original token and remains allowed.
- [ ] **test_missing_auth_injects_defaults**: Invoke `_secure_hydra_args()` without `-l` or `-P` and confirm defaults appended once.
- [ ] **test_unauthorized_target_rejected**: Call `_validate_hydra_requirements()` with public IP and assert returned `ToolOutput` error type `validation_error`.
- [ ] **test_invalid_payload_character_blocked**: Supply payload with disallowed characters (e.g., `;`) and ensure sanitizer returns `ToolOutput`.

### Implementation Checklist
- [ ] Introduce fixture to bypass filesystem checks for wordlists (patch `os.path.exists`/`getsize`).
- [ ] Mock `_spawn` to avoid execution and inspect final command tokens.
- [ ] Use `pytest.mark.asyncio` to exercise `_execute_tool()` path covering validation + sanitizer integration.
- [ ] Capture log warnings for default injections to confirm telemetry unaffected.

## `tests/test_sqlmap_tool.py`
### Goals
- Verify placeholder strategy for query parameters and enforcement of risk/test levels.
- Confirm mandatory flags (`--batch`, `-u/--url`) enforced and sanitized.
- Ensure invalid payload tokens produce structured errors.

### Planned Test Cases
- [ ] **test_url_and_batch_required**: Without `-u` ensure `_secure_sqlmap_args()` raises `ValueError`, converted to `ToolOutput` in `_execute_tool()`.
- [ ] **test_placeholder_payload_restore**: Provide query string containing `?` and `&`; ensure sanitized output matches original token set post-restoration.
- [ ] **test_risk_level_clamped**: Supply `--risk 5` and assert sanitized args clamp to configured max.
- [ ] **test_invalid_payload_token_rejected**: Introduce illegal character (e.g., `;`) and validate error `ToolOutput` with metadata.

### Implementation Checklist
- [ ] Patch `_is_authorized_target()` to focus on sanitizer behaviour without DNS lookups.
- [ ] Parametrize risk/test levels to confirm clamping logic.
- [ ] Mock `_spawn` to avoid subprocess and inspect command tokens include target appended at end.
- [ ] Ensure tests assert metadata contains offending token/value for error cases.

## Cross-Tool Validation Tasks
- [ ] Add coverage measurement target (`pytest --cov=mcp_server.tools`) once individual tests in place.
- [ ] Update `README.md` or developer documentation with instructions to run new tests.
- [ ] Ensure new test files reference the `Tool Test Implementation Plan` for traceability.
- [ ] Schedule follow-up review to confirm optimizer integrity and logging items from `docs/tool_refactor_todo.md` remain open.

## Validation Summary
- [ ] Review plan against current tool implementations in `mcp_server/tools/` to ensure all major execution paths are covered.
- [ ] Peer/AI self-review of plan completeness vs `tests/test_nmap_tool.py` conventions.
- [ ] Obtain user approval before proceeding to implement tests per this plan.
