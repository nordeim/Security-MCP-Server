you are really awesome! please keep up the good work! now, please use the same rigorous and meticulous approach to review and validate the following tool files for the custom MCP server build. then meticulously create a comprehensive execution plan to create a complete production-ready *drop-in* replacement file for each of the files that need updating, include in your plan integrated checklist for each file that needs updating. then review and validate your plan before executing cautiously to create complete fully working updated version for the following tool files. after generating each updated file, validate that the updated file is complete without any placeholder comments and that the checklist passed.

```python
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
    """
    command_name: str = "nmap"

    # Conservative, safe flags for nmap (prefix/option names only; values allowed after '=' or space)
    allowed_flags: Sequence[str] = [
        "-sV", "-sC", "-A", "-p", "--top-ports", "-T", "-T4", "-Pn",
        "-O", "--script", "-oX", "-oN", "-oG", "--max-parallelism",
    ]

    # Nmap can run long; set higher timeout
    default_timeout_sec: float = 600.0

    # Limit concurrency to avoid overloading host and network
    concurrency: int = 1

    # Circuit breaker configuration defaults
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: float = 120.0  # 2 minutes for nmap
    circuit_breaker_expected_exception: tuple = (Exception,)

    def __init__(self):
        super().__init__()
        self.config = get_config()
        self._setup_enhanced_features()

    def _setup_enhanced_features(self):
        """Setup enhanced features for Nmap tool."""
        # Prefer explicit structured config if available
        try:
            cb = getattr(self.config, "circuit_breaker", None)
            if cb:
                # MCPConfig uses nested circuit_breaker dataclass
                self.circuit_breaker_failure_threshold = getattr(cb, "failure_threshold", self.circuit_breaker_failure_threshold)
                self.circuit_breaker_recovery_timeout = getattr(cb, "recovery_timeout", self.circuit_breaker_recovery_timeout)
            else:
                # Fallback to optional flat env-like flags if present on config object
                if getattr(self.config, "circuit_breaker_enabled", False):
                    self.circuit_breaker_failure_threshold = getattr(self.config, "circuit_breaker_failure_threshold", self.circuit_breaker_failure_threshold)
                    self.circuit_breaker_recovery_timeout = getattr(self.config, "circuit_breaker_recovery_timeout", self.circuit_breaker_recovery_timeout)
        except Exception:
            log.debug("nmap._setup_enhanced_features: unable to read config; using defaults")

        # Reinitialize circuit breaker with new settings (class-level, not instance)
        try:
            type(self)._circuit_breaker = None
        except Exception:
            self.__class__._circuit_breaker = None
        self._initialize_circuit_breaker()

    async def _execute_tool(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
        """Enhanced tool execution with nmap-specific features."""
        # Validate nmap-specific requirements
        validation_result = self._validate_nmap_requirements(inp)
        if validation_result:
            return validation_result

        # Add nmap-specific optimizations
        optimized_args = self._optimize_nmap_args(inp.extra_args or "")

        # Create enhanced input with optimizations
        enhanced_input = ToolInput(
            target=inp.target,
            extra_args=optimized_args,
            timeout_sec=timeout_sec or self.default_timeout_sec,
            correlation_id=inp.correlation_id,
        )

        # Execute with enhanced monitoring - pass the enhanced timeout explicitly
        return await super()._execute_tool(enhanced_input, enhanced_input.timeout_sec)

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
            return ""

        try:
            args = shlex.split(extra_args)
        except ValueError as e:
            log.warning("nmap.args.parse_failed tool=%s error=%s args=%r", self.tool_name, str(e), extra_args)
            return extra_args

        optimized: list[str] = []

        has_timing = any(a.startswith("-T") for a in args)
        has_parallelism = any(a.startswith("--max-parallelism") for a in args)
        has_host_discovery = any(a in ("-Pn", "-sn") for a in args)

        if not has_timing:
            optimized.append("-T4")

        if not has_parallelism:
            optimized.append("--max-parallelism=10")

        if not has_host_discovery:
            optimized.append("-Pn")

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

        if hasattr(self, "metrics") and self.metrics:
            base_info["metrics"] = {
                "prometheus_available": True,
                "execution_metrics": f'mcp_tool_execution_total{{tool="{self.tool_name}"}}',
            }

        return base_info
```

