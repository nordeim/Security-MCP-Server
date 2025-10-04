"""
Enhanced Gobuster tool with circuit breaker, metrics, and mode-specific optimizations.
Production-ready implementation with comprehensive safety features and security fixes.
"""
import logging
import shlex
import os
import ipaddress
from typing import List, Sequence, Tuple, Optional, Dict, Any, Union
from datetime import datetime, timezone
import re
from urllib.parse import urlparse

from mcp_server.base_tool import MCPBaseTool, ToolInput, ToolOutput, ToolErrorType, ErrorContext
from mcp_server.config import get_config

log = logging.getLogger(__name__)


class GobusterTool(MCPBaseTool):
    """
    Enhanced Gobuster content/dns/vhost discovery tool with comprehensive security.
    
    Features:
    - Mode-specific validation and optimization
    - Circuit breaker protection
    - Wordlist safety validation with size checks
    - Thread count optimization
    - URL and domain validation with private network enforcement
    - Performance monitoring
    - Intrusive operation control
    
    Gobuster modes:
    - dir: Directory/file enumeration via HTTP/HTTPS
    - dns: DNS subdomain enumeration
    - vhost: Virtual host enumeration
    
    Safety considerations:
    - Target validation ensures RFC1918 or *.lab.internal
    - Conservative thread defaults to prevent overwhelming targets
    - Wordlist size checks to prevent resource exhaustion
    - Non-flag tokens blocked for security
    """
    
    command_name: str = "gobuster"
    
    # Allowed modes for gobuster (exact match only)
    ALLOWED_MODES: Tuple[str, ...] = ("dir", "dns", "vhost")
    
    # Conservative allowed flags for safety
    allowed_flags: Sequence[str] = (
        # Common flags
        "-w", "--wordlist",            # Wordlist specification (required)
        "-t", "--threads",             # Thread count control
        "-q", "--quiet",               # Quiet mode
        "-k", "--no-tls-validation",   # Skip TLS validation
        "-o", "--output",              # Output file
        "-s", "--status-codes",        # Status codes (dir mode)
        "-x", "--extensions",          # File extensions (dir mode)
        "--timeout",                   # HTTP timeout
        "--no-color",                  # Disable color output
        "-H", "--header",              # Custom headers
        "-r", "--follow-redirect",     # Follow redirects
        "-n", "--no-status",           # Don't print status codes
        "-z", "--no-progress",         # Don't display progress
        "--delay",                     # Delay between requests
        # Mode-specific flags
        "-u", "--url",                 # URL (dir, vhost modes)
        "-d", "--domain",              # Domain (dns mode)
        "--wildcard",                  # Wildcard detection (dns)
        "--append-domain",             # Append domain (vhost)
        "-c", "--cookies",             # Cookies (dir)
        "-a", "--useragent",           # User agent
        "-P", "--password",            # Basic auth password
        "-U", "--username",            # Basic auth username
        "--proxy",                     # Proxy URL
        "--retry",                     # Retry on timeout
        "--retry-attempts",            # Number of retry attempts
    )
    
    # Base class integration metadata
    _EXTRA_ALLOWED_TOKENS = {"dir", "dns", "vhost"}
    _FLAGS_REQUIRE_VALUE = {
        "-w", "--wordlist",
        "-t", "--threads",
        "--timeout",
        "-u", "--url",
        "-d", "--domain",
        "-s", "--status-codes",
        "-x", "--extensions",
        "-o", "--output",
        "-H", "--header",
        "-c", "--cookies",
        "-a", "--useragent",
        "-P", "--password",
        "-U", "--username",
        "--proxy",
        "--retry",
        "--retry-attempts",
        "--delay"
    }

    # Gobuster-specific settings
    default_timeout_sec: float = 1200.0  # 20 minutes for large wordlists
    concurrency: int = 1  # Single instance to prevent overwhelming targets
    
    # Circuit breaker configuration
    circuit_breaker_failure_threshold: int = 4
    circuit_breaker_recovery_timeout: float = 180.0
    circuit_breaker_expected_exception: tuple = (Exception,)
    
    # Safety limits
    MAX_THREADS = {
        "dir": 30,      # HTTP can handle moderate threading
        "dns": 50,      # DNS queries are lighter
        "vhost": 20     # Virtual host scanning needs to be careful
    }
    DEFAULT_THREADS = {
        "dir": 10,      # Conservative default for HTTP
        "dns": 20,      # Moderate for DNS
        "vhost": 10     # Conservative for vhost
    }
    MAX_WORDLIST_SIZE = 1000000  # Maximum wordlist entries
    MAX_WORDLIST_BYTES = 50 * 1024 * 1024  # 50MB max file size
    
    def __init__(self):
        """Initialize Gobuster tool with enhanced features."""
        super().__init__()
        self.config = get_config()
        self._apply_config()
        self.allow_intrusive = False
    
    def _apply_config(self):
        """Apply configuration settings safely."""
        try:
            # Apply circuit breaker config
            if hasattr(self.config, 'circuit_breaker') and self.config.circuit_breaker:
                cb = self.config.circuit_breaker
                if hasattr(cb, 'failure_threshold'):
                    self.circuit_breaker_failure_threshold = max(1, min(10, int(cb.failure_threshold)))
                if hasattr(cb, 'recovery_timeout'):
                    self.circuit_breaker_recovery_timeout = max(30.0, min(600.0, float(cb.recovery_timeout)))
            
            # Apply tool config
            if hasattr(self.config, 'tool') and self.config.tool:
                tool = self.config.tool
                if hasattr(tool, 'default_timeout'):
                    self.default_timeout_sec = max(60.0, min(3600.0, float(tool.default_timeout)))
            
            # Apply security config
            if hasattr(self.config, 'security') and self.config.security:
                sec = self.config.security
                if hasattr(sec, 'allow_intrusive'):
                    self.allow_intrusive = bool(sec.allow_intrusive)
            
            log.debug("gobuster.config_applied intrusive=%s", self.allow_intrusive)
            
        except Exception as e:
            log.warning("gobuster.config_apply_failed error=%s using_safe_defaults", str(e))
            # Reset to safe defaults on error
            self.circuit_breaker_failure_threshold = 4
            self.circuit_breaker_recovery_timeout = 180.0
            self.default_timeout_sec = 1200.0
            self.allow_intrusive = False
    
    async def run(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
        """Execute Gobuster with enhanced validation and optimization."""
        # Validate command availability
        resolved = self._resolve_command()
        if not resolved:
            error_context = ErrorContext(
                error_type=ToolErrorType.NOT_FOUND,
                message=f"Command not found: {self.command_name}",
                recovery_suggestion="Install gobuster or check PATH",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target,
                metadata={"command": self.command_name}
            )
            return self._create_error_output(error_context, inp.correlation_id or "")
        
        # Validate gobuster-specific requirements
        validation_result = self._validate_gobuster_requirements(inp)
        if validation_result:
            return validation_result
        
        try:
            # Parse arguments and extract mode
            parsed_tokens = self._parse_and_validate_args(inp.extra_args or "", inp)
            if isinstance(parsed_tokens, ToolOutput):
                return parsed_tokens

            tokens = parsed_tokens
            mode, remaining_args = self._extract_mode_and_args(tokens)
            
            # Validate mode compatibility with target
            mode_validation = self._validate_mode_target_compatibility(mode, inp.target)
            if mode_validation:
                return mode_validation
            
            # Ensure proper target argument
            final_args = self._ensure_target_argument(mode, remaining_args, inp.target)
            
            # Validate and optimize arguments
            validated_args = self._validate_mode_args(mode, final_args)
            optimized_args = self._optimize_mode_args(mode, validated_args)
            
            # Build final command
            cmd = [resolved, mode] + optimized_args
            
            # Execute with timeout
            timeout = float(timeout_sec or inp.timeout_sec or self.default_timeout_sec)
            
            log.info("gobuster.executing mode=%s target=%s timeout=%.1f",
                    mode, inp.target, timeout)
            
            return await self._spawn(cmd, timeout)
            
        except ValueError as e:
            error_context = ErrorContext(
                error_type=ToolErrorType.VALIDATION_ERROR,
                message=str(e),
                recovery_suggestion="Check gobuster mode and arguments",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target,
                metadata={"error": str(e)}
            )
            return self._create_error_output(error_context, inp.correlation_id or "")
    
    def _validate_gobuster_requirements(self, inp: ToolInput) -> Optional[ToolOutput]:
        """Validate gobuster-specific requirements."""
        if not inp.extra_args or not inp.extra_args.strip():
            error_context = ErrorContext(
                error_type=ToolErrorType.VALIDATION_ERROR,
                message="Gobuster requires a mode: dir, dns, or vhost",
                recovery_suggestion="Specify mode as first argument (e.g., 'dir -w wordlist.txt')",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target,
                metadata={"available_modes": list(self.ALLOWED_MODES)}
            )
            return self._create_error_output(error_context, inp.correlation_id or "")
        
        return None
    
    def _parse_and_validate_args(self, extra_args: str, inp: ToolInput) -> Union[List[str], ToolOutput]:
        """Parse arguments via base sanitizer and surface friendly errors."""
        try:
            tokens = list(super()._parse_args(extra_args))
        except ValueError as e:
            error_context = ErrorContext(
                error_type=ToolErrorType.VALIDATION_ERROR,
                message=str(e),
                recovery_suggestion="Review gobuster flags and values",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target,
                metadata={"error": str(e)}
            )
            return self._create_error_output(error_context, inp.correlation_id or "")

        return tokens
    
    def _extract_mode_and_args(self, tokens: List[str]) -> Tuple[str, List[str]]:
        """Extract gobuster mode with exact matching."""
        mode = None
        remaining = []
        
        for i, token in enumerate(tokens):
            # First non-flag token should be the mode
            if not token.startswith("-"):
                if token in self.ALLOWED_MODES:
                    mode = token
                    remaining = tokens[:i] + tokens[i + 1:]
                    break
                else:
                    raise ValueError(f"Invalid gobuster mode: {token}. Allowed: {', '.join(self.ALLOWED_MODES)}")
            else:
                remaining.append(token)
        
        if mode is None:
            raise ValueError("Gobuster requires a mode: dir, dns, or vhost")
        
        return mode, remaining
    
    def _validate_mode_target_compatibility(self, mode: str, target: str) -> Optional[ToolOutput]:
        """Validate target is appropriate for mode with enhanced checks."""
        if mode in ("dir", "vhost"):
            # These modes need URLs
            if not target.startswith(("http://", "https://")):
                fixed_target = f"http://{target}"
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Mode '{mode}' requires URL target",
                    recovery_suggestion=f"Use URL format (e.g., {fixed_target})",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                    metadata={"mode": mode, "suggested": fixed_target}
                )
                return self._create_error_output(error_context, "")
            
            # Validate URL and check host is private
            try:
                parsed = urlparse(target)
                if not parsed.netloc:
                    raise ValueError("Invalid URL")
                
                # Extract host from netloc (remove port if present)
                host = parsed.netloc.split(':')[0]
                
                # Validate host is private or lab.internal
                if not self._is_private_or_lab_host(host):
                    error_context = ErrorContext(
                        error_type=ToolErrorType.VALIDATION_ERROR,
                        message=f"URL host must be private IP or .lab.internal: {host}",
                        recovery_suggestion="Use RFC1918 IPs or .lab.internal hostnames",
                        timestamp=self._get_timestamp(),
                        tool_name=self.tool_name,
                        target=target,
                        metadata={"mode": mode, "host": host}
                    )
                    return self._create_error_output(error_context, "")
                    
            except Exception as e:
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Invalid URL format: {target}",
                    recovery_suggestion="Use valid URL (e.g., http://192.168.1.1)",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                    metadata={"mode": mode, "error": str(e)}
                )
                return self._create_error_output(error_context, "")
        
        elif mode == "dns":
            # DNS mode needs domain names, not URLs
            if target.startswith(("http://", "https://")):
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Mode 'dns' requires domain target, not URL",
                    recovery_suggestion="Use domain format (e.g., lab.internal)",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                    metadata={"mode": mode}
                )
                return self._create_error_output(error_context, "")
            
            # Validate domain is .lab.internal
            if not target.endswith(".lab.internal"):
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"DNS mode requires .lab.internal domain: {target}",
                    recovery_suggestion="Use domains ending with .lab.internal",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                    metadata={"mode": mode}
                )
                return self._create_error_output(error_context, "")
        
        return None
    
    def _is_private_or_lab_host(self, host: str) -> bool:
        """Check if host is private IP or lab.internal domain."""
        # Check if it's a .lab.internal hostname
        if host.endswith(".lab.internal"):
            return True
        
        # Try to parse as IP
        try:
            ip = ipaddress.ip_address(host)
            return ip.is_private or ip.is_loopback
        except ValueError:
            # Not an IP, and not .lab.internal
            return False
    
    def _ensure_target_argument(self, mode: str, args: List[str], target: str) -> List[str]:
        """Ensure the proper target argument is present."""
        result = list(args)
        
        has_url = any(a in ("-u", "--url") for a in args)
        has_domain = any(a in ("-d", "--domain") for a in args)
        
        if mode in ("dir", "vhost"):
            if not has_url:
                result.extend(["-u", target])
        elif mode == "dns":
            if not has_domain:
                result.extend(["-d", target])
        
        return result
    
    def _validate_mode_args(self, mode: str, args: List[str]) -> List[str]:
        """Validate mode-specific arguments with enhanced checks."""
        validated = []
        i = 0
        
        while i < len(args):
            arg = args[i]
            
            # Check thread count
            if arg in ("-t", "--threads"):
                if i + 1 < len(args):
                    try:
                        threads = int(args[i + 1])
                        max_threads = self.MAX_THREADS.get(mode, 50)
                        if threads > max_threads:
                            log.warning("gobuster.threads_reduced mode=%s requested=%d max=%d",
                                       mode, threads, max_threads)
                            threads = max_threads
                        elif threads < 1:
                            threads = 1
                        validated.extend([arg, str(threads)])
                        i += 2
                    except ValueError:
                        raise ValueError(f"Invalid thread count: {args[i + 1]}")
                else:
                    raise ValueError(f"{arg} requires a value")
            
            # Check wordlist with size validation
            elif arg in ("-w", "--wordlist"):
                if i + 1 < len(args):
                    wordlist = args[i + 1]
                    # Validate wordlist path and size
                    wordlist_validation = self._validate_wordlist(wordlist)
                    if wordlist_validation:
                        raise ValueError(wordlist_validation)
                    validated.extend([arg, wordlist])
                    i += 2
                else:
                    raise ValueError(f"{arg} requires a value")
            
            # Check extensions (dir mode specific)
            elif arg in ("-x", "--extensions"):
                if i + 1 < len(args):
                    if mode != "dir":
                        log.warning("gobuster.extensions_ignored mode=%s", mode)
                        i += 2
                        continue
                    
                    extensions = args[i + 1]
                    # Validate extensions format
                    if not re.match(r'^[a-zA-Z0-9,]+$', extensions):
                        raise ValueError(f"Invalid extensions format: {extensions}")
                    
                    # Limit to reasonable set if intrusive not allowed
                    if not self.allow_intrusive:
                        allowed_exts = ['html', 'htm', 'php', 'asp', 'aspx', 'txt', 'xml', 'json']
                        provided_exts = extensions.split(',')
                        filtered_exts = [e for e in provided_exts if e in allowed_exts]
                        if filtered_exts != provided_exts:
                            log.warning("gobuster.extensions_filtered original=%s filtered=%s",
                                       extensions, ','.join(filtered_exts))
                            extensions = ','.join(filtered_exts) if filtered_exts else 'html,php,txt'
                    
                    validated.extend([arg, extensions])
                    i += 2
                else:
                    raise ValueError(f"{arg} requires a value")
            
            else:
                # Pass through other validated args
                validated.append(arg)
                # If this flag expects a value, include it
                if i + 1 < len(args) and not args[i + 1].startswith("-"):
                    validated.append(args[i + 1])
                    i += 2
                else:
                    i += 1
        
        return validated
    
    def _validate_wordlist(self, wordlist_path: str) -> Optional[str]:
        """Validate wordlist path and size."""
        # Basic path validation
        if not wordlist_path or ".." in wordlist_path:
            return f"Invalid wordlist path: {wordlist_path}"
        
        # Check if path is absolute or relative
        if not os.path.isabs(wordlist_path):
            # For relative paths, could check common locations
            common_paths = [
                wordlist_path,
                f"/usr/share/wordlists/{wordlist_path}",
                f"/opt/wordlists/{wordlist_path}",
            ]
            found = False
            for path in common_paths:
                if os.path.exists(path):
                    wordlist_path = path
                    found = True
                    break
            
            if not found:
                return f"Wordlist not found: {wordlist_path}"
        
        # Check file exists and size
        try:
            if os.path.exists(wordlist_path):
                file_size = os.path.getsize(wordlist_path)
                if file_size > self.MAX_WORDLIST_BYTES:
                    return f"Wordlist too large: {file_size} bytes (max: {self.MAX_WORDLIST_BYTES})"
                
                # Try to count lines (quick check)
                with open(wordlist_path, 'r', encoding='utf-8', errors='ignore') as f:
                    line_count = sum(1 for _ in f)
                    if line_count > self.MAX_WORDLIST_SIZE:
                        return f"Wordlist has too many entries: {line_count} (max: {self.MAX_WORDLIST_SIZE})"
            else:
                # File doesn't exist, but gobuster will handle this
                log.warning("gobuster.wordlist_not_found path=%s", wordlist_path)
        except Exception as e:
            log.warning("gobuster.wordlist_validation_error path=%s error=%s", wordlist_path, str(e))
        
        return None
    
    def _optimize_mode_args(self, mode: str, args: List[str]) -> List[str]:
        """Apply mode-specific optimizations."""
        optimized = list(args)
        
        # Check what's already specified
        has_threads = any(a in ("-t", "--threads") for a in args)
        has_wordlist = any(a in ("-w", "--wordlist") for a in args)
        has_timeout = any(a == "--timeout" for a in args)
        
        # Add thread defaults if not specified
        if not has_threads:
            default_threads = self.DEFAULT_THREADS.get(mode, 10)
            optimized.extend(["-t", str(default_threads)])
            log.info("gobuster.threads_set mode=%s threads=%d", mode, default_threads)
        
        # Add timeout if not specified
        if not has_timeout:
            optimized.extend(["--timeout", "10s"])
        
        # Mode-specific optimizations
        if mode == "dir":
            has_status = any(a in ("-s", "--status-codes") for a in args)
            if not has_status:
                # Common successful status codes
                optimized.extend(["-s", "200,204,301,302,307,401,403"])
        
        elif mode == "dns":
            has_wildcard = any(a == "--wildcard" for a in args)
            if not has_wildcard:
                optimized.append("--wildcard")
        
        elif mode == "vhost":
            # Vhost mode benefits from append-domain
            has_append = any(a == "--append-domain" for a in args)
            if not has_append:
                optimized.append("--append-domain")
        
        # Add quiet mode for cleaner output
        if "-q" not in args and "--quiet" not in args:
            optimized.append("-q")
        
        # Add no-progress for better logging
        if "-z" not in args and "--no-progress" not in args:
            optimized.append("-z")
        
        return optimized
    
    def _get_timestamp(self) -> datetime:
        """Get current timestamp with timezone."""
        return datetime.now(timezone.utc)
    
    def get_tool_info(self) -> Dict[str, Any]:
        """Get comprehensive tool information."""
        return {
            "name": self.tool_name,
            "command": self.command_name,
            "description": self.__doc__ or "Gobuster enumeration tool",
            "concurrency": self.concurrency,
            "timeout": self.default_timeout_sec,
            "allowed_modes": list(self.ALLOWED_MODES),
            "allowed_flags": list(self.allowed_flags),
            "intrusive_allowed": self.allow_intrusive,
            "circuit_breaker": {
                "enabled": self._circuit_breaker is not None,
                "failure_threshold": self.circuit_breaker_failure_threshold,
                "recovery_timeout": self.circuit_breaker_recovery_timeout,
                "state": self._circuit_breaker.state.name if self._circuit_breaker else "N/A"
            },
            "mode_settings": {
                mode: {
                    "default_threads": self.DEFAULT_THREADS[mode],
                    "max_threads": self.MAX_THREADS[mode],
                    "target_format": "URL" if mode in ("dir", "vhost") else "domain"
                }
                for mode in self.ALLOWED_MODES
            },
            "safety_limits": {
                "max_wordlist_size": self.MAX_WORDLIST_SIZE,
                "max_wordlist_bytes": self.MAX_WORDLIST_BYTES,
                "timeout_per_request": "10s",
                "private_targets_only": True
            },
            "metrics": {
                "available": self.metrics is not None,
                "prometheus": f'mcp_tool_execution_total{{tool="{self.tool_name}"}}' if self.metrics else None
            }
        }
