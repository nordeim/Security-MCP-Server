# Tool Availability Remediation Sub-Plan

## Problem Statement
- Health endpoint reports overall status `degraded` because every tool-specific health check is `unhealthy` and `tool_availability` lists all five tools as unavailable.
- Running `mcp_client.py` confirms each tool is enabled but subprocess execution fails with `Command not found`, e.g. `gobuster` missing from PATH.

## Planned Actions
- **Install required external binaries**
  - `gobuster`, `hydra`, `masscan`, `nmap`, and `sqlmap` must be present on the host. Install via package manager or ensure they are discoverable in PATH for the server process.
- **Reconfigure tool commands (optional)**
  - If custom install paths are used, adjust tool configuration or system PATH so `_resolve_command()` succeeds.
- **Re-run health checks**
  - After installing binaries, hit `/health` or use `python3 mcp_client.py` to confirm each tool transitions to `healthy` or `degraded` only when runtime issues occur.
- **Document environment requirements**
  - Update project documentation (e.g., README or deployment guide) to list required system packages, preventing future availability failures.

## Validation Steps
1. Run each tool’s `--version` from the same shell as the server to verify availability.
2. Call `/health` and ensure `tool_availability` no longer reports missing tools.
3. Execute representative commands via `mcp_client.py` for each tool to confirm subprocess execution works end-to-end.
