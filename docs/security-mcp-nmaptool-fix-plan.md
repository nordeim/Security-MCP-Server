# NmapTool Argument Validation Fix Plan

## Summary
`NmapTool` rejects valid commands because `_parse_and_validate_args()` disallows flags that the optimizer subsequently injects (`-T4`, `--max-parallelism=10`, `-Pn`, `--top-ports=1000`). The validation logic also reports that user-provided flags like `-O` are not permitted. This results in every execution failing with a validation error.

## Root Causes
- `self.allowed_flags` lacks entries for optimizer-injected flags with inline values (e.g., `--max-parallelism=10`, `--top-ports=1000`), so validation rejects them.
- Flags conditional on intrusive policy (e.g., `-O`, `-A`) are treated as disallowed even when they should be allowed by default policy.
- `_parse_and_validate_args()` still uses `startswith` matching, risking false positives/negatives when allowed flags are prefixes of other tokens.

## Remediation Steps
- [ ] **Audit allowed flags** in `NmapTool` so optimizer defaults are explicitly permitted (include value-bearing forms and plain forms).
- [ ] **Refine flag validation** to use precise matching (no `startswith`), handle value flags robustly, and treat optimizer defaults as trusted.
- [ ] **Adjust optimizer** to append defaults in a structure the validator understands (e.g., split `--max-parallelism=10` into flag + value or add equivalent checks).
- [ ] **Confirm policy expectations** for potentially intrusive flags (e.g., ensure `-O` is allowed if policy permits OS detection).
- [ ] **Add targeted tests** covering user-only args, optimizer-only args, and combined args to prevent regression.
- [ ] **Manual smoke test**: run `curl` or `python3 mcp_client.py` with Nmap arguments (`-O`, `-T4`, `--max-parallelism 10`, `-Pn`, `--top-ports 1000`) to confirm successful execution.

## Validation
1. Unit tests for `_parse_and_validate_args()` with representative inputs.
2. Manual HTTP execution replicating the bug report scenario.
3. Health check to ensure `NmapTool` reports healthy.
