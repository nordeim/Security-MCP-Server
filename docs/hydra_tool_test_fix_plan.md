# HydraTool Test Remediation Plan — TODO

## Context
- `pytest` revealed three failures in `tests/test_hydra_tool.py` related to payload preservation, unauthorized target validation, and invalid payload handling.
- Current behaviour in `mcp_server/tools/hydra_tool.py` aggressively filters arguments, preventing downstream validation from seeing certain tokens.

## Goals
- Preserve legitimate HTTP form payloads so placeholder restoration can succeed.
- Ensure unauthorized targets generate `ToolOutput` validation errors.
- Produce structured errors when payload tokens contain disallowed characters instead of silently stripping them.

## File Impact Assessment
1. `mcp_server/tools/hydra_tool.py`
   - Relax `_secure_hydra_args()` filtering to retain HTTP form payload flags/values and allow safe password file paths.
   - Adjust `_validate_hydra_requirements()` to return `ToolOutput` when `_is_authorized_target()` fails.
   - Update `_parse_and_validate_args()` to emit validation errors when placeholder restoration cannot trust token content.
2. `tests/test_hydra_tool.py`
   - Keep current expectations; only adjust if behaviour changes require refined assertions (e.g., additional metadata checks).

## Step-by-Step Remediation
1. **Preserve Payload Arguments**
   - Modify `_secure_hydra_args()` to treat known HTTP form flags (`http-post-form`, etc.) as pass-through tokens.
   - Accept relative password file paths when `os.path.exists` indicates file presence (already patched in tests).
2. **Unauthorized Target Handling**
   - In `_validate_hydra_requirements()`, return `_create_error_output(...)` when `_is_authorized_target()` returns `False`.
   - Ensure error message matches test expectation "Unauthorized Hydra target".
3. **Invalid Payload Detection**
   - In `_parse_and_validate_args()`, when a token fails `_is_safe_payload_token()`, build and return a `ToolOutput` with metadata capturing the offending token (current log stays intact).
   - Confirm placeholder restoration occurs only for safe tokens; unsafe ones trigger immediate error.
4. **Re-run Tests**
   - Execute `pytest tests/test_hydra_tool.py` followed by full suite to verify no regressions.

## Validation Checklist
- [ ] Update `_secure_hydra_args()` to retain payload tokens and avoid default password injection when user supplied.
- [ ] Ensure unauthorized target rejection returns `ToolOutput` with `validation_error` type.
- [ ] Verify `_parse_and_validate_args()` returns `ToolOutput` for invalid payload characters.
- [ ] Re-run targeted pytest module and confirm pass.
- [ ] Re-run full `pytest` and confirm all tests pass.

## Notes
- Keep existing log warnings intact to avoid telemetry regressions.
- No database or external service changes required; scope limited to argument handling and validation.
- Implementation should preserve backwards-compatible defaults outside the failing scenarios.
