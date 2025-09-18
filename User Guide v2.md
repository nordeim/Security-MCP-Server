# Comprehensive User Guide: Enhanced MCP Server for Security Assessment

## Table of Contents
1. [Introduction](#introduction)
2. [Getting Started](#getting-started)
3. [Tool Overview](#tool-overview)
4. [Usage Scenarios with Prompts](#usage-scenarios-with-prompts)
   - [Network Discovery](#network-discovery)
   - [Port Scanning](#port-scanning)
   - [Service Enumeration](#service-enumeration)
   - [Web Application Testing](#web-application-testing)
   - [SQL Injection Testing](#sql-injection-testing)
   - [Password Security Testing](#password-security-testing)
   - [Comprehensive Assessment Workflows](#comprehensive-assessment-workflows)
5. [Best Practices](#best-practices)
6. [Security Considerations](#security-considerations)
7. [Troubleshooting](#troubleshooting)
8. [Advanced Usage](#advanced-usage)

---

## Introduction

### What is the Enhanced MCP Server?

The Enhanced MCP (Model Context Protocol) Server is a **security-focused, production-ready platform** that integrates powerful security tools with Large Language Models (LLMs) like ChatGPT and Claude. It provides a controlled environment for LLM-driven security assessments, with strong validation, logging, and operational guardrails.

### Key Features

- **Security-First Design**: All tools include comprehensive input validation, rate limiting, and security controls
- **Circuit Breaker Protection**: Prevents cascading failures and system overload
- **Comprehensive Monitoring**: Real-time metrics and health monitoring
- **Multi-Tool Integration**: Unified interface for Nmap, Masscan, Gobuster, Sqlmap, and Hydra
- **LLM-Native**: Designed specifically for seamless LLM integration

### Why Use This MCP Server with LLMs?

1. **Natural Language Security Assessment**: Describe security goals in plain English
2. **Automated Tool Selection**: LLMs can intelligently choose the right tool for each task
3. **Context-Aware Analysis**: LLMs can interpret results and provide actionable insights
4. **Workflow Orchestration**: Chain multiple security assessments in logical sequences
5. **Safety and Compliance**: Built-in guardrails ensure responsible usage

---

## Getting Started

### Prerequisites

1. **MCP Server Running**: Ensure the MCP server is deployed and accessible (via Docker Compose or direct Python execution)
2. **LLM Access**: Access to an LLM that supports MCP (like Claude Desktop)
3. **Network Access**: Access to target RFC1918 networks or .lab.internal domains
4. **Proper Authorization**: Legal authorization to test target systems

### Basic Setup (Docker Compose recommended)

```bash
# Clone and start the service
git clone https://github.com/nordeim/Security-MCP-Server.git
cd Security-MCP-Server
cp .env.template .env
# Edit .env as required
docker-compose up -d --build
```

Wait for the `security-mcp-server` container to be healthy. Verify:

```bash
docker-compose ps
curl -f http://localhost:8080/health
```

Prometheus is available inside the compose network at http://prometheus:9090. In the repository's docker-compose.yml it may be mapped to the host as http://localhost:9091/targets (or adjust the mapping to host 9090 if you prefer).

### Running Locally (development)
You can also run the server directly for development (ensure Python dependencies installed in a venv):

```bash
python -m mcp_server.server
```

This runs the server in the foreground — Docker is recommended for production or for running the compiled toolset.

### First Interaction Test

Prompt to the LLM:

```
Hello! I have access to security assessment tools through MCP. Can you help me understand what tools are available and how to use them safely?
```

---

## Tool Overview

### Available Tools

| Tool | Purpose | Typical Use |
|------|---------|-------------|
| Nmap | Network scanning and service discovery | Network inventory, port discovery |
| Masscan | High-speed port scanning | Large network reconnaissance (use with care) |
| Gobuster | Web content discovery | Directory/file enumeration, DNS discovery |
| Sqlmap | SQL injection testing | Database vulnerability assessment |
| Hydra | Password security testing | Credential strength validation |

### Security Restrictions

- **Target Validation**: All tools accept only RFC1918 addresses or .lab.internal hostnames by default
- **Rate Limiting**: Built-in concurrency and rate limits prevent system overload
- **Argument Validation**: Strict allowlists for command flags
- **Circuit Breakers**: Automatic protection against repeated failures

---

## Usage Scenarios with Prompts

(Abbreviated here; full scenario examples are included in the repository. The guide provides tested, safe prompts for each workflow.)

### Network Discovery

#### Two-phase approach (Masscan + Nmap)
```
1. Use Masscan for a fast sweep of 10.0.0.0/16 for common ports (80, 443, 22)
2. For discovered hosts, use Nmap for detailed service enumeration
```

### Port Scanning
Examples include targeted scans, full port scans, and service-specific scans — always start conservative and increase scope only with authorization.

### Web Application Testing
Use Gobuster for directory enumeration and Sqlmap for conservative SQL injection tests (risk level 1, test level 1).

### Password Security Testing
Use Hydra with small, safe wordlists and strict thread limits. Avoid aggressive brute force operations.

---

## Best Practices

- Always have explicit written authorization.
- Start small: small networks and conservative flags.
- Use logging and retain results securely.
- Use Prometheus/Grafana to monitor resource usage and tool behavior.
- Do not exfiltrate or retain sensitive data unnecessarily.

---

## Security Considerations

### Legal & Ethical
- Obtain written permission before testing
- Define scope and time windows
- Follow responsible disclosure procedures

### Operational Controls
- Target validation and allowlists to avoid unsafe targets/flags
- Circuit breakers to avoid cascading issues
- Rate limiting to protect the network and scanning host

---

## Troubleshooting

- If tools fail to execute, check that the tool binaries exist in the container (builder stage should install them).
- If health shows degraded, check psutil availability and Prometheus connectivity.
- For long builds: the builder compiles native tools; ensure sufficient memory and CPU during build.

---

## Advanced Usage

- Multi-tool workflows: chain Masscan -> Nmap -> Gobuster -> Sqlmap/Hydra for progressive assessment.
- Integrations: SIEM and ticketing systems can consume the server's structured output (JSON) for automated workflows.

---

## Appendix: Quick commands

- docker-compose up -d --build
- docker logs -f security-mcp-server
- curl -f http://localhost:8080/health
- Prometheus targets: http://localhost:9091/targets (or http://localhost:9090/targets if you map to host 9090)
