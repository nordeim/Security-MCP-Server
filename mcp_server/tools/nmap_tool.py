"""
Enhanced Nmap tool with circuit breaker, metrics, and advanced features.
Production-ready implementation with comprehensive safety checks.
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


class NmapTool(MCPBaseTool):
    """
    Enhanced Nmap network scanner tool with advanced features.
    
    Features:
    - Circuit breaker protection for resilience
    - Network range validation and limits
    - Port specification safety
    - Script execution controls
    - Performance optimizations
    - Comprehensive metrics
    """
    
    command_name: str = "nmap"
    
    # Conservative, safe flags for nmap
    allowed_flags: Sequence[str] = (
        "-sV", "-sC", "-A", "-p", "--top-ports", "-T", "-T4", "-Pn",
        "-O", "--script", "-oX", "-oN", "-oG", "--max-parallelism",
        "-sS", "-sT", "-sU", "-sn", "-PS", "-PA", "-PU", "-PY",
        "--open", "--reason", "-v", "-vv", "--version-intensity",
        "--min-rate", "--max-rate", "--max-retries", "--host-timeout",
    )
    
    # Nmap can run long; set higher timeout
    default_timeout_sec: float = 600.0
    
    # Limit concurrency to avoid overloading
    concurrency: int = 1
    
    # Circuit breaker configuration
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: float = 120.0
    circuit_breaker_expected_exception: tuple = (Exception,)
    
    # Safety limits
    MAX_NETWORK_SIZE = 1024  # Maximum number of hosts in a network range
    MAX_PORT_RANGES = 100    # Maximum number of port ranges
    SAFE_SCRIPTS = [
        "safe", "default", "discovery", "version", "vuln",
        "http-headers", "ssl-cert", "ssh-hostkey"
    ]
    
    def __init__(self):
        """Initialize Nmap tool with enhanced features."""
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
                if hasattr(tool, 'default_concurrency'):
                    self.concurrency = int(tool.default_concurrency)
        except Exception as e:
            log.debug("nmap.config_apply_failed error=%s using_defaults", str(e))
    
    async def _execute_tool(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
        """Execute Nmap with enhanced validation and optimization."""
        # Validate nmap-specific requirements
        validation_result = self._validate_nmap_requirements(inp)
        if validation_result:
            return validation_result
        
        # Parse and validate arguments
        try:
            parsed_args = self._parse_and_validate_args(inp.extra_args or "")
        except ValueError as e:
            error_context = ErrorContext(
                error_type=ToolErrorType.VALIDATION_ERROR,
                message=f"Invalid arguments: {str(e)}",
                recovery_suggestion="Check argument syntax and allowed flags",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target,
                metadata={"error": str(e)}
            )
            return self._create_error_output(error_context, inp.correlation_id or "")
        
        # Optimize arguments
        optimized_args = self._optimize_nmap_args(parsed_args)
        
        # Create enhanced input
        enhanced_input = ToolInput(
            target=inp.target,
            extra_args=optimized_args,
            timeout_sec=timeout_sec or inp.timeout_sec or self.default_timeout_sec,
            correlation_id=inp.correlation_id,
        )
        
        # Execute with base class method
        return await super()._execute_tool(enhanced_input, enhanced_input.timeout_sec)
    
    def _validate_nmap_requirements(self, inp: ToolInput) -> Optional[ToolOutput]:
        """Validate nmap-specific requirements."""
        target = inp.target.strip()
        
        # Validate network ranges
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
                    metadata={"input": target}
                )
                return self._create_error_output(error_context, inp.correlation_id or "")
            
            # Check network size
            if network.num_addresses > self.MAX_NETWORK_SIZE:
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Network range too large: {network.num_addresses} addresses (max: {self.MAX_NETWORK_SIZE})",
                    recovery_suggestion=f"Use smaller network ranges (max /{32 - network.prefixlen + 10} for IPv4)",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                    metadata={
                        "network_size": network.num_addresses,
                        "max_allowed": self.MAX_NETWORK_SIZE
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
        else:
            # Single host validation
            try:
                ip = ipaddress.ip_address(target)
                if not (ip.is_private or ip.is_loopback):
                    error_context = ErrorContext(
                        error_type=ToolErrorType.VALIDATION_ERROR,
                        message=f"Only private IPs allowed: {target}",
                        recovery_suggestion="Use RFC1918 or loopback addresses",
                        timestamp=self._get_timestamp(),
                        tool_name=self.tool_name,
                        target=target,
                        metadata={"ip": str(ip)}
                    )
                    return self._create_error_output(error_context, inp.correlation_id or "")
            except ValueError:
                # Must be a hostname
                if not target.endswith(".lab.internal"):
                    error_context = ErrorContext(
                        error_type=ToolErrorType.VALIDATION_ERROR,
                        message=f"Only .lab.internal hostnames allowed: {target}",
                        recovery_suggestion="Use hostnames ending with .lab.internal",
                        timestamp=self._get_timestamp(),
                        tool_name=self.tool_name,
                        target=target,
                        metadata={"hostname": target}
                    )
                    return self._create_error_output(error_context, inp.correlation_id or "")
        
        return None
    
    def _parse_and_validate_args(self, extra_args: str) -> str:
        """Parse and validate nmap arguments."""
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
            
            # Check port specifications
            if token in ("-p", "--ports"):
                if i + 1 < len(tokens):
                    port_spec = tokens[i + 1]
                    if not self._validate_port_specification(port_spec):
                        raise ValueError(f"Invalid port specification: {port_spec}")
                    validated.extend([token, port_spec])
                    i += 2
                else:
                    raise ValueError(f"Port flag {token} requires a value")
            
            # Check script specifications
            elif token == "--script":
                if i + 1 < len(tokens):
                    script_spec = tokens[i + 1]
                    if not self._validate_script_specification(script_spec):
                        raise ValueError(f"Unsafe script specification: {script_spec}")
                    validated.extend([token, script_spec])
                    i += 2
                else:
                    raise ValueError("--script requires a value")
            
            # Check timing templates
            elif token.startswith("-T"):
                if len(token) == 3 and token[2] in "012345":
                    validated.append(token)
                else:
                    raise ValueError(f"Invalid timing template: {token}")
                i += 1
            
            # Check other flags
            elif token.startswith("-"):
                # Check if it's an allowed flag
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
        # Allow common formats: 80, 80-443, 80,443, 1-1000
        if not port_spec:
            return False
        
        # Check for valid characters
        if not re.match(r'^[\d,\-]+$', port_spec):
            return False
        
        # Count ranges to prevent excessive specifications
        ranges = port_spec.split(',')
        if len(ranges) > self.MAX_PORT_RANGES:
            return False
        
        # Validate each range
        for range_spec in ranges:
            if '-' in range_spec:
                parts = range_spec.split('-')
                if len(parts) != 2:
                    return False
                try:
                    start, end = int(parts[0]), int(parts[1])
                    if not (1 <= start <= 65535 and 1 <= end <= 65535 and start <= end):
                        return False
                except ValueError:
                    return False
            else:
                try:
                    port = int(range_spec)
                    if not 1 <= port <= 65535:
                        return False
                except ValueError:
                    return False
        
        return True
    
    def _validate_script_specification(self, script_spec: str) -> bool:
        """Validate script specification for safety."""
        # Only allow safe scripts or categories
        scripts = script_spec.split(',')
        for script in scripts:
            script = script.strip()
            if script not in self.SAFE_SCRIPTS:
                # Check if it's a safe category
                if not script.startswith(("safe", "default", "discovery")):
                    return False
        return True
    
    def _optimize_nmap_args(self, extra_args: str) -> str:
        """Optimize nmap arguments for performance and safety."""
        if not extra_args:
            extra_args = ""
        
        try:
            tokens = shlex.split(extra_args) if extra_args else []
        except ValueError:
            tokens = extra_args.split() if extra_args else []
        
        optimized = []
        
        # Check what's already specified
        has_timing = any(t.startswith("-T") for t in tokens)
        has_parallelism = any("--max-parallelism" in t for t in tokens)
        has_host_discovery = any(t in ("-Pn", "-sn", "-PS", "-PA") for t in tokens)
        has_port_spec = any(t in ("-p", "--ports") for t in tokens)
        
        # Add optimizations
        if not has_timing:
            optimized.append("-T4")  # Aggressive timing
        
        if not has_parallelism:
            optimized.append("--max-parallelism=10")  # Limit parallel probes
        
        if not has_host_discovery:
            optimized.append("-Pn")  # Skip host discovery for speed
        
        if not has_port_spec:
            optimized.append("--top-ports=1000")  # Scan top 1000 ports by default
        
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
            "description": self.__doc__ or "Nmap network scanner",
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
                "max_port_ranges": self.MAX_PORT_RANGES,
                "safe_scripts": self.SAFE_SCRIPTS
            },
            "optimizations": {
                "default_timing": "T4 (Aggressive)",
                "default_parallelism": 10,
                "default_ports": "top-1000",
                "host_discovery": "disabled (-Pn)"
            },
            "metrics": {
                "available": self.metrics is not None,
                "prometheus": f'mcp_tool_execution_total{{tool="{self.tool_name}"}}' if self.metrics else None
            }
        }
