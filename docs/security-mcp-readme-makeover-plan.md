# README Makeover Plan

## Objectives
- Reflect new launch workflows (`scripts/mcp_server_launcher.sh`, updated Docker artifacts).
- Highlight mandatory external binaries and Python packages to keep instructions consistent with `Dockerfile` and launcher script.
- Add requested sections (key files, logic flow mermaid, user guide with prompt samples, guide for extending tool collection).
- Preserve existing marketing sections while tightening structure for readability.

## Proposed Structure (Top-Level Sections)
1. **Title & Badges** (retain existing hero block).
2. **Why Security MCP Server?** (unchanged, tighten language if needed).
3. **Features** (retain subsections).
4. **Architecture Overview**
   - Keep existing mermaid architecture diagram.
   - Add new mermaid logic flow diagram showing request lifecycle: client → transport → server → tool runner → metrics/health.
5. **Quick Start**
   - Option 0: Launcher script (already added) – refine wording.
   - Option 1: Docker (revise to reflect updated Dockerfile, image build, compose usage, include note for non-Linux users).
   - Option 2: Local installation (retain with updated dependency list).
6. **Key Files & Directories**
   - Add table summarizing major paths: `scripts/mcp_server_launcher.sh`, `Dockerfile`, `docker/entrypoint.sh`, `mcp_server/server.py`, `mcp_server/tools/`, `docs/`, `mcp.json`, etc.
7. **User Guide**
   - Explain health check, tool execution workflow, mention `mcp_client.py` / `mcp_stdio_client.py` usage.
   - Provide sample prompts for coding agents (reuse and expand from existing AI integration section).
8. **AI Coding Agent Integration**
   - Reference `mcp.json`, launcher requirements, prompts (may consolidate with User Guide or keep separate subsections).
9. **Extending the Tool Collection**
   - Step-by-step guide for adding a new tool referencing `mcp_server/base_tool.py` patterns, config updates, health check registration.
10. **Configuration** (existing env vars and YAML snippet; update cross-links).
11. **Deployment**
   - Revise Docker subsection with clarified commands (`docker-compose up -d`, rebuild, volumes).
   - Mention Prometheus/Grafana stack, metrics endpoints.
12. **Observability & Alerts** (point to `docker/alerts.yml`, `docker/prometheus.yml`).
13. **Testing**, **Contributing**, **Roadmap**, **Community**, **License** (retain but ensure cross-references updated).

## Content Updates Needed
- **Docker Deployment**: note that the container image now bundles `nmap`, `masscan`, `gobuster`, `hydra`, `sqlmap`; provide build command and link to `start-docker.md`.
- **Key Files**: verify descriptions from actual files (use references such as `scripts/mcp_server_launcher.sh` to explain purpose).
- **Mermaid Logic Flow**: base on `mcp_server/server.py` request handling: HTTP request → FastAPI router → `ToolRegistry` → `MCPBaseTool` execution → metrics logging → health updates.
- **User Guide**: include HTTP sample (`curl`), client script usage (`python3 mcp_client.py`), SSE events mention, safety considerations.
- **Prompt Examples**: adapt existing prompts and add at least two more covering Hydra and Nmap workflows aligned with RFC1918 enforcement.
- **Tool Extension Guide**: reference `docs/TOOLS.md` if exists; otherwise outline steps (create new file under `mcp_server/tools/`, update registry, add health check if needed).

## Validation Checklist
- Confirm all referenced files exist and match descriptions.
- Ensure commands align with updated scripts and Docker assets.
- Verify new mermaid diagram renders (syntax check).
- Cross-link to new documentation files (`docs/security-mcp-tools-availability-subplan.md`, etc.) only if appropriate.
- Review final README for broken anchors after reordering sections.
