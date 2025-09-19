"""
Enhanced Masscan tool with circuit breaker, metrics, and safety features.
Production-ready implementation with comprehensive network safety.
"""
import logging
import shlex
import ipaddress
from datetime import datetime, timezone
from typing import Sequence, Optional, Dict, Any
import re

from mcp_server.base_tool import MCPBaseTool, ToolInput, ToolOutput, ToolErrorType, ErrorContext
from mcp_server.config import get_config

log = logging.getLogger(__name__)


class MasscanTool(MCPBaseTool):
    """
    Enhanced Masscan fast port scanner with comprehensive safety features.
    
    Features:
    - Circuit breaker protection for network resilience
    - Rate limiting enforcement
    - Large network range support with safety checks
    - Interface and routing validation
    - Performance monitoring and metrics
    
    Safety considerations:
    - Targets restricted to RFC1918 or *.lab.internal
    - Conservative flag subset to prevent misuse
    - Rate limiting to prevent network flooding
    - Single concurrency to manage resource usage
    """
    
    command_name: str = "masscan"
    
    # Conservative allowed flags for safety
    allowed_flags: Sequence[str] = (
        "-p", "--ports",              # Port specification
        "--rate",                     # Rate limiting (critical for safety)
        "-e", "--interface",          # Interface specification
        "--wait",                     # Wait between packets
        "--banners",                  # Banner grabbing
        "--router-ip",                # Router IP specification
        "--router-mac",               # Router MAC specification
        "--source-ip",                # Source IP specification
        "--source-port",              # Source port specification
        "--exclude",                  # Exclude targets
        "--excludefile",              # Exclude targets from file
        "-oG", "-oJ", "-oX", "-oL",  # Output formats
        "--rotate",                   # Rotate output files
        "--max-rate",                 # Maximum rate limit
        "--connection-timeout",       # Connection timeout
        "--ping",                     # Ping probe
        "--retries",                  # Retry count
    )
    
    # Masscan-specific settings
    default_timeout_sec: float = 300.0
    concurrency: int = 1  # Single instance due to high resource usage
    
    # Circuit breaker configuration
    circuit_breaker_failure_threshold: int = 3
    circuit_breaker_recovery_timeout: float = 90.0
    circuit_breaker_expected_exception: tuple = (Exception,)
    
    # Safety limits
    MAX_NETWORK_SIZE = 65536     # Maximum /16 network
    DEFAULT_RATE = 1000           # Default packets per second
    MAX_RATE = 100000             # Maximum allowed rate
    MIN_RATE = 100                # Minimum rate for safety
    DEFAULT_WAIT = 0              # Default wait between packets (seconds)
    
    def __init__(self):
        """Initialize Masscan tool with enhanced features."""
        super().__init__()
        self.config = get_config()
        self._apply_config()
    
    def _apply_config(self):
        """Apply configuration settings safely."""
        try:
            if hasattr(self.config, 'circuit_breaker') and self.config.circuit_breaker:
                cb = self.config.circuit_breaker
                if hasattr(cb, 'failure_threshold'):
                    self.circuit_breaker_failure_threshold = int(cb.failure_threshold)
                if hasattr(cb, 'recovery_timeout'):
                    self.circuit_breaker_recovery_timeout = float(cb.recovery_timeout)
            
            if hasattr(self.config, 'tool') and self.config.tool:
                tool = self.config.tool
                if hasattr(tool, 'default_timeout'):
                    self.default_timeout_sec = float(tool.default_timeout)
        except Exception as e:
            log.debug("masscan.config_apply_failed error=%s using_defaults", str(e))
    
    async def _execute_tool(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
        """Execute Masscan with enhanced validation and safety."""
        # Validate masscan-specific requirements
        validation_result = self._validate_masscan_requirements(inp)
        if validation_result:
            return validation_result
        
        # Parse and validate arguments
        try:
            parsed_args = self._parse_and_validate_args(inp.extra_args or "")
        except ValueError as e:
            error_context = ErrorContext(
                error_type=ToolErrorType.VALIDATION_ERROR,
                message=f"Invalid arguments: {str(e)}",
                recovery_suggestion="Check argument syntax and rate limits",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target,
                metadata={"error": str(e)}
            )
            return self._create_error_output(error_context, inp.correlation_id or "")
        
        # Apply safety optimizations
        safe_args = self._apply_safety_limits(parsed_args)
        
        # Create enhanced input
        enhanced_input = ToolInput(
            target=inp.target,
            extra_args=safe_args,
            timeout_sec=timeout_sec or inp.timeout_sec or self.default_timeout_sec,
            correlation_id=inp.correlation_id,
        )
        
        # Execute with base class method
        return await super()._execute_tool(enhanced_input, enhanced_input.timeout_sec)
    
    def _validate_masscan_requirements(self, inp: ToolInput) -> Optional[ToolOutput]:
        """Validate masscan-specific requirements."""
        target = inp.target.strip()
        
        # Validate network ranges
        if "/" in target:
            try:
                network = ipaddress.ip_network(target, strict=False)
            except ValueError:
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Invalid network range: {target}",
                    recovery_suggestion="Use valid CIDR notation (e.g., 10.0.0.0/24)",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                    metadata={"input": target}
                )
                return self._create_error_output(error_context, inp.correlation_id or "")
            
            # Check network size (masscan can handle large ranges but warn)
            if network.num_addresses > self.MAX_NETWORK_SIZE:
                log.warning("masscan.large_network target=%s size=%d max=%d",
                           target, network.num_addresses, self.MAX_NETWORK_SIZE)
                
                # Still block if extremely large
                if network.num_addresses > self.MAX_NETWORK_SIZE * 4:
                    error_context = ErrorContext(
                        error_type=ToolErrorType.VALIDATION_ERROR,
                        message=f"Network range too large: {network.num_addresses} addresses",
                        recovery_suggestion=f"Maximum supported: {self.MAX_NETWORK_SIZE * 4} addresses",
                        timestamp=self._get_timestamp(),
                        tool_name=self.tool_name,
                        target=target,
                        metadata={
                            "network_size": network.num_addresses,
                            "max_allowed": self.MAX_NETWORK_SIZE * 4
                        }
                    )
                    return self._create_error_output(error_context, inp.correlation_id or "")
            
            # Ensure private network
            if not (network.is_private or network.is_loopback):
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Only private networks allowed: {target}",
                    recovery_suggestion="Use RFC1918 ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                    metadata={"network": str(network)}
                )
                return self._create_error_output(error_context, inp.correlation_id or "")
        
        return None
    
    def _parse_and_validate_args(self, extra_args: str) -> str:
        """Parse and validate masscan arguments."""
        if not extra_args:
            return ""
        
        try:
            tokens = shlex.split(extra_args)
        except ValueError as e:
            raise ValueError(f"Failed to parse arguments: {str(e)}")
        
        validated = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            
            # Check rate specifications
            if token == "--rate":
                if i + 1 < len(tokens):
                    rate_spec = tokens[i + 1]
                    try:
                        rate = int(rate_spec)
                        if not (self.MIN_RATE <= rate <= self.MAX_RATE):
                            raise ValueError(f"Rate must be between {self.MIN_RATE} and {self.MAX_RATE}")
                        validated.extend([token, str(rate)])
                    except ValueError:
                        raise ValueError(f"Invalid rate specification: {rate_spec}")
                    i += 2
                else:
                    raise ValueError("--rate requires a value")
            
            # Check port specifications
            elif token in ("-p", "--ports"):
                if i + 1 < len(tokens):
                    port_spec = tokens[i + 1]
                    if not self._validate_port_specification(port_spec):
                        raise ValueError(f"Invalid port specification: {port_spec}")
                    validated.extend([token, port_spec])
                    i += 2
                else:
                    raise ValueError(f"Port flag {token} requires a value")
            
            # Check interface specifications
            elif token in ("-e", "--interface"):
                if i + 1 < len(tokens):
                    interface = tokens[i + 1]
                    # Basic interface name validation
                    if not re.match(r'^[a-zA-Z0-9_\-\.]+$', interface):
                        raise ValueError(f"Invalid interface name: {interface}")
                    validated.extend([token, interface])
                    i += 2
                else:
                    raise ValueError(f"Interface flag {token} requires a value")
            
            # Check other flags
            elif token.startswith("-"):
                flag_base = token.split("=")[0] if "=" in token else token
                if any(flag_base.startswith(allowed) for allowed in self.allowed_flags):
                    validated.append(token)
                else:
                    raise ValueError(f"Flag not allowed: {token}")
                i += 1
            
            else:
                # Non-flag tokens
                validated.append(token)
                i += 1
        
        return " ".join(validated)
    
    def _validate_port_specification(self, port_spec: str) -> bool:
        """Validate port specification for safety."""
        # Allow formats: 80, 80-443, 80,443, 1-65535
        if not port_spec:
            return False
        
        # Special case for masscan's U: and T: prefixes
        if port_spec.startswith(('U:', 'T:')):
            port_spec = port_spec[2:]
        
        # Check for valid characters
        if not re.match(r'^[\d,\-]+$', port_spec):
            return False
        
        # Validate ranges
        for range_spec in port_spec.split(','):
            if '-' in range_spec:
                parts = range_spec.split('-')
                if len(parts) != 2:
                    return False
                try:
                    start, end = int(parts[0]), int(parts[1])
                    if not (0 <= start <= 65535 and 0 <= end <= 65535 and start <= end):
                        return False
                except ValueError:
                    return False
            else:
                try:
                    port = int(range_spec)
                    if not 0 <= port <= 65535:
                        return False
                except ValueError:
                    return False
        
        return True
    
    def _apply_safety_limits(self, extra_args: str) -> str:
        """Apply safety limits and optimizations to masscan arguments."""
        if not extra_args:
            extra_args = ""
        
        try:
            tokens = shlex.split(extra_args) if extra_args else []
        except ValueError:
            tokens = extra_args.split() if extra_args else []
        
        optimized = []
        
        # Check what's already specified
        has_rate = any("--rate" in t for t in tokens)
        has_wait = any("--wait" in t for t in tokens)
        has_retries = any("--retries" in t for t in tokens)
        has_ports = any(t in ("-p", "--ports") for t in tokens)
        
        # Add safety defaults
        if not has_rate:
            optimized.extend(["--rate", str(self.DEFAULT_RATE)])
            log.info("masscan.rate_limit_applied rate=%d", self.DEFAULT_RATE)
        
        if not has_wait:
            optimized.extend(["--wait", str(self.DEFAULT_WAIT)])
        
        if not has_retries:
            optimized.extend(["--retries", "1"])  # Minimal retries for speed
        
        if not has_ports:
            # Default to common ports if not specified
            optimized.extend(["-p", "80,443,22,21,23,25,3306,3389,8080,8443"])
        
        # Add existing arguments
        optimized.extend(tokens)
        
        return " ".join(optimized)
    
    def _get_timestamp(self) -> datetime:
        """Get current timestamp with timezone."""
        return datetime.now(timezone.utc)
    
    def get_tool_info(self) -> Dict[str, Any]:
        """Get comprehensive tool information."""
        return {
            "name": self.tool_name,
            "command": self.command_name,
            "description": self.__doc__ or "Masscan fast port scanner",
            "concurrency": self.concurrency,
            "timeout": self.default_timeout_sec,
            "allowed_flags": list(self.allowed_flags),
            "circuit_breaker": {
                "enabled": self._circuit_breaker is not None,
                "failure_threshold": self.circuit_breaker_failure_threshold,
                "recovery_timeout": self.circuit_breaker_recovery_timeout,
                "state": self._circuit_breaker.state.name if self._circuit_breaker else "N/A"
            },
            "safety_limits": {
                "max_network_size": self.MAX_NETWORK_SIZE,
                "default_rate": self.DEFAULT_RATE,
                "max_rate": self.MAX_RATE,
                "min_rate": self.MIN_RATE
            },
            "network_safety": {
                "rate_limiting": f"{self.DEFAULT_RATE} packets/sec",
                "wait_time": f"{self.DEFAULT_WAIT}s between packets",
                "retries": 1,
                "large_network_support": True
            },
            "metrics": {
                "available": self.metrics is not None,
                "prometheus": f'mcp_tool_execution_total{{tool="{self.tool_name}"}}' if self.metrics else None
            }
        }
