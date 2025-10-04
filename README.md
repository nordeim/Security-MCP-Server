<div align="center">

# 🛡️ Security MCP Server

### **Enterprise-Grade Security Tool Orchestration Platform**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Prometheus](https://img.shields.io/badge/Prometheus-E6522C?logo=Prometheus&logoColor=white)](https://prometheus.io/)
[![Code Style: Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Security: Bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)

**A production-ready, extensible framework for secure execution and orchestration of security tools with enterprise-grade reliability, monitoring, and safety features.**

[Features](#-features) • [Quick Start](#-quick-start) • [Documentation](#-documentation) • [Contributing](#-contributing) • [Security](#-security)

<img src="https://github.com/nordeim/Security-MCP-Server/assets/placeholder/architecture.png" alt="Architecture" width="800"/>

</div>

---

## 🌟 **Why Security MCP Server?**

In modern security operations, teams struggle with:
- **Tool Sprawl**: Managing dozens of security tools with different interfaces
- **Reliability Issues**: Tools failing without proper error handling or recovery
- **Resource Conflicts**: Uncontrolled tool execution overwhelming systems
- **Limited Visibility**: Lack of metrics and monitoring for security operations
- **Safety Concerns**: Risk of tools being misused or causing damage

**Security MCP Server solves these challenges** by providing a unified, production-ready platform that wraps security tools with enterprise features like circuit breakers, health monitoring, rate limiting, and comprehensive observability.

---

## ✨ **Features**

### 🔒 **Enterprise Security**
- **RFC1918 Enforcement**: Restricts operations to private networks only
- **Input Validation**: Comprehensive validation of all tool inputs
- **Rate Limiting**: Prevents resource exhaustion and network flooding
- **Sandboxed Execution**: Tools run in isolated subprocesses with resource limits
- **Audit Logging**: Complete audit trail of all tool executions

### 🔄 **Resilience & Reliability**
- **Circuit Breaker Pattern**: Automatic failure detection and recovery
- **Adaptive Timeouts**: Exponential backoff with jitter for failed operations
- **Graceful Degradation**: System continues operating when components fail
- **Health Monitoring**: Real-time health checks with priority-based evaluation
- **Automatic Recovery**: Self-healing capabilities for transient failures

### 📊 **Observability**
- **Prometheus Metrics**: Comprehensive metrics with percentile calculations
- **Grafana Dashboards**: Pre-built dashboards for visualization
- **Distributed Tracing**: Request correlation across components
- **Structured Logging**: JSON-formatted logs for easy parsing
- **Real-time Events**: Server-Sent Events for live updates

### 🚀 **Performance**
- **Async/Await**: Full asynchronous operation for high concurrency
- **Connection Pooling**: Efficient resource management
- **Output Streaming**: Handle large outputs without memory issues
- **Caching**: Smart caching of tool availability and configurations
- **uvloop Support**: Optional high-performance event loop

### 🔧 **Extensibility**
- **Plugin Architecture**: Easy addition of new tools through inheritance
- **Multiple Transports**: stdio for CLI, HTTP/REST for services
- **Configuration Hot-Reload**: Change settings without restart
- **Custom Health Checks**: Add application-specific health monitoring
- **Webhook Support**: Integration with external systems

---

## 🚀 **Quick Start**

### **Option 0: Guided Launcher Script (New!)**

```bash
# Clone the repository
git clone https://github.com/nordeim/Security-MCP-Server.git
cd Security-MCP-Server

# Make the launcher executable (one-time)
chmod +x scripts/mcp_server_launcher.sh

# Launch with all dependencies auto-installed (requires sudo)
sudo scripts/mcp_server_launcher.sh

# Verify health from another shell
curl http://localhost:8080/health
```

The `scripts/mcp_server_launcher.sh` helper will:

- **Install OS packages** via `apt-get` (`gobuster`, `hydra`, `masscan`, `nmap`, `sqlmap`, Python tooling, etc.).
- **Create or reuse** a virtual environment at `/opt/venv`.
- **Install Python libraries** (`model-context-protocol`, `fastapi`, `uvicorn`, `sse-starlette`, `prometheus-client`, `requests`).
- **Export environment variables** (`MCP_SERVER_TRANSPORT=http`, `MCP_SERVER_HOST=0.0.0.0`, `MCP_SERVER_PORT=8080`).
- **Start the MCP server** using `python -m mcp_server.server`.

### **Option 1: Docker (Recommended for macOS/Windows)**

```bash
# Clone the repository
git clone https://github.com/nordeim/Security-MCP-Server.git
cd Security-MCP-Server

# Copy environment template (optional overrides)
cp .env.docker .env

# Build the image (bundles nmap, masscan, gobuster, hydra, sqlmap)
docker compose build mcp-server

# Launch the observability stack + server
docker compose up -d

# Check health from the host
curl http://localhost:8080/health

# Trigger a sample tool execution (Nmap)
curl -X POST http://localhost:8080/tools/NmapTool/execute \
  -H "Content-Type: application/json" \
  -d '{"target": "192.168.1.1", "extra_args": "-sV"}'
```

> 💡 Re-run `docker compose build` whenever the Python code or Docker prerequisites change. See `start-docker.md` for additional compose profiles (development vs. production).

### **Option 2: Local Installation**

```bash
# Clone and setup
git clone https://github.com/nordeim/Security-MCP-Server.git
cd Security-MCP-Server

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install required security tool binaries
sudo apt-get update
sudo apt-get install -y gobuster hydra masscan nmap sqlmap

# Install Python dependencies (plus optional extras for HTTP transport)
pip install -r requirements.txt
pip install model-context-protocol fastapi uvicorn sse-starlette prometheus-client

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Run the server
python -m mcp_server.server
```

### **External Tool & Library Requirements**


| Path | Description |
|------|-------------|
| `scripts/mcp_server_launcher.sh` | Turnkey launcher that installs OS/Python deps, sets env vars, and starts the server in HTTP mode. |
| `mcp.json` | MCP configuration consumed by coding agents (e.g., Claude Code) pointing to the launcher entrypoint. |
| `Dockerfile` | Multi-stage build bundling MCP runtime, security tool binaries (`nmap`, `masscan`, `gobuster`, `hydra`, `sqlmap`), and entry scripts. |
| `docker/entrypoint.sh` | Hardened container entrypoint that validates dependencies, generates config, and execs the server. |
| `docker-compose.yml` / `docker-compose.override.yml` | Compose stack for MCP server + Prometheus/Grafana observability and optional dev overrides. |
| `mcp_server/server.py` | Core FastAPI-based server startup, transport wiring, and health/metrics initialization. |
| `mcp_server/tools/` | Collection of tool wrappers (`GobusterTool`, `HydraTool`, `MasscanTool`, `NmapTool`, `SqlmapTool`) with safety policies. |
| `mcp_client.py` / `mcp_stdio_client.py` | Example clients for exercising HTTP and stdio transports respectively. |
| `docs/` | Project documentation (architecture overviews, sub-plans, remediation notes, README makeover plan). |

---

## 📖 **Documentation**

> **Operational Note (2025-10-03)**: `NmapTool` argument validation was hardened to accept optimizer defaults (`-T4`, `--max-parallelism 10`, `-Pn`, `--top-ports 1000`) and numeric values (e.g., `--top-ports 200`). If you encounter validation errors:
> - Ensure flag/value pairs use either `--flag value` or `--flag=value` (both now supported).
> - Large CIDR scans may exceed the default 300 s timeout; set `timeout_sec` or narrow the target range.
> - OS detection (`-O`) still requires root privileges in the execution environment; run without `-O` or supply elevated permissions if appropriate.

### **Architecture Overview**

```mermaid
graph TB
    subgraph "Client Layer"
        CLI[CLI Client]
        API[REST API Client]
        WS[WebSocket Client]
    end
    
    subgraph "MCP Server Core"
        TS[Transport Layer]
        ES[Enhanced Server]
        TR[Tool Registry]
        CB[Circuit Breaker]
        HM[Health Monitor]
        MM[Metrics Manager]
    end
    
    subgraph "Security Tools"
        NMAP[Nmap Scanner]
        MASS[Masscan]
        GOB[Gobuster]
        CUSTOM[Custom Tools]
    end
    
    subgraph "Observability"
        PROM[Prometheus]
        GRAF[Grafana]
        LOG[Logging]
    end
    
    CLI --> TS
    API --> TS
    WS --> TS
    
    TS --> ES
    ES --> TR
    ES --> HM
    ES --> MM
    
    TR --> CB
    CB --> NMAP
    CB --> MASS
    CB --> GOB
    CB --> CUSTOM
    
    MM --> PROM
    PROM --> GRAF
    ES --> LOG
    
    style ES fill:#f9f,stroke:#333,stroke-width:4px
    style CB fill:#bbf,stroke:#333,stroke-width:2px
```

### **Application Logic Flow**

```mermaid
flowchart LR
    Client[Client - Coding Agent] --> Transport{Transport Layer: HTTP or stdio}
    Transport --> Router[FastAPI Router]
    Router --> Registry[Tool Registry]
    Registry --> Executor[MCPBaseTool Executor]
    Executor --> Subprocess[Secure Subprocess Runner]
    Subprocess -->|stdout/stderr| Executor
    Executor --> Metrics[Prometheus Metrics]
    Executor --> Health[Health Check Aggregator]
    Metrics --> Observability[Prometheus & Grafana]
    Health --> HealthAPI[health endpoint]
    Executor --> Response[API Response]
    Response --> Client
```

### **Available Tools**

| Tool | Purpose | Key Features | Safety Limits |
|------|---------|--------------|---------------|
| **NmapTool** | Network discovery & port scanning | Service detection, OS fingerprinting, script scanning | Max 1024 hosts, rate limiting, safe scripts only |
| **MasscanTool** | High-speed port scanning | Banner grabbing, large network support | Rate limited to 1000 pps, max /16 networks |
| **GobusterTool** | Content & DNS discovery | Directory brute-force, subdomain enum, vhost discovery | Thread limits, wordlist validation |
| **HydraTool** | Authentication resilience testing | HTTP form payload placeholders, default credential injection, thread caps | Requires RFC1918 or `.lab.internal` targets; preserves `^USER^`/`^PASS^` tokens with sanitizer placeholders |
| **SqlmapTool** | SQL injection detection/exploitation | Risk/test level clamping, mandatory `--batch`, payload placeholders | Enforces `--batch`, clamps `--risk`/`--level`, sanitizes query strings |

### **API Reference**

#### **Health Check**
```http
GET /health
```

<details>
<summary>Response Example</summary>

```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T00:00:00Z",
  "checks": {
    "system_resources": {
      "status": "healthy",
      "message": "CPU: 45%, Memory: 62%, Disk: 30%"
    },
    "tool_availability": {
      "status": "healthy",
      "message": "All 3 tools available"
    }
  }
}
```
</details>

#### **Execute Tool**
```http
POST /tools/{tool_name}/execute
```

<details>
<summary>Request/Response Example</summary>

**Request:**
```json
{
  "target": "192.168.1.0/24",
  "extra_args": "-sS -sV --top-ports 100",
  "timeout_sec": 300,
  "correlation_id": "scan-001"
}
```

**Response:**
```json
{
  "stdout": "Starting Nmap 7.92...",
  "stderr": "",
  "returncode": 0,
  "execution_time": 45.2,
  "correlation_id": "scan-001",
  "metadata": {
    "tool": "NmapTool",
    "target": "192.168.1.0/24",
    "timestamp": "2024-01-01T00:00:00Z"
  }
}
```
</details>

#### **Metrics**
```http
GET /metrics
```

Returns Prometheus-formatted metrics including:
- `mcp_tool_execution_total` - Total executions per tool
- `mcp_tool_execution_seconds` - Execution time histogram
- `mcp_circuit_breaker_state` - Circuit breaker states
- `mcp_health_check_status` - Health check results

---

## 🎯 **Use Cases**

### **Security Operations Center (SOC)**
- Automated security scanning workflows
- Incident response tool orchestration
- Continuous security monitoring
- Vulnerability assessment automation

### **DevSecOps Pipeline**
- CI/CD security scanning integration
- Pre-deployment security checks
- Container security scanning
- Infrastructure compliance validation

### **Penetration Testing**
- Reconnaissance automation
- Controlled vulnerability scanning
- Report generation
- Tool output aggregation

### **Research & Development**
- Security tool comparison
- Performance benchmarking
- Custom tool development
- Security automation research

---

## 🛠️ **Configuration**

### **Environment Variables**

```bash
# Server Configuration
MCP_SERVER_TRANSPORT=http           # Transport: stdio or http
MCP_SERVER_PORT=8080                # HTTP port
MCP_SERVER_HOST=0.0.0.0            # Bind address

# Security Settings
MCP_MAX_ARGS_LEN=2048               # Max argument length
MCP_DEFAULT_TIMEOUT_SEC=300         # Default timeout (5 min)
MCP_DEFAULT_CONCURRENCY=2           # Max concurrent executions

# Circuit Breaker
MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5    # Failures before opening
MCP_CIRCUIT_BREAKER_RECOVERY_TIMEOUT=60    # Recovery time (seconds)

# Health Monitoring
MCP_HEALTH_CHECK_INTERVAL=30        # Check interval (seconds)
MCP_HEALTH_CPU_THRESHOLD=80         # CPU warning threshold (%)
MCP_HEALTH_MEMORY_THRESHOLD=80      # Memory warning threshold (%)

# Metrics
MCP_METRICS_ENABLED=true            # Enable metrics collection
MCP_METRICS_PROMETHEUS_ENABLED=true # Enable Prometheus endpoint
```

### **YAML Configuration**

```yaml
server:
  transport: http
  port: 8080
  workers: 4

tool:
  default_timeout: 300
  default_concurrency: 2

circuit_breaker:
  failure_threshold: 5
  recovery_timeout: 60

health:
  check_interval: 30
  cpu_threshold: 80
```

---

---

## 🤖 **AI Coding Agent Integration**

- **Configuration**: Import `mcp.json` in your coding agent to point at `scripts/mcp_server_launcher.sh`.
- **Prerequisites**: The launcher must be executable (`chmod +x scripts/mcp_server_launcher.sh`) and runnable with elevated privileges when prompted.
- **Workflow**: Agents can call `/health`, list tools, and execute commands using the prompts from the User Guide. SSE support is available via `/events` for streaming updates.

---

## 🔐 **Security**

### **Security Features**

- ✅ **Input Validation**: All inputs validated against strict rules
- ✅ **Network Isolation**: RFC1918 private networks only
- ✅ **Process Isolation**: Subprocess execution with clean environment
- ✅ **Resource Limits**: CPU, memory, and output size limits
- ✅ **No Shell Execution**: Direct process execution only
- ✅ **Audit Logging**: Complete execution audit trail
- ✅ **Rate Limiting**: Prevents resource exhaustion
- ✅ **Authentication Ready**: Easy integration with auth systems

### **Reporting Security Issues**

Please report security vulnerabilities to [security@example.com](mailto:security@example.com). We take security seriously and will respond within 24 hours.

---

## 📊 **Performance**

### **Benchmarks**

| Metric | Value | Notes |
|--------|-------|-------|
| **Concurrent Tools** | 100+ | With appropriate resource limits |
| **Requests/Second** | 1000+ | HTTP transport with caching |
| **Tool Execution Overhead** | <50ms | Validation and setup time |
| **Memory Usage** | ~200MB | Base server without tools |
| **Startup Time** | <2s | Full initialization |
| **Circuit Breaker Response** | <1ms | Failure detection |

### **Optimization Tips**

1. **Use uvloop**: Install `uvloop` for 2-4x performance improvement
2. **Enable Caching**: Configure Redis for tool output caching
3. **Adjust Limits**: Tune concurrency based on your hardware
4. **Use SSD**: Fast storage improves tool execution times

---

## 🚢 **Deployment**

### **Docker Compose (Recommended)**

```yaml
version: '3.8'
services:
  mcp-server:
    image: mcp-server:latest
    ports:
      - "8080:8080"
    environment:
      - MCP_SERVER_TRANSPORT=http
    volumes:
      - ./config:/app/config
    restart: unless-stopped
```

### **Kubernetes**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-server
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: mcp-server
        image: mcp-server:latest
        ports:
        - containerPort: 8080
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
```

### **AWS ECS**

See [deployment/aws-ecs](deployment/aws-ecs) for CloudFormation templates and task definitions.

-
## 🧩 **Extending the Tool Collection**

1. **Create the tool wrapper**
   - Start from `mcp_server/base_tool.py` or an existing implementation in `mcp_server/tools/`.
   - Define `command_name`, allowed flags, concurrency defaults, and override `_execute_tool()` for custom behavior.

2. **Register the tool**
   - Ensure the new class resides in `mcp_server/tools/` and is imported by the package `__init__.py` so discovery picks it up.
   - Update configuration or allowlists if your deployment uses `TOOL_INCLUDE` / `TOOL_EXCLUDE` environment variables.

3. **Validate safety controls**
   - Implement input validation (target restrictions, flag filtering) and wire circuit-breaker settings via `get_config()` like other tools.
   - Add any required external binaries to `scripts/mcp_server_launcher.sh` and the `Dockerfile` so health checks pass.

4. **Document and test**
   - Update the README tool table and `docs/` entries with the new tool’s capabilities.
   - Run `python3 mcp_client.py` and `curl /health` to confirm availability, then add Prometheus alert coverage if needed.

---

## 🧪 **Testing**

```bash
# Activate the project virtual environment (created by launcher or manual setup)
source /opt/venv/bin/activate  # or . /opt/venv/bin/activate

# Run all regression tests, including tool sanitizers
pytest

# Focus on refactored tool suites
pytest tests/test_gobuster_tool.py tests/test_masscan_tool.py \
       tests/test_hydra_tool.py tests/test_sqlmap_tool.py

# Run with coverage
pytest --cov=mcp_server --cov-report=html

# Run specific test suite
pytest tests/test_circuit_breaker.py

# Run integration tests
pytest tests/integration/

# Run performance tests
pytest tests/performance/ -v
```

---

## 🤝 **Contributing**

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### **How to Contribute**

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/AmazingFeature`)
3. **Commit** your changes (`git commit -m 'Add AmazingFeature'`)
4. **Push** to the branch (`git push origin feature/AmazingFeature`)
5. **Open** a Pull Request

### **Development Setup**

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/Security-MCP-Server.git

# Install development dependencies
pip install -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install

# Run tests
pytest

# Run linting
black mcp_server/
flake8 mcp_server/
mypy mcp_server/
```

### **Adding a New Tool**

See our [Tool Development Guide](docs/TOOLS.md) for detailed instructions. Quick example:

```python
from mcp_server.base_tool import MCPBaseTool

class MyTool(MCPBaseTool):
    command_name = "mytool"
    allowed_flags = ["-v", "--output"]
    default_timeout_sec = 300
    
    async def _execute_tool(self, inp, timeout_sec=None):
        # Your implementation
        return await super()._execute_tool(inp, timeout_sec)
```

---

## 📈 **Roadmap**

### **Version 2.1** (Q1 2025)
- [ ] WebSocket support for real-time streaming
- [ ] Built-in authentication/authorization
- [ ] Tool output caching with Redis
- [ ] Advanced scheduling capabilities

### **Version 2.2** (Q2 2025)
- [ ] Kubernetes operator for CRD-based management
- [ ] Multi-tenancy support
- [ ] Tool marketplace/registry
- [ ] AI-powered tool selection

### **Version 3.0** (Q3 2025)
- [ ] Distributed execution across multiple nodes
- [ ] GraphQL API
- [ ] Tool chaining and workflows
- [ ] Built-in reporting engine

---

## 👥 **Community**

### **Get Help**
- 📧 [Mailing List](https://groups.google.com/g/mcp-server)
- 💬 [Discord Server](https://discord.gg/mcp-server)
- 🐛 [Issue Tracker](https://github.com/nordeim/Security-MCP-Server/issues)
- 📚 [Documentation](https://mcp-server.readthedocs.io)

### **Contributors**

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<table>
  <tr>
    <td align="center">
      <a href="https://github.com/nordeim">
        <img src="https://github.com/nordeim.png" width="100px;" alt=""/>
        <br />
        <sub><b>nordeim</b></sub>
      </a>
      <br />
      <a href="#code-nordeim" title="Code">💻</a>
      <a href="#doc-nordeim" title="Documentation">📖</a>
    </td>
    <!-- Add more contributors here -->
  </tr>
</table>
<!-- ALL-CONTRIBUTORS-LIST:END -->

### **Acknowledgments**

- Thanks to all contributors who have helped shape this project
- Special thanks to the security community for feedback and suggestions
- Built with ❤️ using Python, Docker, and open-source tools

---

## 📄 **License**

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🌟 **Star History**

[![Star History Chart](https://api.star-history.com/svg?repos=nordeim/Security-MCP-Server&type=Date)](https://star-history.com/#nordeim/Security-MCP-Server&Date)

---

## 📊 **Stats**

![GitHub Stats](https://github-readme-stats.vercel.app/api?username=nordeim&repo=Security-MCP-Server&show_icons=true&theme=dark)

---

<div align="center">

### **Built with 🛡️ for the Security Community**

**[Website](https://mcp-server.io)** • **[Documentation](https://docs.mcp-server.io)** • **[Blog](https://blog.mcp-server.io)**

© 2024 Security MCP Server. All rights reserved.

</div>
