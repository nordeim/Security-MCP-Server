Notes for .env.template
- The .env.template looks fine. Just a reminder in the README or top of .env.template to instruct users to create a .env file (docker-compose reads .env) — e.g. `cp .env.template .env` — which your README already instructs. If you intentionally want Prometheus host exposed at 9091 on the host, revert the docker-compose change I made.

What I changed and why (concise)
- Dockerfile: set GOBIN to /usr/local/bin, named final stage "runtime", fixed HEALTHCHECK to use curl (robust), and copied gobuster from the right path.
- docker-compose.yml: set build target to runtime (matches Dockerfile), switched Prometheus host port to 9090 to match README, replaced fragile Python-based healthcheck with curl-based one.
- entrypoint.sh: made dependency wait more robust, verified curl availability, safe PYTHONPATH handling, and improved Python import validation.

Next steps and recommendations
- Run a local build: docker-compose build --no-cache security-mcp-server to verify the builder stage produces the expected binaries.
- If builder installation of hydra or masscan places binaries in non-/usr/local/bin locations on some distributions, add checks or use explicit install prefixes to ensure binaries end up in /usr/local/bin (or adjust COPY sources).
- Consider reducing image size by:
  - Using multi-stage to only copy required tool binaries and dependencies.
  - Removing large -dev packages from final image (they are already in builder; runtime still installs many -dev packages — evaluate if they're necessary).
- Add automated CI check to validate:
  - Dockerfile build completes (ci runs docker build --target runtime).
  - Container healthchecks succeed via docker-compose up in a test environment.
- Ensure requirements.txt includes 'requests' only if you actually rely on it at runtime. Current healthchecks use curl, so requests is not necessary for health checks.

---

Why these changes
- Explicit timings (scrape_timeout) prevent Prometheus from waiting indefinitely; keeping scrape_timeout smaller than or equal to scrape_interval avoids overlapping scrapes.
- external_labels help when you federate or aggregate metrics (and are helpful if you run multiple monitoring stacks).
- relabel_configs produce cleaner instance labels (convenient for alerting and dashboards).
- Explicit scheme and metrics_path avoid confusion if any service uses HTTPS or a non-standard path.
- The grafana job is optional but useful to include; it's commented in the file to warn about Grafana config dependency.

Validation checklist (how you can verify locally)
1. Ensure docker-compose exposes ports consistently:
   - prometheus service container port should be 9090 (host mapping may be different). The compose I suggested binds host:container 9090:9090.
2. Start the stack:
   - docker-compose up -d
3. Check Prometheus targets UI:
   - Visit http://localhost:9090/targets (or host port you mapped)
   - Verify targets "prometheus", "security-mcp-server", and "grafana" (if used) show UP
   - If a target is DOWN, click the target to see scrape error details.
4. Query the targets via API:
   - curl -sS http://localhost:9090/api/v1/targets | jq
   - Inspect the returned JSON for statuses and lastError fields.
5. If a target is not discoverable:
   - From inside the prometheus container, test DNS/networking:
     - docker exec -it prometheus sh
     - ping -c 3 security-mcp-server
     - curl -f http://security-mcp-server:9090/metrics
6. If Grafana metrics don't appear, ensure grafana.ini has metrics enabled.
7. If you plan to add Alertmanager, add the actual target(s) under alertmanagers and add rules under rule_files.

Potential follow-up improvements (optional)
- Add file_sd or consul_sd if dynamic service discovery is needed.
- Add TLS/Basic auth scraping settings if any targets require auth.
- Add recording rules for costly queries you plan to reuse often.
- Add alerting rules for health checks (down targets, high error rates, resource saturation).

https://github.com/copilot/share/c8111184-0804-8cd5-a900-7e48a46921e2
https://github.com/copilot/share/c8111184-0804-8cd5-a900-7e48a46921e2
