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

The Enhanced MCP (Model Context Protocol) Server is a **security-focused, production-ready platform** that integrates powerful security tools with Large Language Models (LLMs) like ChatGPT. It provides safe, controlled access to security assessment capabilities while maintaining strict security boundaries.

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

1. **MCP Server Running**: Ensure the MCP server is deployed and accessible
2. **LLM Access**: Access to an LLM that supports MCP (like ChatGPT with MCP plugin)
3. **Network Access**: Access to target RFC1918 networks or .lab.internal domains
4. **Proper Authorization**: Legal authorization to test target systems

### Basic Setup

```bash
# Start MCP server
python -m mcp_server.server

# Configure LLM to use MCP server
# (Follow your LLM's MCP setup instructions)
```

### First Interaction Test

**Prompt for LLM:**
```
"Hello! I have access to security assessment tools through MCP. Can you help me understand what tools are available and how to use them safely?"
```

---

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

---

## Usage Scenarios with Prompts

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

#### Scenario 2.2: Service-Specific Scanning
**Description**: Scan for specific services across multiple hosts to identify particular service types.

**Sample Prompts:**

**Prompt A (Web service discovery):**
```
"Please scan the network 192.168.1.0/24 specifically for web services. Use Nmap to:
- Scan ports 80, 443, 8080, 8443, 8000, 8888
- Detect HTTP/HTTPS services
- Identify web server versions
- Detect common web technologies
Provide a report of all discovered web services."
```

**Prompt B (Database service discovery):**
```
"Search for database services across 192.168.1.0/24. Use Nmap to scan for:
- MySQL (3306)
- PostgreSQL (5432)
- MSSQL (1433)
- Oracle (1521)
- MongoDB (27017)
For each database found, provide version information and security considerations."
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

#### Scenario 3.2: DNS Infrastructure Enumeration
**Description**: Enumerate DNS infrastructure and discover subdomains using Gobuster's DNS capabilities.

**Sample Prompts:**

**Prompt A (Subdomain enumeration):**
```
"Please perform DNS enumeration for the domain lab.internal. Use Gobuster to:
- Discover subdomains using a common wordlist
- Identify DNS records (A, CNAME, etc.)
- Look for potentially sensitive subdomains (admin, dev, test, staging)
- Provide a list of discovered subdomains with their IP addresses"
```

**Prompt B (DNS zone transfer testing):**
```
"Test the DNS server at 192.168.1.5 for zone transfer vulnerabilities. Use Gobuster to:
- Attempt DNS zone transfers
- Enumerate subdomains
- Identify any DNS misconfigurations
- Provide security assessment of DNS infrastructure"
```

### Web Application Testing

#### Scenario 4.1: Comprehensive Web Application Discovery
**Description**: Perform thorough web application reconnaissance combining multiple tools.

**Sample Prompts:**

**Prompt A (Full web app recon):**
```
"Please conduct comprehensive web application reconnaissance for http://192.168.1.10. Use the following approach:
1. First, use Nmap to identify web technologies and services
2. Then use Gobuster to discover directories and files
3. Look for common web technologies (WordPress, Joomla, Drupal, etc.)
4. Identify potential admin panels and login pages
5. Provide a security assessment of discovered web applications"
```

**Prompt B (Technology stack identification):**
```
"Identify the complete technology stack for the web application at http://192.168.1.20. Please:
- Use Nmap to detect web server and version
- Use Gobuster to find common files and directories
- Analyze discovered content to identify:
  - Web frameworks
  - Programming languages
  - Database technologies
  - JavaScript libraries
  - Potential vulnerabilities based on technology stack"
```

#### Scenario 4.2: Web Service Security Assessment
**Description**: Assess the security posture of discovered web services.

**Sample Prompts:**

**Prompt A (Web service security scan):**
```
"Assess the security of the web services discovered on 192.168.1.0/24. Please:
1. Use Nmap to identify all web services and their versions
2. Use Gobuster to enumerate each web service
3. Identify potential security issues based on:
   - Outdated software versions
   - Default configurations
   - Exposed admin panels
   - Sensitive file disclosures
4. Provide prioritized security recommendations"
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

#### Scenario 5.2: Database Enumeration
**Description**: Perform safe database enumeration to identify database structure and potential security issues.

**Sample Prompts:**

**Prompt A (Database structure discovery):**
```
"If SQL injection is discovered on http://192.168.1.10/app.php?id=1, please use Sqlmap to:
- Safely identify the database type and version
- Enumerate database names
- Identify table structures (without dumping sensitive data)
- Look for potentially sensitive table names
- Provide security assessment of database configuration"
```

**Prompt B (Advanced SQL injection assessment):**
```
"Conduct a comprehensive SQL injection assessment of the application at http://192.168.1.15/admin/login. Use Sqlmap with:
- Risk level 2 (moderate testing)
- Test level 2 (moderate depth)
- Focus on authentication bypass possibilities
- Test for time-based and boolean-based SQL injection
- Provide detailed vulnerability analysis with remediation recommendations"
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

#### Scenario 6.2: Web Application Password Security
**Description**: Test web application login forms for weak credentials using Hydra.

**Sample Prompts:**

**Prompt A (Web form password test):**
```
"Test the login form at http://192.168.1.10/admin/login for weak credentials. Use Hydra to:
- Test common admin usernames
- Use a safe password list
- Target the form's username and password parameters
- Use conservative thread limits (4 threads)
- Identify any authentication bypass vulnerabilities"
```

**Prompt B (Multiple service password audit):**
```
"Perform a password security audit of multiple services on 192.168.1.15. Please:
1. Identify all services that require authentication (SSH, FTP, web forms)
2. For each service, use Hydra to test:
   - Default/weak credentials
   - Service-specific usernames
   - Common password patterns
3. Provide comprehensive password security assessment"
```

### Comprehensive Assessment Workflows

#### Scenario 7.1: Full Network Security Assessment
**Description**: Execute a complete network security assessment workflow combining all tools.

**Sample Prompts:**

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

#### Scenario 7.2: Penetration Testing Workflow
**Description**: Execute a penetration testing workflow with ethical considerations.

**Sample Prompts:**

**Prompt A (Ethical penetration test):**
```
"Please perform an ethical penetration test of the network 192.168.1.0/24. Follow this methodology:
1. Reconnaissance:
   - Use Masscan for network mapping
   - Use Nmap for service discovery
2. Scanning and Enumeration:
   - Use Gobuster for web content discovery
   - Identify all potential attack surfaces
3. Vulnerability Assessment:
   - Use Sqlmap for SQL injection testing (conservative settings)
   - Use Hydra for password security testing (safe wordlist only)
4. Reporting:
   - Document all findings
   - Provide risk assessment
   - Suggest remediation strategies
Remember to maintain ethical standards and avoid causing system disruption."
```

**Prompt B (Red team simulation):**
```
"Simulate a red team assessment of the 192.168.1.0/24 network. Please:
1. Initial Access Simulation:
   - Use Masscan and Nmap to identify targets
   - Use Gobuster to find potential entry points
2. Post-Exploitation Simulation:
   - Use Sqlmap to test for data access vulnerabilities
   - Use Hydra to test credential security
3. Lateral Movement Simulation:
   - Identify potential pivot points
   - Assess network segmentation
4. Exfiltration Simulation:
   - Identify potential data exfiltration paths
Provide a comprehensive red team assessment report with defensive recommendations."
```

---

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

---

## Security Considerations

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
- **Target Validation**: Tools only accept RFC1918 and .lab.internal targets
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

---

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

---

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
