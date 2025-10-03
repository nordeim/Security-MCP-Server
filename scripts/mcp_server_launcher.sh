#!/usr/bin/env bash
set -euo pipefail

# MCP server launcher script
# - Installs required OS packages (APT)
# - Installs required Python packages (pip)
# - Sets environment variables
# - Starts the MCP server in the configured transport (default: HTTP)

OS_PACKAGES=(
  "python3"
  "python3-venv"
  "python3-pip"
  "curl"
  "git"
  "gobuster"
  "hydra"
  "masscan"
  "nmap"
  "sqlmap"
)

PYTHON_PACKAGES=(
  "model-context-protocol"
  "fastapi"
  "uvicorn"
  "sse-starlette"
  "prometheus-client"
  "requests"
)

VENV_PATH="/opt/venv"
TRANSPORT_DEFAULT="http"
SERVER_HOST_DEFAULT="0.0.0.0"
SERVER_PORT_DEFAULT="8080"

print_header() {
  echo "========================================"
  echo "$1"
  echo "========================================"
}

check_command() {
  command -v "$1" >/dev/null 2>&1
}

require_root() {
  if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] This script must be run as root (or via sudo)."
    exit 1
  fi
}

install_os_packages() {
  print_header "Checking OS packages"
  need_update=false
  missing_pkgs=()
  for pkg in "${OS_PACKAGES[@]}"; do
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then
      missing_pkgs+=("$pkg")
    fi
  done

  if [ "${#missing_pkgs[@]}" -gt 0 ]; then
    echo "[INFO] Installing missing packages: ${missing_pkgs[*]}"
    apt-get update
    apt-get install -y "${missing_pkgs[@]}"
  else
    echo "[OK] All required OS packages are already installed."
  fi
}

create_or_activate_venv() {
  print_header "Preparing Python environment"
  if [ ! -d "$VENV_PATH" ]; then
    echo "[INFO] Creating virtual environment at $VENV_PATH"
    python3 -m venv "$VENV_PATH"
  fi
  source "$VENV_PATH/bin/activate"
  echo "[OK] Virtual environment active: $(which python3)"
}

install_python_packages() {
  print_header "Checking Python packages"
  python -m pip install --upgrade pip
  python -m pip install --upgrade "${PYTHON_PACKAGES[@]}"
}

configure_environment() {
  print_header "Configuring environment variables"
  export MCP_SERVER_TRANSPORT="${MCP_SERVER_TRANSPORT:-$TRANSPORT_DEFAULT}"
  export MCP_SERVER_HOST="${MCP_SERVER_HOST:-$SERVER_HOST_DEFAULT}"
  export MCP_SERVER_PORT="${MCP_SERVER_PORT:-$SERVER_PORT_DEFAULT}"
  export PATH="/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

  echo "[INFO] MCP_SERVER_TRANSPORT=$MCP_SERVER_TRANSPORT"
  echo "[INFO] MCP_SERVER_HOST=$MCP_SERVER_HOST"
  echo "[INFO] MCP_SERVER_PORT=$MCP_SERVER_PORT"
}

start_server() {
  print_header "Starting MCP server"
  exec python -m mcp_server.server
}

main() {
  require_root
  install_os_packages
  create_or_activate_venv
  install_python_packages
  configure_environment
  start_server
}

main "$@"