```python
# File: masscan_tool.py
"""
Enhanced Masscan tool with ALL original functionality preserved + comprehensive enhancements.
"""
import logging
from typing import Sequence, Optional
from datetime import datetime
import ipaddress

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
        "--exclude",               # Exclude targets
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
        super().__init__()
        self.config = get_config()
        self._setup_enhanced_features()
    
    def _setup_enhanced_features(self):
        """Setup enhanced features for Masscan tool (ADDITIONAL)."""
        # Prefer structured config if available
        try:
            if hasattr(self.config, 'circuit_breaker') and self.config.circuit_breaker:
                self.circuit_breaker_failure_threshold = self.config.circuit_breaker.failure_threshold
                self.circuit_breaker_recovery_timeout = self.config.circuit_breaker.recovery_timeout
        except Exception:
            log.debug("masscan._setup_enhanced_features: unable to read config; using defaults")
        
        # Reinitialize circuit breaker at the class level so base class uses new settings
        try:
            type(self)._circuit_breaker = None
        except Exception:
            self.__class__._circuit_breaker = None
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
        optimized_args = self._optimize_masscan_args(inp.extra_args or "")
        
        # Create enhanced input with optimizations
        enhanced_input = ToolInput(
            target=inp.target,
            extra_args=optimized_args,
            timeout_sec=(timeout_sec or self.default_timeout_sec),
            correlation_id=inp.correlation_id
        )
        
        # ORIGINAL: Use parent _execute_tool method which calls _spawn
        # Pass the computed enhanced timeout explicitly to ensure correct behavior
        return await super()._execute_tool(enhanced_input, enhanced_input.timeout_sec)
    
    def _validate_masscan_requirements(self, inp: ToolInput) -> Optional[ToolOutput]:
        """Validate masscan-specific requirements (ENHANCED FEATURE)."""
        # Masscan-specific validations
        
        # Check if target is a large network range (masscan can handle large ranges but we should warn)
        if "/" in inp.target:
            try:
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
        # has_output_format is detected but not used further here; kept for future extensions
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
```

