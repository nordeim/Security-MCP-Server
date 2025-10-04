# README & AGENT Documentation Update Plan — TODO

## Context
- Recent tool refactors and test additions (e.g., `tests/test_hydra_tool.py`, `tests/test_sqlmap_tool.py`) introduced new safety guarantees that are not fully reflected in `README.md` and `AGENT.md`.
- Both documents currently highlight only a subset of available tools and lack run instructions aligned with the shared pytest harness and `/opt/venv` workflow.

## Objectives
1. Ensure `README.md` accurately documents the current tool roster, safety features, and testing workflow.
2. Refresh `AGENT.md` so that coding assistants receive up-to-date guidance on tool behaviour, sanitizer expectations, and the new regression suite.

## Planned Updates
### `README.md`
- **Tool Coverage Table**: Expand the "Available Tools" table to include `HydraTool` and `SqlmapTool`, noting placeholder sanitization, authentication defaults, and risk-level clamping.
- **Testing Section**: Document the focused tool suites (`tests/test_gobuster_tool.py`, `tests/test_masscan_tool.py`, `tests/test_hydra_tool.py`, `tests/test_sqlmap_tool.py`) and emphasize activation of `/opt/venv` prior to running `pytest`.
- **Hydra/Sanitizer Notes**: Add an operational note describing HTTP form payload placeholders (`^USER^`, `^PASS^`) and the sanitized behaviour now implemented in `mcp_server/tools/hydra_tool.py`.
- **Version & Dependency Callouts**: Confirm Python 3.12+ requirement (matching CI/runtime) and reference the shared fixtures in `tests/conftest.py` for contributors.

### `AGENT.md`
- **Tool Implementations Section**: Add explicit entries for `HydraTool` and `SqlmapTool`, summarizing their sanitizer placeholder handling, risk/test clamping, and unauthorized target checks.
- **Execution Pipeline Notes**: Mention the placeholder restoration step in `_parse_and_validate_args()` and the default injection behaviour for Hydra credentials.
- **Testing/Validation Reference**: Link to the regression suites and note that agents should run `pytest` inside `/opt/venv` to mirror the automation environment.

## Validation Checklist
- [ ] Cross-check updated `README.md` verbs with current code paths in `mcp_server/tools/hydra_tool.py` and `mcp_server/tools/sqlmap_tool.py`.
- [ ] Ensure `AGENT.md` examples remain consistent with `mcp_server/base_tool.py` flow and mention new tests.
- [ ] Run spell-check / markdown lint locally if available (optional) before committing.

## Sequencing
1. Update `README.md` sections listed above; review diff for accuracy.
2. Update `AGENT.md` with new tool details and testing workflow.
3. Re-read both documents to ensure cross-links (e.g., references to `docs/tool_tests_todo.md`) remain valid.
