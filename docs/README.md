# Security MCP Server

[![Docker](https://img.shields.io/badge/Docker-Ready-blue?style=for-the-badge&logo=docker)](https://www.docker.com/)
[![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-Ready-green?style=for-the-badge&logo=githubactions)](https://github.com/features/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![Claude](https://img.shields.io/badge/Claude-Desktop-purple?style=for-the-badge)](https://claude.ai/)

A production-ready MCP (Model Context Protocol) server that integrates security tools (gobuster, hydra, masscan, sqlmap) with LLMs such as Claude Desktop. It provides safe, auditable tool execution with strict target validation, rate limiting, circuit breakers and observability.

IMPORTANT: These tools are powerful and can be disruptive. Only use this server to scan systems and networks you own or for which you have explicit written authorization. See the User Guide (Security & Legal) for details.

## Table of Contents
- [Overview](#overview)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Usage Examples](#usage-examples)
- [CI/CD Integration](#cicd-integration)
- [Workflow Diagram](#workflow-diagram)
- [Contributing](#contributing)
- [License](#license)

## Overview

The Security MCP Server bridges Claude Desktop and other MCP-capable LLMs with powerful security tools, exposing them in a controlled, auditable fashion. The server validates inputs, sanitizes arguments, applies rate limits, and applies circuit breakers to prevent cascading failures.

## Features

- Multi-tool support: Gobuster, Hydra, Masscan, SQLMap (packaged into the container image)
- Target validation: only RFC1918 and .lab.internal by default (configurable)
- Argument sanitization and safe defaults
- Rate limiting and concurrency control
- Circuit breaker pattern for fault tolerance
- Prometheus metrics + Grafana dashboards support
- Hot-reloadable configuration with environment overrides

## Prerequisites

- Docker 20.10+
- Docker Compose 1.29+
- Git
- Sufficient RAM (4GB minimum, 8GB recommended) and disk
- Authorized access to targets you intend to scan (legal & ethical requirement)

## Quick Start

1. Clone the repository
```bash
git clone https://github.com/nordeim/Security-MCP-Server.git
cd Security-MCP-Server
```

2. Create a .env file from the template
```bash
cp .env.template .env
```
Edit `.env` as needed. Key settings:
- MCP_SERVER_HOST — bind address (default 0.0.0.0)
- MCP_SERVER_PORT — server port (default 8080)
- WAIT_FOR_DEPENDENCIES — true/false for docker entrypoint waiting on Prometheus
- PROMETHEUS_URL — internal Prometheus URL (default http://prometheus:9090)

3. Start the stack (first run build can be long because it compiles tools)
```bash
docker-compose up -d --build
```

Notes:
- The Docker image builds security tools (nmap/gobuster/masscan/hydra/sqlmap); the builder stage may take several minutes.
- If you change the Dockerfile or requirement lists, rebuild with --no-cache to ensure a fresh image.

4. Verify containers
```bash
docker-compose ps
```
Check the MCP server logs:
```bash
docker logs -f security-mcp-server
```

5. Check server health and metrics
- Server health endpoint (example):
  - http://localhost:8080/health
- Prometheus UI (default):
  - http://localhost:9090/targets
- Grafana (if enabled):
  - http://localhost:3000 (admin/admin or configured password)

6. Configure Claude Desktop (example — using docker exec)
- Option A: run the MCP server as a container, then configure Claude to exec into it:
```json
{
  "mcpServers": {
    "security": {
      "command": "docker",
      "args": ["exec", "-i", "security-mcp-server", "python", "-m", "mcp_server.server"],
      "env": {}
    }
  }
}
```
- Option B: Use HTTP transport exposed by the server (if you run the server with http transport) — configure the MCP transport and endpoint in your LLM/client according to the MCP spec.

7. Test a simple prompt (from Claude Desktop)
```
Can you help me scan my local network for open ports using masscan? I want to scan the 192.168.1.0/24 network for ports 80, 443, and 22.
```

## Security & Legal
- ALWAYS obtain written authorization prior to testing systems/networks.
- Use conservative settings in production and start with small scopes.
- Keep audit logs and follow your organization’s incident response procedures.
- Refer to the included User Guide for detailed security, legal, and ethical guidance.

## Troubleshooting (short)
- If container fails to start: check `docker logs security-mcp-server`.
- If tools are missing: check build logs; some tools are compiled in builder stage and will appear in /usr/local/bin or /opt/security-tools/bin.
- If Prometheus is unreachable: ensure docker-compose mapped ports correctly (9090) and that `PROMETHEUS_URL` matches the docker-compose network.

## CI/CD Integration
The repository includes a sample GitHub Actions workflow that:
- Builds the Docker image
- Runs tests inside the image
- Optionally scans the repository with Bandit
- Pushes an image to DockerHub if on main branch

(See .github/workflows for the pipeline YAML)

## Contributing
See the "Contributing" section below and the User Guide for development and testing instructions.

## License
MIT. See LICENSE file.
