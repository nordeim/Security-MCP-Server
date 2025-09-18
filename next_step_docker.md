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

https://github.com/copilot/share/c8111184-0804-8cd5-a900-7e48a46921e2
