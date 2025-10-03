# Security-MCP-Server Architecture Overview

## Executive Summary
The `Security-MCP-Server` is an enterprise-ready Model Context Protocol (MCP) server that orchestrates security tooling safely for LLM-driven workflows. It bridges natural-language security requests from clients like Claude Desktop to tightly controlled execution of reconnaissance, scanning, and validation tools across private lab networks.

## Layered System Model
- **Client Layer**: LLM clients, CLIs, and HTTP integrations communicate intent in natural language or structured requests.
- **Transport Layer**: Supports stdio for local tooling and HTTP/REST for service deployments, enforcing secure communication pathways.
- **Server Core**: `server.py` coordinates lifecycle, tool registry, routing, shutdown, and overall orchestration logic.
- **Tool Framework**: `base_tool.py` supplies validation hooks, execution guards, resource limiting, and cross-tool abstractions.
- **Tool Implementations**: Specialized modules (Nmap, Masscan, Gobuster, Sqlmap, Hydra) embed domain-specific command execution with safety constraints.
- **Infrastructure Services**: Configuration (`config.py`), health monitoring (`health.py`), metrics (`metrics.py`), and circuit breakers (`circuit_breaker.py`) provide resilience and observability.

## Security Controls & Safety Guarantees
- **Input Validation**: Multi-stage validation of targets, arguments, and tool-specific parameters before execution.
- **Circuit Breakers**: Automatic detection of repeated failures per tool instance to prevent cascading issues.
- **Resource Governance**: Enforced CPU, memory, output, and concurrency limits alongside subprocess isolation (no shell interpolation).
- **Network Guardrails**: Restricts scanning activity to RFC1918 address space by default, aligning with lab and authorized environments.
- **Audit & Compliance**: Structured JSON logging, audit trails, and Prometheus metrics enable traceability and compliance reporting.

## Tooling Portfolio
- **NmapTool**: Safe network scanning capped at 1024 hosts with sanitized script usage and rate controls.
- **MasscanTool**: High-speed port scanning constrained to safe packet rates and network sizes (max /16).
- **GobusterTool**: Web enumeration with thread limits and validated wordlists.
- **SqlmapTool**: SQL injection testing restricted to risk levels 1-2 and test levels 1-3.
- **HydraTool**: Credential strength assessment with guarded service lists and password hygiene.

## Reliability & Operations
- **Resilience**: Adaptive timeouts, exponential backoff, and fail-safe defaults maintain availability under stress.
- **Health Monitoring**: Real-time checks for system resources, process state, and per-tool readiness.
- **Observability Stack**: Prometheus metrics, Grafana dashboards, structured logging, and SSE events support diagnosis and reporting.
- **Deployment Paths**: Docker Compose bundles, local Python environments, and hot-reloadable configs facilitate flexible rollouts.

## Key Differentiators
- LLM-first interaction model lowers friction for SOC and DevSecOps teams.
- Enterprise-grade guardrails combine compliance, safety, and operational visibility.
- Extensible framework simplifies onboarding of new security tools with consistent governance.
- Comprehensive monitoring and recovery mechanisms foster trustworthy automation.

## Intended Users & Use Cases
- **Target Personas**: SOC analysts, DevSecOps engineers, penetration testers, and security researchers.
- **Primary Scenarios**: Automated incident response, CI/CD security gates, reconnaissance automation, performance benchmarking, and tool prototyping.

This document distills the foundational intent and architecture captured in `CLAUDE.md` to support future onboarding, audits, and architectural decisions.
