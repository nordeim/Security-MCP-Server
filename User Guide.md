# Comprehensive User Guide: Enhanced MCP Server for Security Assessment

This User Guide provides thorough operational, security, and usage guidance for the Security MCP Server. It is intended for authorized security teams, developers, and system operators.

> Strong warning: This project integrates offensive/security tooling. Do not run scans against systems without explicit written authorization.

## Table of Contents
- Introduction
- Getting Started
- Tool Overview
- Usage Scenarios with Example Prompts
- Best Practices
- Security Considerations (Legal & Operational)
- Troubleshooting
- Advanced Usage
- Appendix: Quick CLI / Docker commands and validation

## Introduction
The Enhanced MCP Server enables LLMs to orchestrate multiple security tools in a controlled environment. It provides guardrails (target validation, rate limits, argument sanitization), observability (Prometheus/Grafana), and fault tolerance (circuit breakers).

## Getting Started

### Prerequisites
- Docker & Docker Compose installed
- Sufficient machine resources (8GB RAM recommended for builds)
- Written approval to test networks/systems

### Start locally (development)
1. clone repo
2. cp .env.template .env and edit
3. docker-compose up -d --build
4. Verify:
   - Server container: docker-compose ps
   - Health: curl -f http://localhost:8080/health
   - Prometheus targets: http://localhost:9090/targets

### Run server directly (development non-container)
If you prefer to run Python locally (developer mode):
```bash
python -m mcp_server.server
```
(Use virtualenv that includes dependencies in requirements.txt; note the Docker image is the recommended runtime for consistent behavior.)

## Tool Overview
Short summary of tools and intended use:
- Nmap — detailed host/service discovery and version detection
- Masscan — high-speed port discovery (use with care)
- Gobuster — content and virtual-host discovery
- Sqlmap — targeted SQL injection testing
- Hydra — password security testing (use extremely conservatively)

## Usage Scenarios & Prompts
(Examples in detail; see repo for full list — many handcrafted prompts are included in this guide.)

### Example: Two-phase network discovery
1. Masscan for wide, fast discovery (limit rate/concurrency)
2. Nmap for targeted enumeration on discovered hosts

(Example prompt provided in the repository README and expanded in this guide.)

## Best Practices
- Always verify authorization and scope
- Start with small ranges and conservative settings
- Use logging and central storage for results
- Enable Prometheus and Grafana for metrics and health monitoring

## Security Considerations
- Target validation restricts targets to RFC1918 and .lab.internal by default (configurable)
- Audit logs must be retained for compliance and incident review
- Follow responsible disclosure and do not exfiltrate data

## Troubleshooting
- Container build failures: increase resources, inspect builder logs for failed compilation of native tools.
- Tool not found at runtime: ensure builder stage completed and binaries were copied into final image.
- Health endpoint returns degraded: check psutil availability (optional) and ensure Prometheus (if used) is reachable.

## Appendix: Quick verification commands
- docker-compose up -d --build
- docker logs -f security-mcp-server
- curl -f http://localhost:8080/health
- Visit: http://localhost:9090/targets and http://localhost:3000 (Grafana)
