"""
Enhanced Masscan tool with circuit breaker, metrics, and comprehensive safety features.
Production-ready implementation with strict security controls.
"""
import logging
import shlex
import ipaddress
from datetime import datetime, timezone
from typing import Sequence, Optional, Dict, Any, Union, List
import re
import math

from mcp_server.base_tool import MCPBaseTool, ToolInput, ToolOutput, ToolErrorType, ErrorContext
from mcp_server.config import get_config

log = logging.getLogger(__name__)


class MasscanTool(MCPBaseTool):
    """
    Enhanced Masscan fast port scanner with comprehensive safety features.
    
    Features:
    - Circuit breaker protection for network resilience
    - Rate limiting enforcement with config-based controls
    - Large network range support with safety checks
    - Interface and routing validation
    - Banner grabbing control based on intrusive policy
    - Performance monitoring and metrics
    
    Safety considerations:
    - Targets restricted to RFC1918 or *.lab.internal
    - Conservative flag subset to prevent misuse
    - Rate limiting to prevent network flooding
    - Single concurrency to manage resource usage
    - Non-flag tokens blocked for security
    """
    
    command_name: str = "masscan"
    
    # Conservative allowed flags for safety
    allowed_flags: Sequence[str] = (
        "-p", "--ports",              # Port specification
        "--rate",                     # Rate limiting (critical for safety)
        "-e", "--interface",          # Interface specification
        "--wait",                     # Wait between packets
        "--banners",                  # Banner grabbing (controlled by policy)
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
        "--adapter-ip",               # Adapter IP
        "--adapter-mac",              # Adapter MAC
        "--ttl",                      # TTL value
    )
    
    # Base class integration metadata
    _EXTRA_ALLOWED_TOKENS = set()
    _FLAGS_REQUIRE_VALUE = {
        "-p", "--ports",
        "--rate", "--max-rate",
        "--wait",
        "--retries",
        "--connection-timeout",
        "--ttl",
        "--source-port",
        "-e", "--interface",
        "--source-ip",
        "--router-ip",
        "--router-mac",
        "--adapter-ip",
        "--adapter-mac",
        "--exclude",
        "--excludefile"
    }

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
    MAX_RATE = 100000             # Maximum allowed rate (can be overridden by config)
    MIN_RATE = 100                # Minimum rate for safety
    DEFAULT_WAIT = 1              # Default wait time between packets
    
    def __init__(self):
        """Initialize Masscan tool with enhanced features."""
        super().__init__()
        self.config = get_config()
        # Attributes referenced during configuration
        self.allow_intrusive = False
        self.config_max_rate = self.MAX_RATE
        self._apply_config()

    def _apply_config(self):
        """Apply configuration settings safely."""
        try:
            # Apply circuit breaker config
            cb = getattr(self.config, 'circuit_breaker', None)
            if cb:
                failure_threshold = getattr(cb, 'failure_threshold', None)
                if failure_threshold is not None:
                    self.circuit_breaker_failure_threshold = max(1, min(10, int(failure_threshold)))
                recovery_timeout = getattr(cb, 'recovery_timeout', None)
                if recovery_timeout is not None:
                    self.circuit_breaker_recovery_timeout = max(30.0, min(300.0, float(recovery_timeout)))

            # Apply tool config
            tool_cfg = getattr(self.config, 'tool', None)
            if tool_cfg:
                default_timeout = getattr(tool_cfg, 'default_timeout', None)
                if default_timeout is not None:
                    self.default_timeout_sec = max(60.0, min(1800.0, float(default_timeout)))

            # Apply security config
            sec_cfg = getattr(self.config, 'security', None)
            if sec_cfg:
                if hasattr(sec_cfg, 'allow_intrusive'):
                    self.allow_intrusive = bool(sec_cfg.allow_intrusive)

                max_scan_rate = getattr(sec_cfg, 'max_scan_rate', None)
                if max_scan_rate is not None:
                    self.config_max_rate = max(self.MIN_RATE, min(self.MAX_RATE, int(max_scan_rate)))
                    log.info("masscan.max_rate_from_config rate=%d", self.config_max_rate)

            log.debug("masscan.config_applied intrusive=%s max_rate=%d", 
                     self.allow_intrusive, self.config_max_rate)
        except Exception as e:
            log.warning("masscan.config_apply_failed error=%s using_safe_defaults", str(e))
            # Reset to safe defaults on error
            self.circuit_breaker_failure_threshold = 3
            self.circuit_breaker_recovery_timeout = 90.0
            self.default_timeout_sec = 300.0
            self.allow_intrusive = False
            self.config_max_rate = self.MAX_RATE
    
    async def _execute_tool(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
        """Execute Masscan with enhanced validation and safety."""
        # Validate masscan-specific requirements
        validation_result = self._validate_masscan_requirements(inp)
        if validation_result:
            return validation_result
        
        # Parse and validate arguments
        parsed_args = self._parse_and_validate_args(inp.extra_args or "", inp)
        if isinstance(parsed_args, ToolOutput):
            return parsed_args
        
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
                    max_cidr = self._get_max_cidr_for_size(self.MAX_NETWORK_SIZE * 4)
                    error_context = ErrorContext(
                        error_type=ToolErrorType.VALIDATION_ERROR,
                        message=f"Network range too large: {network.num_addresses} addresses",
                        recovery_suggestion=f"Use /{max_cidr} or smaller (max {self.MAX_NETWORK_SIZE * 4} hosts)",
                        timestamp=self._get_timestamp(),
                        tool_name=self.tool_name,
                        target=target,
                        metadata={
                            "network_size": network.num_addresses,
                            "max_allowed": self.MAX_NETWORK_SIZE * 4,
                            "suggested_cidr": f"/{max_cidr}"
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
    
    def _get_max_cidr_for_size(self, max_hosts: int) -> int:
        """Calculate maximum CIDR prefix for given host count."""
        # For max_hosts, calculate the CIDR prefix
        # Example: 262144 hosts = /14, 65536 hosts = /16, 1024 hosts = /22
        bits_needed = math.ceil(math.log2(max_hosts))
        return max(0, 32 - bits_needed)
    
    def _parse_and_validate_args(self, extra_args: str, inp: ToolInput) -> Union[str, ToolOutput]:
        """Parse and validate masscan arguments with strict security."""
        try:
            tokens = list(super()._parse_args(extra_args))
        except ValueError as e:
            error_context = ErrorContext(
                error_type=ToolErrorType.VALIDATION_ERROR,
                message=str(e),
                recovery_suggestion="Check argument syntax and rate limits",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target,
                metadata={"error": str(e)}
            )
            return self._create_error_output(error_context, inp.correlation_id or "")

        validated: List[str] = []
        i = 0
        while i < len(tokens):
            token = tokens[i]

            # Check rate specifications
            if token in ("--rate", "--max-rate"):
                if i + 1 < len(tokens):
                    rate_spec = tokens[i + 1]
                    try:
                        rate = int(rate_spec)
                        # Apply config-based max rate
                        if rate > self.config_max_rate:
                            log.warning("masscan.rate_limited requested=%d max=%d", rate, self.config_max_rate)
                            rate = self.config_max_rate
                        elif rate < self.MIN_RATE:
                            log.warning("masscan.rate_increased requested=%d min=%d", rate, self.MIN_RATE)
                            rate = self.MIN_RATE
                        validated.extend([token, str(rate)])
                    except ValueError:
                        return self._create_error_output(
                            ErrorContext(
                                error_type=ToolErrorType.VALIDATION_ERROR,
                                message=f"Invalid rate specification: {rate_spec}",
                                recovery_suggestion="Use numeric packet rate",
                                timestamp=self._get_timestamp(),
                                tool_name=self.tool_name,
                                target=inp.target,
                                metadata={"flag": token, "value": rate_spec}
                            ),
                            inp.correlation_id or ""
                        )
                    i += 2
                    continue
                return self._create_error_output(
                    ErrorContext(
                        error_type=ToolErrorType.VALIDATION_ERROR,
                        message=f"{token} requires a value",
                        recovery_suggestion="Provide numeric rate value",
                        timestamp=self._get_timestamp(),
                        tool_name=self.tool_name,
                        target=inp.target,
                        metadata={"flag": token}
                    ),
                    inp.correlation_id or ""
                )

            # Check port specifications
            if token in ("-p", "--ports"):
                if i + 1 < len(tokens):
                    port_spec = tokens[i + 1]
                    if not self._validate_port_specification(port_spec):
                        return self._create_error_output(
                            ErrorContext(
                                error_type=ToolErrorType.VALIDATION_ERROR,
                                message=f"Invalid port specification: {port_spec}",
                                recovery_suggestion="Use formats like 80,443 or 1-1024",
                                timestamp=self._get_timestamp(),
                                tool_name=self.tool_name,
                                target=inp.target,
                                metadata={"flag": token, "value": port_spec}
                            ),
                            inp.correlation_id or ""
                        )
                    validated.extend([token, port_spec])
                    i += 2
                    continue
                return self._create_error_output(
                    ErrorContext(
                        error_type=ToolErrorType.VALIDATION_ERROR,
                        message=f"Port flag {token} requires a value",
                        recovery_suggestion="Provide port list or range",
                        timestamp=self._get_timestamp(),
                        tool_name=self.tool_name,
                        target=inp.target,
                        metadata={"flag": token}
                    ),
                    inp.correlation_id or ""
                )

            # Check banner grabbing (controlled by policy)
            if token == "--banners":
                if not self.allow_intrusive:
                    log.warning("masscan.banners_blocked intrusive_not_allowed")
                    i += 1
                    continue
                validated.append(token)
                i += 1
                continue

            # Check interface specifications
            if token in ("-e", "--interface"):
                if i + 1 < len(tokens):
                    interface = tokens[i + 1]
                    if not re.match(r'^[a-zA-Z0-9_\-.]+$', interface):
                        return self._create_error_output(
                            ErrorContext(
                                error_type=ToolErrorType.VALIDATION_ERROR,
                                message=f"Invalid interface name: {interface}",
                                recovery_suggestion="Use simple interface identifiers (e.g., eth0)",
                                timestamp=self._get_timestamp(),
                                tool_name=self.tool_name,
                                target=inp.target,
                                metadata={"flag": token, "value": interface}
                            ),
                            inp.correlation_id or ""
                        )
                    validated.extend([token, interface])
                    i += 2
                    continue
                return self._create_error_output(
                    ErrorContext(
                        error_type=ToolErrorType.VALIDATION_ERROR,
                        message=f"Interface flag {token} requires a value",
                        recovery_suggestion="Specify interface name after the flag",
                        timestamp=self._get_timestamp(),
                        tool_name=self.tool_name,
                        target=inp.target,
                        metadata={"flag": token}
                    ),
                    inp.correlation_id or ""
                )

            # For other flags, rely on base sanitizer output
            validated.append(token)
            i += 1

        return " ".join(validated)
    
    def _validate_port_specification(self, port_spec: str) -> bool:
        """Validate port specification for safety."""
        # Allow formats: 80, 80-443, 80,443, 1-65535
        # But exclude port 0 for security
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
                    # Exclude port 0
                    if start == 0 or end == 0:
                        log.warning("masscan.port_zero_blocked")
                        return False
                    if not (1 <= start <= 65535 and 1 <= end <= 65535 and start <= end):
                        return False
                except ValueError:
                    return False
            else:
                try:
                    port = int(range_spec)
                    # Exclude port 0
                    if port == 0:
                        log.warning("masscan.port_zero_blocked")
                        return False
                    if not 1 <= port <= 65535:
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
        has_rate = any("--rate" in t or "--max-rate" in t for t in tokens)
        has_wait = any("--wait" in t for t in tokens)
        has_retries = any("--retries" in t for t in tokens)
        has_ports = any(t in ("-p", "--ports") for t in tokens)
        
        # Add safety defaults
        if not has_rate:
            # Use conservative default rate
            default_rate = min(self.DEFAULT_RATE, self.config_max_rate)
            optimized.extend(["--rate", str(default_rate)])
            log.info("masscan.rate_limit_applied rate=%d", default_rate)
        
        if not has_wait:
            optimized.extend(["--wait", str(self.DEFAULT_WAIT)])
        
        if not has_retries:
            optimized.extend(["--retries", "1"])  # Minimal retries for speed
        
        if not has_ports:
            # Default to common ports if not specified
            if self.allow_intrusive:
                # More comprehensive port list for intrusive mode
                optimized.extend(["-p", "21-23,25,53,80,110,111,135,139,143,443,445,993,995,1723,3306,3389,5900,8080,8443"])
            else:
                # Conservative port list
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
            "intrusive_allowed": self.allow_intrusive,
            "circuit_breaker": {
                "enabled": self._circuit_breaker is not None,
                "failure_threshold": self.circuit_breaker_failure_threshold,
                "recovery_timeout": self.circuit_breaker_recovery_timeout,
                "state": self._circuit_breaker.state.name if self._circuit_breaker else "N/A"
            },
            "safety_limits": {
                "max_network_size": self.MAX_NETWORK_SIZE,
                "default_rate": self.DEFAULT_RATE,
                "config_max_rate": self.config_max_rate,
                "min_rate": self.MIN_RATE,
                "banner_grabbing": "allowed" if self.allow_intrusive else "blocked"
            },
            "network_safety": {
                "rate_limiting": f"{min(self.DEFAULT_RATE, self.config_max_rate)} packets/sec",
                "wait_time": f"{self.DEFAULT_WAIT}s between packets",
                "retries": 1,
                "large_network_support": True,
                "port_zero_blocked": True
            },
            "metrics": {
                "available": self.metrics is not None,
                "prometheus": f'mcp_tool_execution_total{{tool="{self.tool_name}"}}' if self.metrics else None
            }
        }
