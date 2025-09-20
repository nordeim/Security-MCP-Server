Nice work — your assessment is thoughtful and most recommendations are correct. I carefully validated each finding and improved/clarified several points, fixed minor mistakes, and added precise, safe alternatives you can apply immediately. Summary (what I validated and changed):

- Build success summary: plausible and fine — nothing to change there.
- Your four high-priority issues are real (deploy/reservations warning, healthcheck fragility, depends_on race, volume/config write conflict). I confirmed their root causes and refined the fixes and caveats.
- I corrected a YAML syntax bug in your “Immediate Fix” snippet (an extra quote) and strengthened the healthcheck and depends_on recommendations with accurate Compose compatibility notes and safer alternatives.
- Added concrete, copy/paste-ready YAML strings and exact shell healthcheck command that will work reliably on minimal images and in Compose.

Detailed review and corrections

1) Deploy.resources.reservations warning — validated
- Your diagnosis is correct: compose (docker-compose up) ignores deploy.* semantics in many environments and emits warnings for reservations.
- Clarification and actionable options:
  - If you run with docker stack deploy (Swarm) — keep deploy.resources.{limits,reservations}.
  - If you run with docker-compose up (most local/dev uses), remove reservations or move to Compose v2 style resource constraints (which is a different format) or accept the warning and rely on host-level cgroups. The simplest: remove the reservations subsection from compose to silence the warning.

2) Healthcheck command fragility — refined and fixed
- Problem: curl may not exist in minimal runtime images. Your wget fallback idea is good but can be made more robust and concise.
- Use a CMD-SHELL test that tries wget then curl and exits non-zero if neither succeeds — works on minimal images that have sh:
  - Recommended healthcheck entry:

    test: ["CMD-SHELL", "sh -c 'command -v wget >/dev/null 2>&1 && wget -q --spider http://localhost:8080/health || command -v curl >/dev/null 2>&1 && curl -sf http://localhost:8080/health || exit 1'"]

- This checks for wget first, then curl, and fails if both are missing or the endpoint returns non-2xx.

3) depends_on race condition — nuance & safer approach
- Your statement that depends_on only waits for start (not readiness) is correct.
- Caveat: the depends_on condition syntax (service_healthy) is supported by docker-compose but not by Docker Swarm. Behavior differs by tool/version.
- Recommended approach:
  - Keep a lightweight depends_on to ensure ordering when possible, but rely on application-level wait logic (entrypoint) to confirm readiness. Your image already has entrypoint logic that waits for Prometheus — prefer that as the canonical readiness check.
  - If you want compose-only solution and you run docker-compose (not stack deploy), you can use:
    depends_on:
      prometheus:
        condition: service_healthy
  - If you must support swarm or portability, remove condition and rely on health-check based polling in entrypoint/wait-for-it.

4) Volume mount / config generation conflict — critical
- You correctly flagged this: mounting /app/config as a read-only named volume and then trying to generate into it will fail.
- Options (pick one):
  - Make mcp-config writable (remove :ro) so entrypoint can generate config into /app/config.
  - Leave /app/config read-only and modify entrypoint to detect writability; if not writable, write generated config to a writable location (e.g., /app/config-local or /app/data) and set the server to read that path (or set MCP_CONFIG_PATH to that fallback).
  - Prefer explicit: mount config rw in production via the named volume and use :ro for bind-mounts only in dev overrides.
- I recommend: change compose to mount the named volume as rw in production, and keep bind mounts and :ro only in the override development file.

5) Traefik labels without Traefik service — validated
- Correct: remove or add Traefik. If Traefik is provided externally or as a stack service, labels are fine; otherwise remove them to avoid confusion.

6) Other important refinements I added
- Build cache_from: adding python:3.12-slim-trixie to cache_from is only useful if that tag exists locally; acceptable as optional optimization but not critical.
- Resource limits: note that deploy.resources in Compose is primarily for Swarm; docker-compose up ignores it. If you need local enforcement, use legacy v2 style mem_limit or rely on systemd/cgroup enforcement or run in a Swarm/Kubernetes environment.
- Security hardening: read_only: true is fine but ensure writable dirs are mounted as volumes (logs, data). Also keep tmpfs entries for /tmp and /var/tmp. If read_only is enabled, ensure entrypoint does not attempt writes to other root-owned directories.
- Network simplification: removing mcp-public is fine if no external exposure is required; ensure prometheus and grafana are still attached to networks needed for scraping and access.
- Health env var consistency: your healthcheck scripts/entrypoint use different variable names (HEALTH_CHECK_TIMEOUT vs MCP_HEALTH_TIMEOUT). Standardize these names.

