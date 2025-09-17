# File: masscan_tool.py
"""
Enhanced Masscan tool with ALL original functionality preserved + comprehensive enhancements.
"""
import logging
from typing import Sequence

# ORIGINAL IMPORT - PRESERVED EXACTLY
from mcp_server.base_tool import MCPBaseTool, ToolInput, ToolOutput, ToolErrorType, ErrorContext

# ENHANCED IMPORT (ADDITIONAL)
from mcp_server.config import get_config

log = logging.getLogger(__name__)

class MasscanTool(MCPBaseTool):
    """
    Enhanced Masscan fast port scanner with ALL original functionality preserved.
    
    ORIGINAL DOCSTRING PRESERVED:
    Usage pattern (positional target at the end, handled by base class):
    masscan -p80,443 --rate 1000 10.0.0.0/24
    Safety considerations:
    - Targets are restricted to RFC1918 or *.lab.internal by the base ToolInput validator.
    - Only a conservative subset of flags is allowed to reduce risk of misuse.
    - Concurrency is limited to 1 due to high network and CPU usage.
    Environment overrides:
    - MCP_DEFAULT_TIMEOUT_SEC (default overridden to 300s)
    - MCP_DEFAULT_CONCURRENCY (default overridden to 1)
    
    ENHANCED FEATURES:
    - Circuit breaker protection
    - Network safety validation
    - Rate limiting enforcement
    - Performance monitoring
    """
    
    # ORIGINAL CLASS VARIABLES - PRESERVED EXACTLY
    command_name: str = "masscan"
    allowed_flags: Sequence[str] = [
        "-p", "--ports",           # Port specification
        "--rate",                  # Rate limiting
        "-e",                      # Interface specification
        "--wait",                  # Wait between packets
        "--banners",               # Banner grabbing
        "--router-ip",             # Router IP specification
        "--router-mac",            # Router MAC specification
        "--source-ip",             # Source IP specification
        "--source-port",           # Source port specification
        "--exclude",                # Exclude targets
        "--excludefile",           # Exclude targets from file
        # Output controls - preserved from original
        "-oG", "-oJ", "-oX", "-oL",  # Output formats
        "--rotate",                # Rotate output files
    ]
    
    # ORIGINAL TIMEOUT AND CONCURRENCY - PRESERVED EXACTLY
    default_timeout_sec: float = 300.0
    concurrency: int = 1
    
    # ENHANCED CIRCUIT BREAKER CONFIGURATION
    circuit_breaker_failure_threshold: int = 3  # Lower threshold for masscan (network-sensitive)
    circuit_breaker_recovery_timeout: float = 90.0  # 1.5 minutes for masscan
    circuit_breaker_expected_exception: tuple = (Exception,)
    
    def __init__(self):
        """Enhanced initialization with original functionality preserved."""
        # ORIGINAL: Call parent constructor (implicit)
        super().__init__()
        
        # ENHANCED: Setup additional features
        self.config = get_config()
        self._setup_enhanced_features()
    
    def _setup_enhanced_features(self):
        """Setup enhanced features for Masscan tool (ADDITIONAL)."""
        # Override circuit breaker settings from config if available
        if self.config.circuit_breaker_enabled:
            self.circuit_breaker_failure_threshold = self.config.circuit_breaker_failure_threshold
            self.circuit_breaker_recovery_timeout = self.config.circuit_breaker_recovery_timeout
        
        # Reinitialize circuit breaker with new settings
        self._circuit_breaker = None
        self._initialize_circuit_breaker()
    
    async def _execute_tool(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
        """
        Enhanced tool execution with masscan-specific features.
        Uses original _spawn method internally.
        """
        # ENHANCED: Validate masscan-specific requirements
        validation_result = self._validate_masscan_requirements(inp)
        if validation_result:
            return validation_result
        
        # ENHANCED: Add masscan-specific optimizations and safety checks
        optimized_args = self._optimize_masscan_args(inp.extra_args)
        
        # Create enhanced input with optimizations
        enhanced_input = ToolInput(
            target=inp.target,
            extra_args=optimized_args,
            timeout_sec=timeout_sec or self.default_timeout_sec,
            correlation_id=inp.correlation_id
        )
        
        # ORIGINAL: Use parent _execute_tool method which calls _spawn
        return await super()._execute_tool(enhanced_input, timeout_sec)
    
    def _validate_masscan_requirements(self, inp: ToolInput) -> Optional[ToolOutput]:
        """Validate masscan-specific requirements (ENHANCED FEATURE)."""
        # Masscan-specific validations
        
        # Check if target is a large network range (masscan can handle large ranges but we should warn)
        if "/" in inp.target:
            try:
                import ipaddress
                network = ipaddress.ip_network(inp.target, strict=False)
                if network.num_addresses > 65536:  # More than a /16 network
                    # This is a warning, not an error, as masscan is designed for large scans
                    log.warning("masscan.large_network_range target=%s size=%d", 
                               inp.target, network.num_addresses)
            except ValueError:
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Invalid network range: {inp.target}",
                    recovery_suggestion="Use valid CIDR notation (e.g., 10.0.0.0/24)",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=inp.target
                )
                return self._create_error_output(error_context, inp.correlation_id)
        
        return None
    
    def _optimize_masscan_args(self, extra_args: str) -> str:
        """Optimize masscan arguments for performance and safety (ENHANCED FEATURE)."""
        if not extra_args:
            return ""
        
        args = extra_args.split()
        optimized = []
        
        # Masscan-specific optimizations
        has_rate = any(arg.startswith("--rate") for arg in args)
        has_wait = any(arg.startswith("--wait") for arg in args)
        has_output_format = any(arg in ("-oG", "-oJ", "-oX", "-oL") for arg in args)
        
        # Add default rate limiting if not specified (important for network safety)
        if not has_rate:
            optimized.append("--rate=1000")  # Default to 1000 packets per second
        
        # Add small wait between packets if not specified (reduces network impact)
        if not has_wait:
            optimized.append("--wait=0.1")  # 100ms wait between packets
        
        # Add existing args
        optimized.extend(args)
        
        return " ".join(optimized)
    
    def _get_timestamp(self):
        """Get current timestamp (ENHANCED HELPER)."""
        from datetime import datetime
        return datetime.now()
    
    def get_tool_info(self) -> dict:
        """Get enhanced tool information (ENHANCED FEATURE)."""
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
            "network_safety": {
                "default_rate": "1000 packets/sec",
                "default_wait": "100ms",
                "large_network_support": True
            }
        }
        
        # Add metrics if available
        if hasattr(self, 'metrics') and self.metrics:
            base_info["metrics"] = {
                "prometheus_available": True,
                "execution_metrics": f"mcp_tool_execution_total{{tool=\"{self.tool_name}\"}}"
            }
        
        return base_info
