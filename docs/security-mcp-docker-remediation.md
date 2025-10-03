# Docker Deployment Remediation TODOs

## Context
- The production `Dockerfile` installs `nmap`, `masscan`, and `gobuster`, but not `hydra` or `sqlmap`, so containerized runs still report tool availability failures.
- `docker/entrypoint.sh` only warns when those binaries are missing; once the image includes them, health checks will pass without manual intervention.
- Documentation (`start-docker.md`, `docker-compose*.yml`) references the container option for non-Linux users and should mention the updated dependency coverage once the image is rebuilt.

## Planned Actions
- [ ] **Update Dockerfile**: add `hydra` and `sqlmap` to the apt-get install list so all five required tools are present inside the container.
- [ ] **Rebuild and validate**: run `docker build` / `docker-compose up --build` and confirm `/health` reports `status":"healthy"` with all tool checks passing.
- [ ] **Adjust entrypoint logging (optional)**: consider promoting missing-tool warnings to errors if future edits remove any required binary.
- [ ] **Refresh docs**: update `start-docker.md` (and any Docker-related README sections) to note the new all-in-one coverage and rebuild requirement.

## Validation Steps
1. After rebuilding the image, execute `docker-compose up -d` and `curl http://localhost:8080/health`.
2. Inspect container logs to ensure `docker/entrypoint.sh` no longer warns about missing tools.
3. Run `python3 mcp_client.py` against the containerized server to verify tool execution succeeds.