Fixed/Improved copy-paste YAML for the mcp-server service
- I fixed the stray quote and included a robust healthcheck command, removed reservations, kept deploy.limits (with note), and recommended network/volume adjustments. Use this version (paste into your compose, adjusting as needed):

```yml
mcp-server:
  container_name: mcp-server
  image: mcp-server:${MCP_VERSION:-latest}
  build:
    context: .
    dockerfile: Dockerfile
    args:
      PYTHON_VERSION: ${PYTHON_VERSION:-3.12}
    cache_from:
      - mcp-server:latest

  restart: unless-stopped

  networks:
    - mcp-internal

  ports:
    - "${MCP_SERVER_PORT:-8080}:8080"
    - "${MCP_METRICS_PORT:-9090}:9090"

  volumes:
    # In production prefer writable named volume so entrypoint can generate config
    - mcp-config:/app/config:rw
    - mcp-logs:/app/logs:rw
    - mcp-data:/app/data:rw
    # For local development keep bind mounts in docker-compose.override.yml

  environment:
    # ... (existing environment variables)

  deploy:
    resources:
      limits:
        cpus: '${MCP_CPU_LIMIT:-2.0}'
        memory: ${MCP_MEMORY_LIMIT:-1G}

  healthcheck:
    # Robust check: prefer wget, fallback to curl, fail if neither exists or endpoint unhealthy
    test: ["CMD-SHELL", "sh -c 'command -v wget >/dev/null 2>&1 && wget -q --spider http://localhost:8080/health || command -v curl >/dev/null 2>&1 && curl -sf http://localhost:8080/health || exit 1'"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 60s

  # If you're using docker-compose (not swarm) and want compose-level dependency-based wait:
  # depends_on:
  #   prometheus:
  #     condition: service_healthy
  # However, note: depends_on.condition is not honored by Swarm; prefer application-level waits.
  depends_on:
    - prometheus

  labels:
    - "prometheus.io/scrape=true"
    - "prometheus.io/port=9090"
    - "prometheus.io/path=/metrics"
```

Additional precise technical notes & fixes you should apply now
- Fix syntax bug: in your posted snippet the memory line had an extra apostrophe; I corrected that above.
- Align health env var names:
  - docker/healthcheck.sh uses HEALTH_CHECK_TIMEOUT; entrypoint uses MCP_HEALTH_TIMEOUT. Pick one name (I suggest MCP_HEALTH_TIMEOUT) and export it for healthcheck script, or change healthcheck.sh to read MCP_HEALTH_TIMEOUT.
- Entrypoint already polls Prometheus. Keep that behavior — it is a safer portability pattern than depending purely on compose conditions.
- If your container will run scanning tools that require raw sockets, surface this in docs and provide an optional cap_add block in docker-compose.override.yml for development:
  - cap_add: ["NET_RAW", "NET_ADMIN"]
  - Do NOT run the container as root just to allow scanning.
- Permissions: ensure any "read_only: true" root filesystem keeps /app/logs and /app/data mounted as volumes and writable by the container user.

Priority action list (reordered & precise)
Immediate (apply now)
1. Change mcp-config volume to rw or change entrypoint to write to a writable fallback directory (I recommend the volume -> rw approach).
2. Replace the healthcheck test string with the robust CMD-SHELL string above.
3. Remove deploy.resources.reservations to eliminate warnings (if you run docker-compose up).

Short-term (this release)
4. Standardize health timeout env var names (MCP_HEALTH_TIMEOUT).
5. Document scanning capability requirements and provide optional cap_add in dev override.
6. Fix the stray quote in your provided snippet (done above).

Medium-term
7. Add CI linting jobs (hadolint, yamllint, docker-compose config, trivy/dockle)
8. Add read_only root filesystem + tmpfs + no-new-privileges once permissions and writable mounts are validated.

Optional improvements
- Use entrypoint wait logic as the canonical readiness detector (already present).
- If you want compose to enforce resource reservations on production hosts, use Swarm/Kubernetes.

What I can do next
- Produce a small patch/PR that:
  - Changes the compose mcp-server service as above
  - Removes reservations
  - Fixes healthcheck and the volume rw/read-only mismatch
  - Standardizes health env names
- Or I can generate a CI workflow (GitHub Actions) that runs hadolint, yamllint, docker-compose config, build, and trivy/dockle scans.

Tell me which of those you want me to do next and I’ll create the patch or the CI workflow right away.

https://github.com/copilot/share/80511114-0024-84f3-8912-ec48846b69f2
