# Stage 1: Builder stage
FROM python:3.12-slim-trixie as builder

# Set metadata
LABEL maintainer="nordeim"
LABEL description="Security MCP Server - Builder Stage"
LABEL version="1.0.0"

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    gcc \
    g++ \
    git \
    libcurl4-openssl-dev \
    libffi-dev \
    libgcrypt20-dev \
    libgmp-dev \
    libgnutls28-dev \
    libidn11-dev \
    libldap2-dev \
    libmysqlclient-dev \
    libncursesw5-dev \
    libpcre3-dev \
    libpq-dev \
    libreadline-dev \
    libssl-dev \
    libsvn-dev \
    libxml2-dev \
    libxslt1-dev \
    libz-dev \
    make \
    pkg-config \
    wget \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Go for gobuster
RUN wget -q https://go.dev/dl/go1.21.5.linux-amd64.tar.gz -O /tmp/go.tar.gz && \
    tar -C /usr/local -xzf /tmp/go.tar.gz && \
    rm /tmp/go.tar.gz

# Set Go environment variables
ENV PATH="/usr/local/go/bin:${PATH}"
ENV GOPATH="/go"
ENV GO111MODULE="on"

# Install gobuster
RUN go install github.com/OJ/gobuster/v3@latest

# Download and install masscan
RUN wget -q https://github.com/robertdavidgraham/masscan/archive/1.3.2.tar.gz -O /tmp/masscan.tar.gz && \
    tar -xzf /tmp/masscan.tar.gz -C /tmp && \
    cd /tmp/masscan-1.3.2 && \
    make && \
    make install && \
    rm -rf /tmp/masscan*

# Download and install hydra
RUN wget -q https://github.com/vanhauser-thc/thc-hydra/archive/v9.4.tar.gz -O /tmp/hydra.tar.gz && \
    tar -xzf /tmp/hydra.tar.gz -C /tmp && \
    cd /tmp/thc-hydra-9.4 && \
    ./configure && \
    make && \
    make install && \
    rm -rf /tmp/hydra*

# Install Python dependencies
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Stage 2: Runtime stage
FROM python:3.12-slim-trixie

# Set metadata
LABEL maintainer="nordeim"
LABEL description="Security MCP Server"
LABEL version="1.0.0"

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/opt/security-tools/bin:${PATH}"

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    ca-certificates \
    libcurl4-openssl-dev \
    libgcrypt20-dev \
    libgmp-dev \
    libgnutls28-dev \
    libidn11-dev \
    libldap2-dev \
    libmysqlclient-dev \
    libncursesw5-dev \
    libpcre3-dev \
    libpq-dev \
    libreadline-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    libz-dev \
    && rm -rf /var/lib/apt/lists/*

# Create security tools directory
RUN mkdir -p /opt/security-tools/bin

# Copy compiled security tools from builder stage
COPY --from=builder /usr/local/bin/gobuster /opt/security-tools/bin/
COPY --from=builder /usr/local/bin/masscan /opt/security-tools/bin/
COPY --from=builder /usr/local/bin/hydra /opt/security-tools/bin/

# Install sqlmap (Python-based tool)
RUN git clone --depth 1 https://github.com/sqlmapproject/sqlmap.git /opt/security-tools/sqlmap && \
    ln -s /opt/security-tools/sqlmap/sqlmap.py /opt/security-tools/bin/sqlmap && \
    chmod +x /opt/security-tools/bin/sqlmap

# Create non-root user
RUN groupadd -r security && \
    useradd -r -g security -d /opt/security-tools -s /bin/bash security

# Create application directory
RUN mkdir -p /opt/mcp-server && \
    chown -R security:security /opt/mcp-server

# Set working directory
WORKDIR /opt/mcp-server

# Copy application code
COPY --chown=security:security . .

# Install Python dependencies
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Create directories for logs and data
RUN mkdir -p /var/log/mcp-server /var/lib/mcp-server && \
    chown -R security:security /var/log/mcp-server /var/lib/mcp-server

# Copy entrypoint script
COPY docker/entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh

# Switch to non-root user
USER security

# Expose ports
EXPOSE 8080 9090

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health')" || exit 1

# Set entrypoint
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Default command
CMD ["python", "-m", "mcp_server.main"]
