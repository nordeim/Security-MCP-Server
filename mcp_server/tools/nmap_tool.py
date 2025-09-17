# File: mcp_server/tools/nmap_tool.py
"""
Enhanced Nmap tool with circuit breaker, metrics, and advanced features.
"""
import logging
import shlex
import ipaddress
from datetime import datetime, timezone
from typing import Sequence, Optional

from mcp_server.base_tool import MCPBaseTool, ToolInput, ToolOutput, ToolErrorType, ErrorContext
from mcp_server.config import get_config

log = logging.getLogger(__name__)

class NmapTool(MCPBaseTool):
    """
    Enhanced Nmap network scanner tool with advanced features.

    Executes `nmap` against validated RFC1918, loopback, or .lab.internal targets.
    Only a curated set of flags are permitted for safety and predictability.

    Features:
    - Circuit breaker protection
    - Comprehensive metrics collection
    - Advanced error handling
    - Performance monitoring
    - Resource safety

    Environment overrides:
    - MCP_DEFAULT_TIMEOUT_SEC (default 600s here)
    - MCP_DEFAULT_CONCURRENCY (default 1 here)
    - MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD (default 5)
    - MCP_CIRCUIT_BREAKER_RECOVERY_TIMEOUT (default 60s)
    """

    command_name: str = "nmap"

    # Conservative, safe flags for nmap (prefix/option names only; values allowed after '=' or space)
    allowed_flags: Sequence[str] = [
        "-sV",         # Service version detection
        "-sC",         # Default script scan
        "-A",          # Aggressive options (enables -sV, -sC, -O, --traceroute)
        "-p",          # Port specification
        "--top-ports", # Scan top N ports
        "-T", "-T4",   # Timing template (T4 = aggressive)
        "-Pn",         # Treat all hosts as online (skip host discovery)
        "-O",          # OS detection
        "--script",    # Script scanning (safe scripts only)
        "-oX",         # XML output (for parsing)
        "-oN",         # Normal output
        "-oG",         # Grepable output
        "--max-parallelism",  # Explicitly allow injected parallelism control
    ]

    # Nmap can run long; set higher timeout
    default_timeout_sec: float = 600.0

    # Limit concurrency to avoid overloading host and network
    concurrency: int = 1

    # Circuit breaker configuration
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: float = 120.0  # 2 minutes for nmap
    circuit_breaker_expected_exception: tuple = (Exception,)

    def __init__(self):
        super().__init__()
        self.config = get_config()
        self._setup_enhanced_features()

    def _setup_enhanced_features(self):
        """Setup enhanced features for Nmap tool."""
        # Override circuit breaker settings from config if available
        if getattr(self.config, "circuit_breaker_enabled", False):
            self.circuit_breaker_failure_threshold = getattr(
                self.config, "circuit_breaker_failure_threshold", self.circuit_breaker_failure_threshold
            )
            self.circuit_breaker_recovery_timeout = getattr(
                self.config, "circuit_breaker_recovery_timeout", self.circuit_breaker_recovery_timeout
            )

        # Reinitialize circuit breaker with new settings (class-level, not instance)
        type(self)._circuit_breaker = None
        self._initialize_circuit_breaker()

    async def _execute_tool(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
        """Enhanced tool execution with nmap-specific features."""
        # Validate nmap-specific requirements
        validation_result = self._validate_nmap_requirements(inp)
        if validation_result:
            return validation_result

        # Add nmap-specific optimizations
        optimized_args = self._optimize_nmap_args(inp.extra_args)

        # Create enhanced input with optimizations
        enhanced_input = ToolInput(
            target=inp.target,
            extra_args=optimized_args,
            timeout_sec=timeout_sec or self.default_timeout_sec,
            correlation_id=inp.correlation_id,
        )

        # Execute with enhanced monitoring
        return await super()._execute_tool(enhanced_input, timeout_sec)

    def _validate_nmap_requirements(self, inp: ToolInput) -> Optional[ToolOutput]:
        """Validate nmap-specific requirements."""
        target = inp.target.strip()

        # CIDR/network targets
        if "/" in target:
            try:
                network = ipaddress.ip_network(target, strict=False)
            except ValueError:
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Invalid network range: {target}",
                    recovery_suggestion="Use valid CIDR notation (e.g., 192.168.1.0/24)",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                )
                return self._create_error_output(error_context, inp.correlation_id)

            # Enforce reasonable scan size
            if network.num_addresses > 1024:
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Network range too large: {network.num_addresses} addresses",
                    recovery_suggestion="Use smaller network ranges or specify individual hosts",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                    metadata={"network_size": network.num_addresses},
                )
                return self._create_error_output(error_context, inp.correlation_id)

            # Enforce RFC1918/loopback for networks
            if not (network.is_private or network.is_loopback):
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Network not permitted: {target}",
                    recovery_suggestion="Use RFC1918 or loopback ranges only (e.g., 10.0.0.0/8, 192.168.0.0/16)",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                )
                return self._create_error_output(error_context, inp.correlation_id)

            return None

        # Single-host targets
        # If it's an IP, enforce private/loopback; if it's a hostname, require .lab.internal
        try:
            ip = ipaddress.ip_address(target)
            if not (ip.is_private or ip.is_loopback):
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"IP not permitted: {target}",
                    recovery_suggestion="Use RFC1918 or loopback IPs only",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                )
                return self._create_error_output(error_context, inp.correlation_id)
        except ValueError:
            # Not an IP -> treat as hostname
            if not target.endswith(".lab.internal"):
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Hostname not permitted: {target}",
                    recovery_suggestion="Use hostnames ending in .lab.internal",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                )
                return self._create_error_output(error_context, inp.correlation_id)

        return None

    def _optimize_nmap_args(self, extra_args: str) -> str:
        """Optimize nmap arguments for performance and safety."""
        if not extra_args:
            # Provide safe, minimal defaults with no args if desired; currently none.
            return ""

        # Robustly parse arguments, supporting quotes
        try:
            args = shlex.split(extra_args)
        except ValueError as e:
            # Fallback: return as-is; the base parser will raise a structured error
            log.warning("nmap.args.parse_failed tool=%s error=%s args=%r", self.tool_name, str(e), extra_args)
            return extra_args

        optimized: list[str] = []

        # Add performance optimizations if not specified
        has_timing = any(a.startswith("-T") for a in args)
        has_parallelism = any(a.startswith("--max-parallelism") for a in args)
        has_host_discovery = any(a in ("-Pn", "-sn") for a in args)

        if not has_timing:
            optimized.append("-T4")  # Aggressive timing (user args later can override)

        # Note: --max-parallelism must be supported by your nmap version.
        # It's allowed in allowed_flags to avoid parse rejection.
        if not has_parallelism:
            optimized.append("--max-parallelism=10")  # Conservative cap

        if not has_host_discovery:
            optimized.append("-Pn")  # Skip host discovery for internal networks

        # Append existing args so user-provided flags can override defaults
        optimized.extend(args)

        return " ".join(optimized)

    def _get_timestamp(self):
        """Get current timestamp (UTC, timezone-aware)."""
        return datetime.now(timezone.utc)

    def get_tool_info(self) -> dict:
        """Get enhanced tool information."""
        base_info = {
            "name": self.tool_name,
            "command": self.command_name,
            "description": self.__doc__,
            "concurrency": self.concurrency,
            "timeout": self.default_timeout_sec,
            "allowed_flags": list(self.allowed_flags) if self.allowed_flags else [],
            "circuit_breaker": {
                "failure_threshold": self.circuit_breaker_failure_threshold,
                "recovery_timeout": self.circuit_breaker_recovery_timeout,
            },
            "optimizations": [
                "Aggressive timing (-T4)",
                "Limited parallelism (--max-parallelism=10)",
                "Host discovery skip (-Pn)",
            ],
        }

        # Add metrics if available
        if hasattr(self, "metrics") and self.metrics:
            base_info["metrics"] = {
                "prometheus_available": True,
                "execution_metrics": f'mcp_tool_execution_total{{tool="{self.tool_name}"}}',
            }

        return base_info
