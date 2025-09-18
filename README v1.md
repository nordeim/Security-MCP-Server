# Security MCP Server

[![Docker](https://img.shields.io/badge/Docker-Ready-blue?style=for-the-badge&logo=docker)](https://www.docker.com/)
[![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-Ready-green?style=for-the-badge&logo=githubactions)](https://github.com/features/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![Claude](https://img.shields.io/badge/Claude-Desktop-purple?style=for-the-badge)](https://claude.ai/)

A production-ready MCP (Model Context Protocol) server that provides security tools integration for Claude Desktop. This server enables Claude to perform security assessments, network scanning, and vulnerability testing through a secure, controlled environment.

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

The Security MCP Server is a robust, production-ready implementation that bridges Claude Desktop with powerful security tools. It provides a secure framework for running security assessments, network scans, and vulnerability tests through a controlled, audited environment.

### Why This Matters

Security testing requires specialized tools and careful control to prevent unintended consequences. This MCP server provides:

- **Safe Execution**: All tools are executed in a controlled environment with strict security constraints
- **Audit Trail**: Complete logging and monitoring of all security operations
- **Rate Limiting**: Prevents network overload and aggressive scanning
- **Access Control**: Restricts operations to authorized targets only (RFC1918 and .lab.internal)
- **Circuit Breakers**: Prevents cascading failures and system overload

### MCP Integration

This server implements the Model Context Protocol (MCP), which allows Claude Desktop to securely interact with external tools and resources. The MCP architecture ensures:

- **Standardized Communication**: Consistent interface between Claude and tools
- **Security Isolation**: Tools run in isolated environments
- **Resource Management**: Controlled access to system resources
- **Extensibility**: Easy to add new tools and capabilities

## Features

### Core Capabilities

- **Multi-Tool Support**: Integrated support for multiple security tools:
  - **Gobuster**: Directory and DNS brute-forcing
  - **Hydra**: Online password cracking
  - **Masscan**: Fast port scanning
  - **SQLMap**: SQL injection detection and exploitation

- **Security Controls**:
  - Target validation (RFC1918 and .lab.internal only)
  - Argument sanitization and validation
  - Rate limiting and concurrency control
  - Circuit breaker pattern for fault tolerance
  - Comprehensive audit logging

- **Observability**:
  - Prometheus metrics integration
  - Structured logging with correlation IDs
  - Performance monitoring
  - Error tracking with recovery suggestions

- **Configuration Management**:
  - Environment variable overrides
  - Hot-reload capability
  - Sensitive data redaction
  - Validation and defaults

### Tool-Specific Features

#### Gobuster Tool
- Mode validation (dir, dns, vhost)
- Automatic target argument injection
- Mode-specific optimizations
- Wordlist safety validation

#### Hydra Tool
- Service-specific validation
- Password list size restrictions
- Thread count limitations
- Comprehensive input sanitization

#### Masscan Tool
- Network range validation
- Rate limiting enforcement
- Large network support
- Performance optimizations

#### SQLMap Tool
- Risk level restrictions (1-2 only)
- Test level restrictions (1-3 only)
- URL validation and authorization
- Batch mode enforcement

## Prerequisites

Before setting up the Security MCP Server, ensure you have the following:

### System Requirements
- **Operating System**: Linux, macOS, or Windows (with WSL2)
- **Memory**: Minimum 4GB RAM, 8GB recommended
- **Storage**: Minimum 2GB free space
- **Network**: Internet connection for downloading dependencies

### Software Dependencies
- **Docker**: Version 20.10 or later
- **Docker Compose**: Version 1.29 or later
- **Claude Desktop**: Latest version with MCP support
- **Git**: For cloning the repository

### Security Tools
The following security tools are included in the Docker image:
- `gobuster` v3.6+
- `hydra` v9.4+
- `masscan` v1.3+
- `sqlmap` v1.7+

### Knowledge Requirements
- Basic understanding of security testing concepts
- Familiarity with Docker and containerization
- Knowledge of network security principles
- Understanding of target systems and networks

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/nordeim/Security-MCP-Server.git
cd Security-MCP-Server
```

### 2. Configure Environment Variables

Create a `.env` file based on the template:

```bash
cp .env.template .env
```

Edit the `.env` file with your configuration:

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

### 3. Start the Server

Using Docker Compose:

```bash
docker-compose up -d
```

This will:
- Build the Docker image with all security tools
- Start the MCP server
- Configure metrics collection
- Set up logging

### 4. Verify the Server

Check that the server is running:

```bash
docker-compose ps
```

You should see the `security-mcp-server` container running.

### 5. Configure Claude Desktop

Add the MCP server to Claude Desktop:

1. Open Claude Desktop
2. Go to Settings → Developer → MCP Servers
3. Add a new server with the following configuration:

```json
{
  "mcpServers": {
    "security": {
      "command": "docker",
      "args": ["exec", "-i", "security-mcp-server", "python", "-m", "mcp_server.main"],
      "env": {}
    }
  }
}
```

### 6. Test the Integration

Restart Claude Desktop and test with a simple prompt:

```
Can you help me scan my local network for open ports using masscan? I want to scan the 192.168.1.0/24 network for ports 80, 443, and 22.
```

## Usage Examples

### Basic Security Assessment

```
I need to perform a security assessment on my local web server at http://192.168.1.10. Can you:
1. Use gobuster to discover directories and files
2. Use sqlmap to check for SQL injection vulnerabilities
3. Provide a summary of findings
```

### Network Scanning

```
Please scan my local network (192.168.1.0/24) for:
1. Open web servers (ports 80, 443, 8080)
2. SSH servers (port 22)
3. FTP servers (port 21)
Use masscan for the initial scan and then use more targeted tools for any discovered services.
```

### Password Security Testing

```
I need to test the password security on my local SSH server at 192.168.1.10. I have a list of usernames in /path/to/users.txt and passwords in /path/to/passwords.txt. Can you use hydra to test these credentials? Please limit the thread count to 4 and stop when you find a valid credential.
```

### SQL Injection Testing

```
I have a web application at http://192.168.1.10/login.php with a potential SQL injection vulnerability in the username parameter. Can you use sqlmap to test this? Please use risk level 1 and test level 2 to be safe.
```

### Comprehensive Security Audit

```
I need a comprehensive security audit of my local network. Please:
1. Scan the 192.168.1.0/24 network for common services
2. For any web servers found, discover directories and test for SQL injection
3. For any SSH servers found, test for weak credentials using my wordlists
4. Provide a detailed report of all findings
```

### Custom Tool Configuration

```
I need to run a custom gobuster scan with specific parameters:
- Target: http://192.168.1.10/admin
- Wordlist: /usr/share/wordlists/dirbuster/directory-list-2.3-medium.txt
- Threads: 20
- Extensions: php,html,txt
- Status codes: 200,301,302,403
Can you run this scan and provide the results?
```

## CI/CD Integration

### GitHub Actions Workflow

The repository includes a GitHub Actions workflow for automated testing and deployment:

```yaml
name: Security MCP Server CI/CD

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Docker Buildx
      uses: docker/setup-buildx-action@v2
    
    - name: Build Docker image
      run: |
        docker build -t security-mcp-server:test .
    
    - name: Run tests
      run: |
        docker run --rm security-mcp-server:test pytest
    
    - name: Security scan
      run: |
        docker run --rm security-mcp-server:test bandit -r .
    
  deploy:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
    - uses: actions/checkout@v3
    
    - name: Login to DockerHub
      uses: docker/login-action@v2
      with:
        username: ${{ secrets.DOCKERHUB_USERNAME }}
        password: ${{ secrets.DOCKERHUB_TOKEN }}
    
    - name: Build and push
      uses: docker/build-push-action@v4
      with:
        context: .
        push: true
        tags: nordeim/security-mcp-server:latest
```

### Workflow Triggers

The CI/CD pipeline is triggered by:
- **Push to main branch**: Runs tests and deploys to production
- **Push to develop branch**: Runs tests only
- **Pull requests to main**: Runs tests and security scans

### Quality Gates

The workflow includes several quality gates:
- **Unit Tests**: Ensure all tests pass
- **Security Scan**: Check for security vulnerabilities
- **Docker Build**: Verify the Docker image builds correctly
- **Integration Tests**: Verify MCP server functionality

## Workflow Diagram

```mermaid
graph TD
    A[Claude Desktop] -->|MCP Protocol| B[Security MCP Server]
    B --> C[Tool Router]
    C --> D[Gobuster Tool]
    C --> E[Hydra Tool]
    C --> F[Masscan Tool]
    C --> G[SQLMap Tool]
    
    B --> H[Configuration Manager]
    B --> I[Metrics Collector]
    B --> J[Error Handler]
    
    D --> K[Target Validation]
    E --> K
    F --> K
    G --> K
    
    K --> L[Execution Engine]
    L --> M[Subprocess Execution]
    M --> N[Result Processing]
    N --> O[Output Formatting]
    O --> P[Claude Desktop]
    
    H --> Q[Environment Variables]
    H --> R[Configuration Files]
    
    I --> S[Prometheus Metrics]
    I --> T[Structured Logs]
    
    J --> U[Error Context]
    J --> V[Recovery Suggestions]
    
    style A fill:#9b59b6,stroke:#333,stroke-width:2px
    style B fill:#3498db,stroke:#333,stroke-width:2px
    style K fill:#e74c3c,stroke:#333,stroke-width:2px
    style S fill:#2ecc71,stroke:#333,stroke-width:2px
```

## Contributing

We welcome contributions to the Security MCP Server! Please follow these guidelines:

### Development Workflow

1. **Fork the Repository**
   ```bash
   # Fork the repository on GitHub
   git clone https://github.com/your-username/Security-MCP-Server.git
   cd Security-MCP-Server
   ```

2. **Create a Feature Branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Make Changes**
   - Follow the existing code style
   - Add tests for new functionality
   - Update documentation as needed

4. **Test Your Changes**
   ```bash
   # Run tests
   docker-compose run --rm app pytest
   
   # Run linting
   docker-compose run --rm app flake8
   
   # Run security checks
   docker-compose run --rm app bandit -r .
   ```

5. **Commit Your Changes**
   ```bash
   git add .
   git commit -m "feat: add your feature description"
   ```

6. **Push to Your Fork**
   ```bash
   git push origin feature/your-feature-name
   ```

7. **Create a Pull Request**
   - Provide a clear description of changes
   - Link to any relevant issues
   - Ensure all CI checks pass

### Code Standards

- **Python Style**: Follow PEP 8 guidelines
- **Type Hints**: Use type hints for all function signatures
- **Documentation**: Include docstrings for all public methods
- **Testing**: Maintain test coverage above 80%
- **Security**: All new code must pass security scans

### Reporting Issues

When reporting issues, please include:
- **Environment**: OS, Docker version, Python version
- **Steps to Reproduce**: Clear reproduction steps
- **Expected Behavior**: What you expected to happen
- **Actual Behavior**: What actually happened
- **Error Messages**: Full error messages and stack traces

### Feature Requests

For feature requests, please:
- **Search Existing Issues**: Check if your request already exists
- **Provide Context**: Explain the use case and benefits
- **Suggest Implementation**: If possible, suggest how to implement it

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

### License Summary

- **Commercial Use**: Allowed
- **Modification**: Allowed
- **Distribution**: Allowed
- **Private Use**: Allowed
- **Liability**: Provided "as is" without warranty
- **Warranty**: No warranty provided

### Third-Party Licenses

This project includes third-party security tools with their own licenses:
- **Gobuster**: MIT License
- **Hydra**: AGPLv3 License
- **Masscan**: AGPLv3 License
- **SQLMap**: GPLv2 License

Please ensure you comply with all applicable licenses when using this project.

## Acknowledgments

- **Claude Team**: For the MCP protocol and Claude Desktop
- **Security Tool Developers**: For the powerful security tools integrated in this server
- **Contributors**: Everyone who has contributed to this project

## Support

If you need help with the Security MCP Server:

1. **Check the Documentation**: Review this README and other documentation
2. **Search Issues**: Look for similar issues in the GitHub repository
3. **Create an Issue**: If you can't find a solution, create a new issue
4. **Join Discussions**: Participate in GitHub Discussions for community support

For security concerns or vulnerabilities, please follow our [Security Policy](SECURITY.md).
