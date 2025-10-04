# Tool Refactoring Plan — TODO

## Scope
- **Goal**: Align `GobusterTool`, `MasscanTool`, `HydraTool`, and `SqlmapTool` with the hardened validation patterns introduced in `mcp_server/base_tool.py` and `NmapTool`, without regressing existing behaviour.
- **Out of Scope**: Introducing new default flags, changing optimiser behaviour, or altering transports.

## Pre-Refactor Baseline Verification
- [x] **GobusterTool**: `_parse_safe_args()` is the sole consumer of `extra_args`, bypassing `MCPBaseTool._parse_args()` (see `mcp_server/tools/gobuster_tool.py`, lines ~165-257).
- [x] **MasscanTool**: `_parse_and_validate_args()` joins tokens into a single string and no `DEFAULT_WAIT` constant is defined (see `mcp_server/tools/masscan_tool.py`, lines ~232-328 & class vars).
- [x] **HydraTool**: `_secure_hydra_args()` injects defaults like `-l admin`/`-P` wordlist and defines no `_FLAGS_REQUIRE_VALUE` metadata (see `mcp_server/tools/hydra_tool.py`, lines ~254-379).
- [x] **SqlmapTool**: `_secure_sqlmap_args()` enforces `--batch`, appends safety flags, and lacks `_FLAGS_REQUIRE_VALUE` (see `mcp_server/tools/sqlmap_tool.py`, lines ~250-365).

## Refactor Tasks
1. **Base Metadata Augmentation**
   - [x] `GobusterTool`: `_FLAGS_REQUIRE_VALUE` + `_EXTRA_ALLOWED_TOKENS` defined for mode tokens and flag values.
   - [x] `MasscanTool`: `_FLAGS_REQUIRE_VALUE` declared; `_EXTRA_ALLOWED_TOKENS` remains empty (not needed).
   - [x] `HydraTool`: `_FLAGS_REQUIRE_VALUE` declared; `_EXTRA_ALLOWED_TOKENS` not needed after sanitizer placeholder approach.
   - [x] `SqlmapTool`: metadata declared for risk/test/URL flags; `_EXTRA_ALLOWED_TOKENS` not required.
2. **Validation Integration**
   - [x] `GobusterTool`: added `_parse_and_validate_args()` wrapper around `super()._parse_args()` with error-to-`ToolOutput` handling.
   - [x] `MasscanTool`: `_parse_and_validate_args()` now wraps `super()._parse_args()` and preserves rate/port semantics.
   - [x] `HydraTool`: `_parse_and_validate_args()` now wraps base sanitizer using placeholder tokens for form payloads.
   - [x] `SqlmapTool`: secured arguments now pass through base sanitizer via placeholder restoration.
3. **Error Handling Consistency**
   - [ ] Convert ValueError pathways to `ToolOutput` via `_create_error_output()` using the calling input’s correlation ID.
   - [ ] Preserve existing log messages to avoid breaking telemetry dashboards.
4. **Optimizer Integrity**
   - [ ] Ensure optimiser methods (`_optimize_mode_args()`, `_apply_safety_limits()`) append defaults **only when missing**; no change expected.
   - [ ] Validate post-refactor that defaults are not duplicated via new metadata.
5. **Unit & Integration Tests**
   - [ ] Add targeted unit tests per tool under `tests/` mirroring `tests/test_nmap_tool.py` style: empty args, user-only args, optimiser-only args.
   - [ ] Add HTTP smoke tests (curl snippets) to documentation to confirm runtime behaviour.

## Validation Checklist (Run Post-Changes)
- [ ] `pytest tests/test_gobuster_tool.py tests/test_masscan_tool.py tests/test_hydra_tool.py tests/test_sqlmap_tool.py`
- [ ] Manual HTTP POST for each tool verifying validator acceptance and subprocess launch.
- [ ] Review logs for duplicated default flags or missing telemetry entries.

## Sequencing & Rollback Strategy
1. Work tool-by-tool in separate commits to ease rollback.
2. After each tool refactor, run its unit test and—from the FastAPI server—execute a smoke test.
3. Maintain branch with staged changes; if regressions detected, revert to pre-plan tag.

## Notes
- Created: 2025-10-04 12:49 +08:00
- Prepared by: Cascade (validated against `mcp_server/base_tool.py` as of current workspace state)
- Next action: execute baseline verification tasks before editing code.
