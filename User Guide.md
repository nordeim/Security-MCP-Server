# Comprehensive User Guide: Enhanced MCP Server for Security Assessment

This User Guide provides thorough operational, security, and usage guidance for the Security MCP Server. It is intended for authorized security teams, developers, and system operators.

> Strong warning: This project integrates offensive/security tooling. Do not run scans against systems without explicit written authorization.

## Table of Contents
- [Introduction](#introduction)
- [Getting Started](#getting-started)
- [Tool Overview](#tool-overview)
- [Usage Scenarios with Example Prompts](#usage-scenarios-with-example-prompts)
- [Best Practices](#best-practices)
- [Security Considerations (Legal & Operational)](#security-considerations-legal--operational)
- [Troubleshooting](#troubleshooting)
- [Advanced Usage](#advanced-usage)
- [Appendix: Quick CLI / Docker commands and validation](#appendix-quick-cli--docker-commands-and-validation)

## Introduction

### What is the Enhanced MCP Server?

The Enhanced MCP (Model Context Protocol) Server is a **security-focused, production-ready platform** that integrates powerful security tools with Large Language Models (LLMs) like Claude Desktop. It provides safe, controlled access to security assessment capabilities while maintaining strict security boundaries.

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

## Getting Started

### Prerequisites

- **MCP Server Running**: Ensure the MCP server is deployed and accessible
- **LLM Access**: Access to an LLM that supports MCP (like Claude Desktop with MCP support)
- **Network Access**: Access to target RFC1918 networks or .lab.internal domains
- **Proper Authorization**: Legal authorization to test target systems

### Start locally (development)

1. **Clone the repository**
   ```bash
   git clone https://github.com/nordeim/Security-MCP-Server.git
   cd Security-MCP-Server
   ```

2. **Configure environment variables**
   ```bash
   cp .env.template .env
   ```

3. **Edit the .env file** with your configuration:
   ```bash
   # Server Configuration
   MCP_SERVER_HOST=0.0.0.0
   MCP_SERVER_PORT=8080
   MCP_SERVER_TRANSPORT=http

   # Security Configuration
   MCP_SECURITY_MAX_ARGS_LENGTH=4096
   MCP_SECURITY_TIMEOUT_SECONDS=600
   MCP_SECURITY_CONCURRENCY_LIMIT=2

   # Metrics Configuration
   MCP_METRICS_ENABLED=true
   MCP_METRICS_PROMETHEUS_ENABLED=true
   MCP_METRICS_PROMETHEUS_PORT=9090

   # Logging Configuration
   MCP_LOGGING_LEVEL=INFO
   MCP_LOGGING_FILE_PATH=/var/log/mcp/server.log
   ```

4. **Start the stack** (first run build can be long because it compiles tools)
   ```bash
   docker-compose up -d --build
   ```

### Run server directly (development non-container)

If you prefer to run Python locally (developer mode):
```bash
python -m mcp_server.server
```
(Use virtualenv that includes dependencies in requirements.txt; note the Docker image is the recommended runtime for consistent behavior.)

### Verify the installation

1. **Check containers**
   ```bash
   docker-compose ps
   ```

2. **Check server health**
   ```bash
   curl -f http://localhost:8080/health
   ```

3. **Check Prometheus targets**
   ```bash
   http://localhost:9090/targets
   ```

4. **Check Grafana** (if enabled)
   ```bash
   http://localhost:3000 (admin/admin or configured password)
   ```

### First Interaction Test

**Prompt for LLM:**
```
"Hello! I have access to security assessment tools through MCP. Can you help me understand what tools are available and how to use them safely?"
```

## Tool Overview

### Available Tools

| Tool | Purpose | Security Level | Typical Use Case |
|------|---------|----------------|------------------|
| **Nmap** | Network scanning and service discovery | Medium | Network inventory, port discovery |
| **Masscan** | High-speed port scanning | Medium | Large network reconnaissance |
| **Gobuster** | Web content discovery | Low-Medium | Directory/file enumeration, DNS discovery |
| **Sqlmap** | SQL injection testing | High | Database vulnerability assessment |
| **Hydra** | Password security testing | High | Credential strength validation |

### Security Restrictions

- **Target Validation**: All tools only accept RFC1918 addresses (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) or .lab.internal domains
- **Rate Limiting**: Built-in concurrency and rate limits prevent system overload
- **Argument Validation**: Strict allowlists for command-line flags prevent unsafe operations
- **Circuit Breakers**: Automatic protection against tool failures and cascading issues

### Tool-Specific Details

#### Nmap
- **Purpose**: Detailed host/service discovery and version detection
- **Security Level**: Medium
- **Typical Use**: Network inventory, port discovery, service enumeration
- **Safety Features**: Built-in rate limiting, argument validation

#### Masscan
- **Purpose**: High-speed port discovery
- **Security Level**: Medium
- **Typical Use**: Large network reconnaissance
- **Safety Features**: Network range validation, rate limiting enforcement

#### Gobuster
- **Purpose**: Content and virtual-host discovery
- **Security Level**: Low-Medium
- **Typical Use**: Directory/file enumeration, DNS discovery
- **Safety Features**: Mode validation, wordlist safety validation

#### Sqlmap
- **Purpose**: Targeted SQL injection testing
- **Security Level**: High
- **Typical Use**: Database vulnerability assessment
- **Safety Features**: Risk level restrictions (1-2 only), test level restrictions (1-3 only)

#### Hydra
- **Purpose**: Password security testing
- **Security Level**: High
- **Typical Use**: Credential strength validation
- **Safety Features**: Service-specific validation, password list size restrictions, thread count limitations

## Usage Scenarios with Example Prompts

### Network Discovery

#### Scenario 1.1: Basic Network Inventory
**Description**: Discover all active hosts on a network segment and identify open services. This is the first step in network security assessment.

**Sample Prompts:**

**Prompt A (Basic):**
```
"Please scan the network 192.168.1.0/24 to discover all active hosts and identify their open ports and services. Use Nmap with service version detection enabled."
```

**Prompt B (Detailed):**
```
"I need to perform a comprehensive network discovery on the 192.168.1.0/24 subnet. Please:
1. Use Nmap to scan all hosts in the network
2. Enable service version detection (-sV)
3. Enable OS detection (-O)
4. Use aggressive timing (-T4)
5. Skip host discovery (-Pn) since we know these are internal hosts
6. Provide a summary of found hosts, services, and potential security implications"
```

**Prompt C (Compliance-focused):**
```
"Conduct a network inventory scan of 192.168.1.0/24 for compliance documentation. Use Nmap to identify:
- All active hosts
- Open ports and associated services
- Service versions
- Operating systems
Format the results in a compliance-ready format with risk categorization."
```

#### Scenario 1.2: Large-Scale Network Reconnaissance
**Description**: Perform rapid scanning of large network segments using Masscan for initial discovery, followed by targeted Nmap scanning.

**Sample Prompts:**

**Prompt A (Two-phase approach):**
```
"Please perform a two-phase network assessment:
1. First, use Masscan to quickly scan the 10.0.0.0/16 network for common ports (80, 443, 22, 3389, etc.)
2. Then, for any hosts found, use Nmap to perform detailed service enumeration on the discovered ports
Provide a consolidated report of findings."
```

**Prompt B (Targeted reconnaissance):**
```
"I need to identify web servers across the 172.16.0.0/12 network. Please:
1. Use Masscan to scan for ports 80, 443, 8080, 8443 across the entire network
2. For each discovered web server, use Nmap to get detailed service information and detect technologies
3. Categorize findings by service type and potential risk level"
```

### Port Scanning

#### Scenario 2.1: Targeted Port Assessment
**Description**: Perform detailed port scanning on specific hosts with comprehensive service detection.

**Sample Prompts:**

**Prompt A (Single host detailed scan):**
```
"Please perform a comprehensive port scan of the host 192.168.1.10 using Nmap. Include:
- All 65535 ports (full port scan)
- Service version detection
- OS detection
- Default script scanning (-sC)
- Aggressive timing options
Provide detailed information about each discovered service."
```

**Prompt B (Security-focused scan):**
```
"Conduct a security-focused port scan of 192.168.1.15. Use Nmap to:
- Scan the top 1000 most common ports
- Detect service versions
- Run safe default scripts
- Identify potential vulnerabilities
Focus on services that commonly have security implications (SMB, RDP, SSH, etc.)"
```

### Service Enumeration

#### Scenario 3.1: Web Service Enumeration
**Description**: Perform detailed enumeration of discovered web services using Gobuster to find directories, files, and virtual hosts.

**Sample Prompts:**

**Prompt A (Directory discovery):**
```
"The host 192.168.1.10 is running a web server on port 80. Please use Gobuster to:
- Discover hidden directories and files
- Use a common wordlist for directory brute-forcing
- Look for common web admin panels (admin, login, wp-admin, etc.)
- Identify any sensitive files or directories
Provide a comprehensive list of discovered paths with security implications."
```

**Prompt B (Virtual host discovery):**
```
"The web server at 192.168.1.10 appears to be hosting multiple domains. Please use Gobuster to:
- Discover virtual hosts using DNS enumeration
- Look for common subdomains (www, mail, ftp, admin, etc.)
- Use the .lab.internal domain for testing
- Identify any additional web applications or services"
```

### SQL Injection Testing

#### Scenario 5.1: Basic SQL Injection Assessment
**Description**: Test web applications for SQL injection vulnerabilities using Sqlmap with safety controls.

**Sample Prompts:**

**Prompt A (Basic SQL injection test):**
```
"Please test the web application at http://192.168.1.10/login.php for SQL injection vulnerabilities. Use Sqlmap with:
- Risk level 1 (conservative testing)
- Test level 1 (basic tests)
- Batch mode for automated operation
- Target the login form's username parameter
Focus on identifying potential SQL injection points without causing damage"
```

**Prompt B (Parameter-specific testing):**
```
"Test the URL parameter 'id' on http://192.168.1.10/page.php?id=1 for SQL injection. Use Sqlmap to:
- Perform safe SQL injection testing
- Use risk level 1 and test level 2
- Identify database type and version
- Test for basic SQL injection vulnerabilities
- Provide detailed findings without extracting sensitive data"
```

### Password Security Testing

#### Scenario 6.1: SSH Password Security Assessment
**Description**: Test SSH service password security using Hydra with safe parameters.

**Sample Prompts:**

**Prompt A (Basic SSH password test):**
```
"Please test the SSH service on 192.168.1.10 for weak passwords. Use Hydra to:
- Test common usernames (admin, root, user, etc.)
- Use a small, safe password list
- Limit to 4 concurrent threads
- Focus on identifying obviously weak credentials
- Do not perform aggressive brute force attacks"
```

**Prompt B (SSH security audit):**
```
"Conduct a security audit of SSH services on 192.168.1.0/24. Please:
1. Use Nmap to identify all SSH services and their versions
2. For each SSH service, use Hydra to test:
   - Common default credentials
   - Weak passwords from a safe wordlist
   - Service-specific usernames (admin, root, etc.)
3. Provide security assessment with recommendations"
```

### Comprehensive Assessment Workflows

#### Scenario 7.1: Full Network Security Assessment
**Description**: Execute a complete network security assessment workflow combining all tools.

**Prompt A (Complete security assessment):**
```
"Please conduct a comprehensive security assessment of the network 192.168.1.0/24. Follow this workflow:
1. Discovery Phase:
   - Use Masscan to quickly identify all active hosts and common services
   - Use Nmap for detailed service enumeration on discovered hosts
2. Enumeration Phase:
   - Use Gobuster to discover web content and directories
   - Identify all web applications and services
3. Vulnerability Assessment Phase:
   - Use Sqlmap to test web applications for SQL injection
   - Use Hydra to test authentication mechanisms
4. Reporting Phase:
   - Consolidate all findings
   - Prioritize by risk level
   - Provide remediation recommendations
Provide a comprehensive security assessment report."
```

**Prompt B (Compliance-focused assessment):**
```
"Conduct a compliance-focused security assessment of 192.168.1.0/24. Please:
1. Use Nmap to create a complete network inventory
2. Use Gobuster to discover all web applications
3. Use Sqlmap to identify potential SQL injection vulnerabilities
4. Use Hydra to test for default/weak credentials
5. Format findings according to compliance frameworks (CIS, NIST, etc.)
6. Provide specific compliance recommendations"
```

## Best Practices

### Prompt Engineering Best Practices

#### 1. **Be Specific and Clear**
```
Good: "Use Nmap to scan 192.168.1.10 with service version detection (-sV) and OS detection (-O)"
Poor: "Scan the network"
```

#### 2. **Include Safety Constraints**
```
Good: "Use Sqlmap with risk level 1 and test level 1 for safe testing"
Poor: "Test for SQL vulnerabilities"
```

#### 3. **Provide Context**
```
Good: "This is for an authorized security assessment of our internal network 192.168.1.0/24"
Poor: "Test this network"
```

#### 4. **Request Specific Output Formats**
```
Good: "Provide findings in a structured format with risk categorization"
Poor: "Tell me what you found"
```

### Security Best Practices

#### 1. **Authorization**
- Always ensure you have proper authorization
- Test only on systems you own or have explicit permission to test
- Respect scope and time limitations

#### 2. **Safety First**
- Use conservative settings for vulnerability testing
- Avoid aggressive attacks that could disrupt services
- Never attempt to extract sensitive data without authorization

#### 3. **Documentation**
- Document all findings thoroughly
- Include timestamps and tool configurations
- Provide clear remediation recommendations

#### 4. **Communication**
- Keep stakeholders informed of progress
- Report critical findings immediately
- Provide regular status updates

## Security Considerations (Legal & Operational)

### Legal and Ethical Guidelines

#### **Authorization Requirements**
- **Written Permission**: Always obtain written authorization before testing
- **Scope Definition**: Clearly define what systems and tests are authorized
- **Time Windows**: Respect specified testing time windows
- **Data Protection**: Never access or extract sensitive data without explicit permission

#### **Responsible Disclosure**
- **Report Vulnerabilities**: Follow responsible disclosure procedures
- **Provide Details**: Include sufficient detail for vulnerability reproduction
- **Allow Remediation Time**: Give organizations time to fix vulnerabilities
- **Public Disclosure**: Never disclose vulnerabilities without permission

### Technical Security Controls

#### **Network Restrictions**
- **Target Validation**: Tools only accept RFC1918 and .lab.internal targets by default (configurable)
- **Rate Limiting**: Built-in controls prevent system overload
- **Argument Validation**: Strict allowlists prevent unsafe operations

#### **Operational Security**
- **Circuit Breakers**: Automatic protection against tool failures
- **Resource Monitoring**: Real-time monitoring of system resources
- **Audit Logging**: Comprehensive logging of all tool executions

### Data Protection

#### **Sensitive Information**
- **Avoid Data Extraction**: Never extract or view sensitive data
- **Anonymize Results**: Remove sensitive information from reports
- **Secure Storage**: Store results securely with proper access controls

#### **Privacy Protection**
- **PII Protection**: Never collect or process personally identifiable information
- **Compliance**: Follow all relevant privacy regulations (GDPR, CCPA, etc.)
- **Minimization**: Collect only the minimum necessary information

## Troubleshooting

### Common Issues and Solutions

#### **1. Tool Execution Failures**

**Symptoms**: Tools return error messages or fail to execute

**Common Causes**:
- Target host unreachable
- Tool not installed on server
- Permission issues
- Network connectivity problems

**Solutions**:
```
"Check if the target host is reachable and the tool is properly installed. Use basic connectivity tests first."
```

#### **2. Timeout Issues**

**Symptoms**: Tools timeout during execution

**Common Causes**:
- Network latency
- Large scan scopes
- Resource constraints

**Solutions**:
```
"Reduce scan scope, increase timeout values, or scan smaller network segments."
```

#### **3. Permission Denied Errors**

**Symptoms**: Tools fail with permission-related errors

**Common Causes**:
- Insufficient user privileges
- File permission issues
- Network access restrictions

**Solutions**:
```
"Check user permissions and ensure the MCP server has necessary privileges to execute security tools."
```

#### **4. Circuit Breaker Activation**

**Symptoms**: Tools refuse to execute due to circuit breaker

**Common Causes**:
- Too many recent failures
- System resource exhaustion
- Network connectivity issues

**Solutions**:
```
"Wait for the circuit breaker timeout period, then retry. Check system resources and network connectivity."
```

### Debugging Prompts

#### **Basic Diagnostics**
```
"Please run basic diagnostics on the MCP server. Check:
1. Tool availability (nmap, masscan, gobuster, sqlmap, hydra)
2. Network connectivity to test targets
3. System resource status
4. Recent error logs
Provide a diagnostic report."
```

#### **Connectivity Testing**
```
"Test network connectivity to the target 192.168.1.10. Please:
1. Use basic ping tests if available
2. Use Nmap for basic connectivity check
3. Verify the target is in an authorized network range
4. Report any connectivity issues"
```

#### **Tool-Specific Diagnostics**
```
"Please diagnose issues with Sqlmap execution. Check:
1. Sqlmap installation and version
2. Target URL accessibility
3. Network connectivity
4. Recent error messages
Provide specific diagnostic information and troubleshooting steps."
```

### Specific Troubleshooting Scenarios

- **Container build failures**: increase resources, inspect builder logs for failed compilation of native tools.
- **Tool not found at runtime**: ensure builder stage completed and binaries were copied into final image.
- **Health endpoint returns degraded**: check psutil availability (optional) and ensure Prometheus (if used) is reachable.

## Advanced Usage

### Complex Multi-Tool Workflows

#### **Automated Security Assessment Pipeline**
```
"Please create an automated security assessment pipeline for 192.168.1.0/24. Execute the following workflow:
1. Discovery Phase:
   - Masscan: Rapid network discovery
   - Nmap: Detailed service enumeration
   - Output: JSON file with discovered assets
2. Vulnerability Assessment Phase:
   - Gobuster: Web content discovery
   - Sqlmap: SQL injection testing (conservative)
   - Hydra: Password security testing (safe wordlist)
   - Output: Vulnerability report
3. Reporting Phase:
   - Consolidate all findings
   - Generate risk assessment
   - Create remediation plan
Execute this pipeline and provide comprehensive results."
```

#### **Continuous Security Monitoring**
```
"Set up continuous security monitoring for the network 192.168.1.0/24. Please:
1. Baseline Assessment:
   - Use Nmap to create network baseline
   - Document all services and configurations
2. Monitoring Configuration:
   - Configure periodic scans (every 6 hours)
   - Monitor for changes in services
   - Alert on new vulnerabilities
3. Reporting:
   - Generate daily summary reports
   - Highlight critical changes
   - Provide trend analysis
Configure this monitoring workflow and provide initial baseline report."
```

### Integration with Security Tools

#### **SIEM Integration**
```
"Please integrate MCP security assessment results with a SIEM system. For the network 192.168.1.0/24:
1. Execute comprehensive security assessment
2. Format findings in SIEM-compatible format
3. Include:
   - Timestamps
   - Severity levels
   - MITRE ATT&CK mappings
   - Asset information
4. Provide integration recommendations and sample data"
```

#### **Ticketing System Integration**
```
"Create security ticket entries based on MCP assessment results. For the network 192.168.1.0/24:
1. Perform security assessment
2. Identify issues requiring attention
3. Create ticket entries with:
   - Priority levels
   - Technical details
   - Remediation steps
   - Assignment suggestions
4. Provide ticket data in common formats (JSON, CSV)"
```

### Custom Security Assessments

#### **Compliance Framework Mapping**
```
"Map security assessment results to compliance frameworks. For 192.168.1.0/24:
1. Execute comprehensive security assessment
2. Map findings to:
   - CIS Controls
   - NIST Cybersecurity Framework
   - ISO 27001
   - GDPR requirements
3. Provide compliance gap analysis
4. Suggest prioritized remediation plan"
```

#### **Risk Assessment Matrix**
```
"Create a detailed risk assessment matrix for 192.168.1.0/24. Please:
1. Execute comprehensive security assessment
2. For each finding, calculate:
   - Likelihood score (1-5)
   - Impact score (1-5)
   - Risk score (Likelihood × Impact)
   - Business impact analysis
3. Create risk matrix visualization
4. Provide risk treatment recommendations"
```

## Appendix: Quick CLI / Docker commands and validation

### Quick verification commands

#### Build and Start
```bash
# Build and start all services
docker-compose up -d --build

# View logs
docker logs -f security-mcp-server

# Check container status
docker-compose ps
```

#### Health Checks
```bash
# Server health check
curl -f http://localhost:8080/health

# Prometheus targets
curl http://localhost:9090/targets

# Grafana dashboard
# Visit: http://localhost:3000 (admin/admin or configured password)
```

#### Common Operations
```bash
# Stop all services
docker-compose down

# Rebuild with no cache
docker-compose build --no-cache

# Execute commands in running container
docker exec -it security-mcp-server bash

# View specific service logs
docker-compose logs -f security-mcp-server
docker-compose logs -f prometheus
docker-compose logs -f grafana
```

#### Configuration Validation
```bash
# Validate environment file
cat .env

# Check docker-compose configuration
docker-compose config

# Test network connectivity between containers
docker exec -it security-mcp-server ping prometheus
docker exec -it security-mcp-server ping grafana
```

#### Tool Validation
```bash
# Check if tools are available in container
docker exec -it security-mcp-server which nmap
docker exec -it security-mcp-server which masscan
docker exec -it security-mcp-server which gobuster
docker exec -it security-mcp-server which sqlmap
docker exec -it security-mcp-server which hydra

# Check tool versions
docker exec -it security-mcp-server nmap --version
docker exec -it security-mcp-server gobuster --version
```

#### Performance Monitoring
```bash
# Monitor resource usage
docker stats

# Check disk usage
docker system df

# Clean up unused resources
docker system prune -f
```

#### Troubleshooting Commands
```bash
# Check container logs for errors
docker-compose logs --tail=100 security-mcp-server

# Inspect container configuration
docker inspect security-mcp-server

# Check network configuration
docker network ls
docker network inspect security-mcp-server_default

# Reset entire stack (warning: removes all data)
docker-compose down -v
```

---

## Conclusion

This comprehensive user guide provides the foundation for effectively using the Enhanced MCP Server with LLMs for security assessments. The key to success is:

1. **Start Simple**: Begin with basic discovery and enumeration
2. **Build Complexity**: Gradually move to more complex assessments
3. **Stay Safe**: Always use conservative settings and respect authorization boundaries
4. **Document Everything**: Maintain thorough records of all assessments
5. **Communicate Clearly**: Provide clear, actionable prompts to the LLM

Remember that this MCP server is designed for **authorized security assessment only**. Always ensure you have proper permission before testing any systems, and use these powerful tools responsibly and ethically.

The combination of advanced security tools and LLM intelligence creates unprecedented opportunities for efficient, effective security assessment. Use this guide to unlock the full potential of your security testing capabilities while maintaining the highest standards of security and ethics.

https://chat.z.ai/s/9ea34a8e-b8c8-41a9-a51d-0cf42f0611a9