```python
# File: gobuster_tool.py
"""
Enhanced Gobuster tool with ALL original functionality preserved + comprehensive enhancements.
"""
import logging
from typing import List, Sequence, Tuple, Optional
from datetime import datetime

# ORIGINAL IMPORTS - PRESERVED EXACTLY
from mcp_server.base_tool import MCPBaseTool, ToolInput, ToolOutput, ToolErrorType, ErrorContext

# ENHANCED IMPORT (ADDITIONAL)
from mcp_server.config import get_config

log = logging.getLogger(__name__)

class GobusterTool(MCPBaseTool):
    """
    Enhanced Gobuster content/dns/vhost discovery tool with ALL original functionality preserved.
    
    ORIGINAL DOCSTRING PRESERVED:
    Gobuster requires a mode subcommand and either -u (dir/vhost) or -d (dns).
    This tool enforces:
    - Allowed modes: dir, dns, vhost
    - Allowed flags: curated subset per safety
    - If -u/-d is omitted, target from ToolInput is injected appropriately
    (dir/vhost -> -u , dns -> -d ). - Target validation from base class ensures RFC1918 or *.lab.internal. Examples: gobuster dir -u http://192.168.1.10/ -w /lists/common.txt -t 50 gobuster dns -d lab[...]
    
    ENHANCED FEATURES:
    - Circuit breaker protection
    - Wordlist safety validation
    - Request throttling
    - Mode-specific optimizations
    - Enhanced error handling
    """
    
    # ORIGINAL CLASS VARIABLES - PRESERVED EXACTLY
    command_name: str = "gobuster"
    allowed_modes: Tuple[str, ...] = ("dir", "dns", "vhost")
    allowed_flags: Sequence[str] = [
        # Common flags - preserved from original
        "-w", "--wordlist",           # Wordlist specification
        "-t", "--threads",            # Thread count
        "-q", "--quiet",              # Quiet mode
        "-k", "--no-tls-validation",  # Skip TLS validation
        "-o", "--output",             # Output file
        "-s", "--status-codes",       # Status codes
        "-x", "--extensions",         # Extensions
        "--timeout",                  # Timeout
        "--no-color",                 # No color output
        "-H", "--header",             # Headers
        "-r", "--follow-redirect",    # Follow redirects
        # Mode-specific flags - preserved from original
        "-u", "--url",                # URL (dir, vhost)
        "-d", "--domain",              # Domain (dns)
        "--wildcard",                 # Wildcard detection
        "--append-domain",            # Append domain
    ]
    
    # ORIGINAL TIMEOUT AND CONCURRENCY - PRESERVED EXACTLY
    default_timeout_sec: float = 1200.0
    concurrency: int = 1
    
    # ENHANCED CIRCUIT BREAKER CONFIGURATION
    circuit_breaker_failure_threshold: int = 4  # Medium threshold for gobuster
    circuit_breaker_recovery_timeout: float = 180.0  # 3 minutes for gobuster
    circuit_breaker_expected_exception: tuple = (Exception,)
    
    def __init__(self):
        """Enhanced initialization with original functionality preserved."""
        # ORIGINAL: Call parent constructor (implicit)
        super().__init__()
        
        # ENHANCED: Setup additional features
        self.config = get_config()
        self._setup_enhanced_features()
    
    def _setup_enhanced_features(self):
        """Setup enhanced features for Gobuster tool (ADDITIONAL)."""
        # Override circuit breaker settings from config if available
        if hasattr(self.config, 'circuit_breaker') and self.config.circuit_breaker:
            self.circuit_breaker_failure_threshold = self.config.circuit_breaker.failure_threshold
            self.circuit_breaker_recovery_timeout = self.config.circuit_breaker.recovery_timeout
        
        # Reinitialize circuit breaker at the class level so base class uses new settings
        try:
            type(self)._circuit_breaker = None
        except Exception:
            # Fallback if unusual environment: ensure the class-level attribute is cleared
            self.__class__._circuit_breaker = None
        self._initialize_circuit_breaker()
    
    # ==================== ORIGINAL METHODS - PRESERVED EXACTLY ====================
    
    def _split_tokens(self, extra_args: str) -> List[str]:
        """ORIGINAL METHOD - PRESERVED EXACTLY"""
        # Reuse base safety checks, but we need raw tokens to inspect mode
        tokens = super()._parse_args(extra_args)
        return list(tokens)
    
    def _extract_mode_and_args(self, tokens: List[str]) -> Tuple[str, List[str]]:
        """ORIGINAL METHOD - PRESERVED EXACTLY"""
        # Determine mode and return (mode, remaining_args_without_mode). The mode must be the first token not starting with '-'.
        mode = None
        rest: List[str] = []
        
        for i, tok in enumerate(tokens):
            if tok.startswith("-"):
                rest.append(tok)
                continue
            mode = tok
            # everything after this token remains (if any)
            rest.extend(tokens[i + 1 :])
            break
        
        if mode is None:
            raise ValueError("gobuster requires a mode: one of dir, dns, or vhost as the first non-flag token")
        
        if mode not in self.allowed_modes:
            raise ValueError(f"gobuster mode not allowed: {mode!r}")
        
        return mode, rest
    
    def _ensure_target_arg(self, mode: str, args: List[str], target: str) -> List[str]:
        """ORIGINAL METHOD - PRESERVED EXACTLY"""
        # Ensure the proper -u/-d argument is present; inject from ToolInput if missing.
        out = list(args)
        has_u = any(a in ("-u", "--url") for a in out)
        has_d = any(a in ("-d", "--domain") for a in out)
        
        if mode in ("dir", "vhost"):
            if not has_u:
                out.extend(["-u", target])
        elif mode == "dns":
            if not has_d:
                out.extend(["-d", target])
        
        return out
    
    async def run(self, inp: "ToolInput", timeout_sec: Optional[float] = None): # type: ignore[override]
        """ORIGINAL METHOD - PRESERVED EXACTLY with enhanced error handling"""
        # Override run to: 1) Validate/parse args via base 2) Extract and validate mode 3) Inject -u/-d with inp.target if not provided 4) Execute as: gobuster
        
        # ORIGINAL: Resolve availability
        resolved = self._resolve_command()
        if not resolved:
            error_context = ErrorContext(
                error_type=ToolErrorType.NOT_FOUND,
                message=f"Command not found: {self.command_name}",
                recovery_suggestion="Install the required tool or check PATH",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target,
                metadata={"command": self.command_name}
            )
            return self._create_error_output(error_context, inp.correlation_id)
        
        # ENHANCED: Validate gobuster-specific requirements
        validation_result = self._validate_gobuster_requirements(inp)
        if validation_result:
            return validation_result
        
        # ORIGINAL: Parse arguments and enforce mode
        try:
            tokens = self._split_tokens(inp.extra_args or "")
            mode, rest = self._extract_mode_and_args(tokens)
            
            # ENHANCED: Additional mode validation
            if not self._is_mode_valid_for_target(mode, inp.target):
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Invalid target '{inp.target}' for mode '{mode}'",
                    recovery_suggestion=f"For {mode} mode, use appropriate target format",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=inp.target
                )
                return self._create_error_output(error_context, inp.correlation_id)
            
            # ORIGINAL: Enforce allowed flags on the remaining tokens (already done in base _parse_args),
            # but ensure we didn't accidentally include a second mode.
            for t in rest:
                if not t.startswith("-") and t in self.allowed_modes:
                    error_context = ErrorContext(
                        error_type=ToolErrorType.VALIDATION_ERROR,
                        message=f"Multiple modes specified: {mode}, {t}",
                        recovery_suggestion="Specify only one mode",
                        timestamp=self._get_timestamp(),
                        tool_name=self.tool_name,
                        target=inp.target
                    )
                    return self._create_error_output(error_context, inp.correlation_id)
            
            # ORIGINAL: Ensure proper target argument
            final_args = self._ensure_target_arg(mode, rest, inp.target)
            
            # ENHANCED: Add gobuster-specific optimizations
            optimized_args = self._optimize_gobuster_args(mode, final_args)
            
            # Build command: gobuster <mode> <args>
            cmd = [resolved] + [mode] + optimized_args
            
            # ORIGINAL: Execute with timeout
            timeout = float(timeout_sec or self.default_timeout_sec)
            return await self._spawn(cmd, timeout)
            
        except ValueError as e:
            # ENHANCED: Better error handling
            error_context = ErrorContext(
                error_type=ToolErrorType.VALIDATION_ERROR,
                message=f"Argument validation failed: {str(e)}",
                recovery_suggestion="Check arguments and try again",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target
            )
            return self._create_error_output(error_context, inp.correlation_id)
    
    # ==================== ENHANCED METHODS - ADDITIONAL FUNCTIONALITY ====================
    
    def _validate_gobuster_requirements(self, inp: ToolInput) -> Optional[ToolOutput]:
        """Validate gobuster-specific requirements (ENHANCED FEATURE)."""
        # Check if extra_args contains a mode
        if not (inp.extra_args and inp.extra_args.strip()):
            error_context = ErrorContext(
                error_type=ToolErrorType.VALIDATION_ERROR,
                message="Gobuster requires a mode: dir, dns, or vhost",
                recovery_suggestion="Specify a mode as the first argument",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target
            )
            return self._create_error_output(error_context, inp.correlation_id)
        
        return None
    
    def _is_mode_valid_for_target(self, mode: str, target: str) -> bool:
        """Check if the target is valid for the specified mode (ENHANCED FEATURE)."""
        if mode == "dns":
            # DNS mode should have a domain name, not URL
            return not target.startswith(("http://", "https://"))
        elif mode in ("dir", "vhost"):
            # dir/vhost modes should have URLs
            return target.startswith(("http://", "https://"))
        
        return True
    
    def _optimize_gobuster_args(self, mode: str, args: List[str]) -> List[str]:
        """Optimize gobuster arguments for performance and safety (ENHANCED FEATURE)."""
        optimized = list(args)
        
        # Mode-specific optimizations
        if mode == "dir":
            # Add default thread count if not specified
            has_threads = any(arg in ("-t", "--threads") for arg in args)
            if not has_threads:
                optimized.extend(["-t", "50"])  # Default to 50 threads
            
            # Add status codes if not specified
            has_status_codes = any(arg in ("-s", "--status-codes") for arg in args)
            if not has_status_codes:
                optimized.extend(["-s", "200,204,301,302,307,401,403"])  # Common status codes
        
        elif mode == "dns":
            # Add default thread count if not specified
            has_threads = any(arg in ("-t", "--threads") for arg in args)
            if not has_threads:
                optimized.extend(["-t", "100"])  # DNS can handle more threads
            
            # Enable wildcard detection if not specified
            has_wildcard = any(arg == "--wildcard" for arg in args)
            if not has_wildcard:
                optimized.append("--wildcard")
        
        elif mode == "vhost":
            # Add default thread count if not specified
            has_threads = any(arg in ("-t", "--threads") for arg in args)
            if not has_threads:
                optimized.extend(["-t", "30"])  # Vhost scanning is slower, use fewer threads
        
        return optimized
    
    def _get_timestamp(self):
        """Get current timestamp (ENHANCED HELPER)."""
        return datetime.now()
    
    def get_tool_info(self) -> dict:
        """Get enhanced tool information (ENHANCED FEATURE)."""
        base_info = {
            "name": self.tool_name,
            "command": self.command_name,
            "description": self.__doc__,
            "concurrency": self.concurrency,
            "timeout": self.default_timeout_sec,
            "allowed_modes": list(self.allowed_modes),
            "allowed_flags": list(self.allowed_flags) if self.allowed_flags else [],
            "circuit_breaker": {
                "failure_threshold": self.circuit_breaker_failure_threshold,
                "recovery_timeout": self.circuit_breaker_recovery_timeout
            },
            "mode_optimizations": {
                "dir": {
                    "default_threads": 50,
                    "default_status_codes": "200,204,301,302,307,401,403"
                },
                "dns": {
                    "default_threads": 100,
                    "wildcard_detection": True
                },
                "vhost": {
                    "default_threads": 30
                }
            }
        }
        
        # Add metrics if available
        if hasattr(self, 'metrics') and self.metrics:
            base_info["metrics"] = {
                "prometheus_available": True,
                "execution_metrics": f"mcp_tool_execution_total{{tool=\"{self.tool_name}\"}}"
            }
        
        return base_info
```
