# File: nmap_tool.py
"""
Enhanced Nmap tool with circuit breaker, metrics, and advanced features.
"""
import logging
from typing import Sequence

from mcp_server.base_tool import MCPBaseTool, ToolInput, ToolOutput, ToolErrorType, ErrorContext
from mcp_server.config import get_config

log = logging.getLogger(__name__)

class NmapTool(MCPBaseTool):
    """
    Enhanced Nmap network scanner tool with advanced features.
    
    Executes `nmap` against validated RFC1918 or .lab.internal targets.
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
    
    # Conservative, safe flags for nmap
    allowed_flags: Sequence[str] = [
        "-sV",        # Service version detection
        "-sC",        # Default script scan
        "-A",         # Aggressive options (enables -sV, -sC, -O, --traceroute)
        "-p",         # Port specification
        "--top-ports", # Scan top N ports
        "-T", "-T4",  # Timing template (T4 = aggressive)
        "-Pn",        # Treat all hosts as online (skip host discovery)
        "-O",         # OS detection
        "--script",   # Script scanning (safe scripts only)
        "-oX",        # XML output (for parsing)
        "-oN",        # Normal output
        "-oG",        # Grepable output
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
        if self.config.circuit_breaker_enabled:
            self.circuit_breaker_failure_threshold = self.config.circuit_breaker_failure_threshold
            self.circuit_breaker_recovery_timeout = self.config.circuit_breaker_recovery_timeout
        
        # Reinitialize circuit breaker with new settings
        self._circuit_breaker = None
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
            correlation_id=inp.correlation_id
        )
        
        # Execute with enhanced monitoring
        return await super()._execute_tool(enhanced_input, timeout_sec)
    
    def _validate_nmap_requirements(self, inp: ToolInput) -> Optional[ToolOutput]:
        """Validate nmap-specific requirements."""
        # Check if target is a network range (might need special handling)
        if "/" in inp.target:
            try:
                # Validate CIDR notation
                import ipaddress
                network = ipaddress.ip_network(inp.target, strict=False)
                if network.num_addresses > 1024:
                    error_context = ErrorContext(
                        error_type=ToolErrorType.VALIDATION_ERROR,
                        message=f"Network range too large: {network.num_addresses} addresses",
                        recovery_suggestion="Use smaller network ranges or specify individual hosts",
                        timestamp=self._get_timestamp(),
                        tool_name=self.tool_name,
                        target=inp.target,
                        metadata={"network_size": network.num_addresses}
                    )
                    return self._create_error_output(error_context, inp.correlation_id)
            except ValueError:
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Invalid network range: {inp.target}",
                    recovery_suggestion="Use valid CIDR notation (e.g., 192.168.1.0/24)",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=inp.target
                )
                return self._create_error_output(error_context, inp.correlation_id)
        
        return None
    
    def _optimize_nmap_args(self, extra_args: str) -> str:
        """Optimize nmap arguments for performance and safety."""
        if not extra_args:
            return ""
        
        args = extra_args.split()
        optimized = []
        
        # Add performance optimizations if not specified
        has_timing = any(arg.startswith("-T") for arg in args)
        has_parallelism = any(arg.startswith("--max-parallelism") for arg in args)
        has_host_discovery = any(arg in ("-Pn", "-sn") for arg in args)
        
        if not has_timing:
            optimized.append("-T4")  # Aggressive timing
        
        if not has_parallelism:
            optimized.append("--max-parallelism=10")  # Limit parallelism
        
        if not has_host_discovery:
            optimized.append("-Pn")  # Skip host discovery for internal networks
        
        # Add existing args
        optimized.extend(args)
        
        return " ".join(optimized)
    
    def _get_timestamp(self):
        """Get current timestamp."""
        from datetime import datetime
        return datetime.now()
    
    async def get_tool_info(self) -> dict:
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
                "recovery_timeout": self.circuit_breaker_recovery_timeout
            },
            "optimizations": [
                "Aggressive timing (-T4)",
                "Limited parallelism",
                "Host discovery skip (-Pn)"
            ]
        }
        
        # Add metrics if available
        if self.metrics:
            base_info["metrics"] = {
                "prometheus_available": True,
                "execution_metrics": f"mcp_tool_execution_total{{tool=\"{self.tool_name}\"}}"
            }
        
        return base_info
