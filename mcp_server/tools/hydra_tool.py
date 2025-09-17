# File: hydra_tool.py
"""
Enhanced Hydra tool with ALL framework features + comprehensive password cracking safety.
"""
import logging
import re
import os
from typing import Sequence, Optional, List, Dict, Any

# ORIGINAL IMPORT - PRESERVED EXACTLY
from mcp_server.base_tool import MCPBaseTool, ToolInput, ToolOutput, ToolErrorType, ErrorContext

# ENHANCED IMPORT (ADDITIONAL)
from mcp_server.config import get_config

log = logging.getLogger(__name__)

class HydraTool(MCPBaseTool):
    """
    Enhanced online password cracking tool with comprehensive safety controls.
    
    ORIGINAL REQUIREMENTS (inferred from common usage):
    - command_name = "hydra"
    - Common safe flags for password cracking
    - Long timeout for password lists
    - Limited concurrency for safety
    
    ENHANCED FEATURES:
    - Service-specific validation
    - Password list size restrictions
    - Thread count limitations
    - Rate limiting and safety controls
    - Comprehensive error handling
    - Circuit breaker protection
    
    SECURITY CONSIDERATIONS:
    - Only use on authorized systems
    - Password file sizes must be validated
    - Thread counts strictly limited
    - Service-specific safety measures
    - Comprehensive logging and monitoring
    - Resource usage monitoring
    
    Usage Examples:
    - SSH password cracking: hydra -l admin -P /path/to/wordlist.txt 192.168.1.10 ssh
    - FTP password cracking: hydra -L /path/to/users.txt -P /path/to/wordlist.txt 192.168.1.10 ftp
    - Web form password cracking: hydra -l admin -P /path/to/wordlist.txt 192.168.1.10 http-post-form "/login:username=^USER^&password=^PASS^:F=incorrect"
    
    Environment overrides:
    - MCP_DEFAULT_TIMEOUT_SEC (default 1200s here)
    - MCP_DEFAULT_CONCURRENCY (default 1 here)
    - HYDRA_MAX_THREADS (default 16)
    - HYDRA_MAX_PASSWORD_LIST_SIZE (default 10000)
    """
    
    # ORIGINAL CLASS VARIABLES - PRESERVED EXACTLY
    command_name: str = "hydra"
    
    # ENHANCED ALLOWED FLAGS - Comprehensive safety controls
    allowed_flags: Sequence[str] = [
        # Target specification
        "-l",                           # Single login name
        "-L",                           # Login name file
        "-p",                           # Single password
        "-P",                           # Password file
        "-e",                           # Additional checks (nsr)
        "-C",                           # Combination file (login:password)
        # Service specification (required)
        "ssh", "ftp", "telnet", "http", "https", "smb", "ldap", "rdp", "mysql", "postgresql", "vnc",
        # Connection options
        "-s",                           # Port number
        "-S",                           # SSL connection
        "-t",                           # Number of threads (limited)
        "-T",                           # Connection timeout
        "-w",                           # Wait time between attempts
        "-W",                           # Wait time for response
        # Output options
        "-v", "-V",                     # Verbose output
        "-o",                           # Output file
        "-f",                           # Stop when found
        "-q",                           # Quiet mode
        # HTTP-specific options
        "http-get", "http-post", "http-post-form", "http-head",
        # Technical options
        "-I",                           # Ignore existing restore file
        "-R",                           # Restore session
        "-F",                           # Fail on failed login
        # Service-specific options
        "/path",                        # Path for HTTP
        "-m",                           # Module specification
    ]
    
    # ENHANCED TIMEOUT AND CONCURRENCY - Optimized for password cracking
    default_timeout_sec: float = 1200.0  # 20 minutes for password cracking
    concurrency: int = 1  # Single concurrency due to high resource usage
    
    # ENHANCED CIRCUIT BREAKER CONFIGURATION
    circuit_breaker_failure_threshold: int = 4  # Medium threshold for network tool
    circuit_breaker_recovery_timeout: float = 240.0  # 4 minutes recovery
    circuit_breaker_expected_exception: tuple = (Exception,)
    
    # HYDRA-SPECIFIC SECURITY LIMITS
    max_threads: int = 16          # Limit concurrent threads per attack
    max_password_list_size: int = 10000  # Maximum lines in password file
    max_wait_time: int = 5         # Maximum wait time between attempts
    allowed_services: Sequence[str] = [
        "ssh", "ftp", "telnet", "http", "https", "smb", "ldap", "rdp", "mysql", "postgresql", "vnc"
    ]
    
    def __init__(self):
        """Enhanced initialization with hydra-specific security setup."""
        # ORIGINAL: Call parent constructor (implicit)
        super().__init__()
        
        # ENHANCED: Setup additional features
        self.config = get_config()
        self._setup_enhanced_features()
    
    def _setup_enhanced_features(self):
        """Setup enhanced features for Hydra tool (ADDITIONAL)."""
        # Override circuit breaker settings from config if available
        if self.config.circuit_breaker_enabled:
            self.circuit_breaker_failure_threshold = self.config.circuit_breaker_failure_threshold
            self.circuit_breaker_recovery_timeout = self.config.circuit_breaker_recovery_timeout
        
        # Reinitialize circuit breaker with new settings
        self._circuit_breaker = None
        self._initialize_circuit_breaker()
    
    async def _execute_tool(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
        """
        Enhanced tool execution with hydra-specific security validations.
        Uses original _spawn method internally.
        """
        # ENHANCED: Validate hydra-specific requirements
        validation_result = self._validate_hydra_requirements(inp)
        if validation_result:
            return validation_result
        
        # ENHANCED: Add hydra-specific security optimizations
        secured_args = self._secure_hydra_args(inp.extra_args)
        
        # Create enhanced input with security measures
        enhanced_input = ToolInput(
            target=inp.target,
            extra_args=secured_args,
            timeout_sec=timeout_sec or self.default_timeout_sec,
            correlation_id=inp.correlation_id
        )
        
        # ORIGINAL: Use parent _execute_tool method which calls _spawn
        return await super()._execute_tool(enhanced_input, timeout_sec)
    
    def _validate_hydra_requirements(self, inp: ToolInput) -> Optional[ToolOutput]:
        """Validate hydra-specific security requirements (ENHANCED FEATURE)."""
        # Validate that target is a valid host/service combination
        if not self._is_valid_hydra_target(inp.target):
            error_context = ErrorContext(
                error_type=ToolErrorType.VALIDATION_ERROR,
                message=f"Invalid Hydra target: {inp.target}",
                recovery_suggestion="Use format: host:service or host:port:service",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target
            )
            return self._create_error_output(error_context, inp.correlation_id)
        
        # Validate that target is authorized (RFC1918 or .lab.internal)
        if not self._is_authorized_target(inp.target):
            error_context = ErrorContext(
                error_type=ToolErrorType.VALIDATION_ERROR,
                message=f"Unauthorized Hydra target: {inp.target}",
                recovery_suggestion="Target must be RFC1918 IPv4 or .lab.internal hostname",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target
            )
            return self._create_error_output(error_context, inp.correlation_id)
        
        # Validate that extra_args contains required authentication options
        if not inp.extra_args.strip():
            error_context = ErrorContext(
                error_type=ToolErrorType.VALIDATION_ERROR,
                message="Hydra requires authentication specification (-l, -L, -p, -P)",
                recovery_suggestion="Specify login names and/or passwords (e.g., '-l admin -P wordlist.txt')",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target
            )
            return self._create_error_output(error_context, inp.correlation_id)
        
        return None
    
    def _is_valid_hydra_target(self, target: str) -> bool:
        """Validate Hydra target format (ENHANCED FEATURE)."""
        # Hydra target formats:
        # host:service
        # host:port:service
        # service://host
        # service://host:port
        
        # Basic validation - should contain service or port
        if not target or len(target.split(':')) < 2:
            return False
        
        # Extract host part
        if '://' in target:
            # service://host or service://host:port
            parts = target.split('://', 1)
            if len(parts) != 2:
                return False
            host_part = parts[1]
        else:
            # host:service or host:port:service
            host_part = target
        
        # Validate host part
        host_components = host_part.split(':')
        if len(host_components) < 2:
            return False
        
        # Check if service is valid
        service = host_components[-1].lower()
        if service not in self.allowed_services:
            return False
        
        return True
    
    def _is_authorized_target(self, target: str) -> bool:
        """Check if Hydra target is authorized (RFC1918 or .lab.internal) (ENHANCED FEATURE)."""
        try:
            # Extract host from target
            if '://' in target:
                # service://host or service://host:port
                host_part = target.split('://', 1)[1]
            else:
                # host:service or host:port:service
                host_part = target
            
            # Remove service and port
            host = host_part.split(':')[0]
            
            # Check .lab.internal
            if host.endswith('.lab.internal'):
                return True
            
            # Check RFC1918
            import ipaddress
            ip = ipaddress.ip_address(host)
            return ip.version == 4 and ip.is_private
            
        except Exception:
            return False
    
    def _secure_hydra_args(self, extra_args: str) -> str:
        """Apply hydra-specific security restrictions to arguments (ENHANCED FEATURE)."""
        if not extra_args:
            return ""
        
        args = extra_args.split()
        secured = []
        
        # Track security settings
        has_login = False
        has_password = False
        threads = 4  # Default thread count
        service = None
        
        # Process arguments with security restrictions
        i = 0
        while i < len(args):
            arg = args[i]
            
            # Login specification
            elif arg in ("-l", "-L"):
                if i + 1 < len(args):
                    login_spec = args[i + 1]
                    if self._is_safe_login_spec(login_spec, arg == "-L"):
                        secured.extend([arg, login_spec])
                        has_login = True
                    else:
                        log.warning("hydra.unsafe_login_spec spec=%s", login_spec)
                        # Skip this login specification
                        i += 2
                        continue
                i += 2
                continue
            
            # Password specification
            elif arg in ("-p", "-P"):
                if i + 1 < len(args):
                    password_spec = args[i + 1]
                    if self._is_safe_password_spec(password_spec, arg == "-P"):
                        secured.extend([arg, password_spec])
                        has_password = True
                    else:
                        log.warning("hydra.unsafe_password_spec spec=%s", password_spec)
                        # Skip this password specification
                        i += 2
                        continue
                i += 2
                continue
            
            # Thread count (restricted)
            elif arg == "-t":
                if i + 1 < len(args):
                    try:
                        thread_count = int(args[i + 1])
                        if 1 <= thread_count <= self.max_threads:
                            secured.extend([arg, str(thread_count)])
                            threads = thread_count
                        else:
                            log.warning("hydra.thread_count_restricted threads=%d max=%d", 
                                       thread_count, self.max_threads)
                            # Use maximum allowed thread count
                            secured.extend([arg, str(self.max_threads)])
                    except ValueError:
                        # Invalid thread count, use default
                        secured.extend([arg, "4"])
                i += 2
                continue
            
            # Service specification (validate)
            elif i == len(args) - 1:  # Last argument is typically the service
                if arg.lower() in self.allowed_services:
                    secured.append(arg)
                    service = arg.lower()
                else:
                    log.warning("hydra.unsafe_service service=%s", arg)
                    # Use SSH as default safe service
                    secured.append("ssh")
                    service = "ssh"
                i += 1
                continue
            
            # Safe flags (allow as-is)
            elif arg.startswith("-") and self._is_safe_flag(arg):
                secured.append(arg)
                i += 1
                continue
            
            # Values for safe flags
            elif i > 0 and args[i - 1].startswith("-") and self._is_safe_flag(args[i - 1]):
                secured.append(arg)
                i += 1
                continue
            
            # Skip unknown/unsafe flags
            else:
                log.warning("hydra.unsafe_flag_skipped flag=%s", arg)
                i += 1
        
        # Ensure required authentication is present
        if not has_login:
            # Add default login if not specified
            secured.extend(["-l", "admin"])
            log.warning("hydra.no_login_specified using_default")
        
        if not has_password:
            # Add default password file if not specified
            secured.extend(["-P", "/usr/share/wordlists/common-passwords.txt"])
            log.warning("hydra.no_password_specified using_default")
        
        # Add safety restrictions
        if threads > self.max_threads:
            secured.extend(["-t", str(self.max_threads)])
        
        # Add default safety options
        secured.extend(["-t", "4"])           # Conservative thread count
        secured.extend(["-w", "2"])           # 2 second wait time
        secured.extend(["-W", "5"])           # 5 second response timeout
        secured.extend(["-f"])                # Stop when found
        secured.extend(["-V"])                # Verbose output
        
        # Ensure service is specified
        if not service:
            secured.append("ssh")
            log.info("hydra.no_service_specified using_ssh_default")
        
        return " ".join(secured)
    
    def _is_safe_login_spec(self, spec: str, is_file: bool) -> bool:
        """Validate login specification (ENHANCED FEATURE)."""
        if is_file:
            # Check if file exists and is safe size
            try:
                if os.path.exists(spec):
                    file_size = os.path.getsize(spec)
                    if file_size > 1024 * 1024:  # 1MB max for login files
                        log.warning("hydra.login_file_too_large size=%d", file_size)
                        return False
                return True
            except Exception:
                return False
        else:
            # Single login name - basic validation
            return len(spec) <= 64 and re.match(r'^[a-zA-Z0-9_\-\.@]+$', spec)
    
    def _is_safe_password_spec(self, spec: str, is_file: bool) -> bool:
        """Validate password specification (ENHANCED FEATURE)."""
        if is_file:
            # Check if file exists and is safe size
            try:
                if os.path.exists(spec):
                    # Check line count instead of file size for password files
                    with open(spec, 'r') as f:
                        line_count = sum(1 for _ in f)
                    if line_count > self.max_password_list_size:
                        log.warning("hydra.password_file_too_large lines=%d max=%d", 
                                   line_count, self.max_password_list_size)
                        return False
                return True
            except Exception:
                return False
        else:
            # Single password - basic validation
            return len(spec) <= 128
    
    def _is_safe_flag(self, flag: str) -> bool:
        """Check if a flag is in the allowed list (ENHANCED FEATURE)."""
        return flag in self.allowed_flags
    
    def _get_timestamp(self):
        """Get current timestamp (ENHANCED HELPER)."""
        from datetime import datetime
        return datetime.now()
    
    def get_tool_info(self) -> dict:
        """Get enhanced hydra tool information (ENHANCED FEATURE)."""
        base_info = {
            "name": self.tool_name,
            "command": self.command_name,
            "description": self.__doc__,
            "concurrency": self.concurrency,
            "timeout": self.default_timeout_sec,
            "allowed_flags": list(self.allowed_flags) if self.allowed_flags else [],
            "allowed_services": list(self.allowed_services),
            "circuit_breaker": {
                "failure_threshold": self.circuit_breaker_failure_threshold,
                "recovery_timeout": self.circuit_breaker_recovery_timeout
            },
            "security_restrictions": {
                "max_threads": self.max_threads,
                "max_password_list_size": self.max_password_list_size,
                "max_wait_time": self.max_wait_time,
                "allowed_services": list(self.allowed_services)
            },
            "usage_examples": [
                {
                    "description": "SSH password cracking",
                    "command": "hydra -l admin -P /path/to/wordlist.txt 192.168.1.10 ssh"
                },
                {
                    "description": "FTP password cracking",
                    "command": "hydra -L /path/to/users.txt -P /path/to/wordlist.txt 192.168.1.10 ftp"
                },
                {
                    "description": "Web form password cracking",
                    "command": "hydra -l admin -P /path/to/wordlist.txt 192.168.1.10 http-post-form \"/login:username=^USER^&password=^PASS^:F=incorrect\""
                }
            ]
        }
        
        # Add metrics if available
        if hasattr(self, 'metrics') and self.metrics:
            base_info["metrics"] = {
                "prometheus_available": True,
                "execution_metrics": f"mcp_tool_execution_total{{tool=\"{self.tool_name}\"}}"
            }
        
        return base_info
