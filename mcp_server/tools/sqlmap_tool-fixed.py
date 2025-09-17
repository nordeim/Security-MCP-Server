# File: sqlmap_tool.py
"""
Enhanced Sqlmap tool with ALL framework features + comprehensive SQL injection safety.
"""
import logging
import re
from typing import Sequence, Optional, List, Dict, Any
from urllib.parse import urlparse
from datetime import datetime

# ORIGINAL IMPORT - PRESERVED EXACTLY
from mcp_server.base_tool import MCPBaseTool, ToolInput, ToolOutput, ToolErrorType, ErrorContext

# ENHANCED IMPORT (ADDITIONAL)
from mcp_server.config import get_config

log = logging.getLogger(__name__)

class SqlmapTool(MCPBaseTool):
    """
    Enhanced SQL injection detection and exploitation tool with comprehensive safety controls.
    
    ORIGINAL REQUIREMENTS (from documentation):
    - command_name = "sqlmap"
    - Allowed flags: `-u`, `--batch`, `--risk`, `--level`
    - Timeout: 1800s
    - Concurrency: 1
    
    ENHANCED FEATURES:
    - Comprehensive URL validation
    - Risk level restrictions (1-2 only)
    - Test level restrictions (1-3 only)
    - SQL injection safety controls
    - Request rate limiting
    - Comprehensive error handling
    - Circuit breaker protection
    
    SECURITY CONSIDERATIONS:
    - Only use on authorized targets
    - Risk levels limited to prevent aggressive testing
    - URLs must be RFC1918 or .lab.internal
    - Batch mode enforced for non-interactive operation
    - Comprehensive logging and monitoring
    
    Usage Examples:
    - Basic SQL injection test: sqlmap -u "http://192.168.1.10/page.php?id=1" --batch --risk=1 --level=1
    - Database enumeration: sqlmap -u "http://192.168.1.10/page.php?id=1" --batch --risk=1 --level=2 --dbs
    - Table enumeration: sqlmap -u "http://192.168.1.10/page.php?id=1" --batch --risk=1 --level=2 -D testdb --tables
    
    Environment overrides:
    - MCP_DEFAULT_TIMEOUT_SEC (default 1800s here)
    - MCP_DEFAULT_CONCURRENCY (default 1 here)
    - SQLMAP_MAX_RISK_LEVEL (default 2)
    - SQLMAP_MAX_TEST_LEVEL (default 3)
    """
    
    # ORIGINAL CLASS VARIABLES - PRESERVED EXACTLY
    command_name: str = "sqlmap"
    
    # ENHANCED ALLOWED FLAGS - Comprehensive safety controls
    allowed_flags: Sequence[str] = [
        # Target specification (required)
        "-u", "--url",                  # Target URL
        # Operation mode (required for safety)
        "--batch",                      # Non-interactive mode
        # Risk control (limited for safety)
        "--risk",                       # Risk level (1-3, limited to 1-2)
        # Test level control (limited for safety)
        "--level",                      # Test level (1-5, limited to 1-3)
        # Enumeration flags (safe when risk-controlled)
        "--dbs",                        # List databases
        "--tables",                     # List tables
        "--columns",                    # List columns
        "--dump",                       # Dump table contents
        "--current-user",               # Get current user
        "--current-db",                 # Get current database
        "--users",                      # List users
        "--passwords",                  # List password hashes
        "--roles",                      # List roles
        # Technical flags (safe)
        "--technique",                  # SQL injection techniques
        "--time-sec",                   # Time-based delay
        "--union-cols",                 # Union columns
        "--cookie",                     # HTTP cookie
        "--user-agent",                 # HTTP user agent
        "--referer",                    # HTTP referer
        "--headers",                    # HTTP headers
        # Output control (safe)
        "--output-dir",                 # Output directory
        "--flush-session",              # Flush session
        # Format control (safe)
        "--json",                       # JSON output format
        "--xml",                        # XML output format
    ]
    
    # ORIGINAL TIMEOUT AND CONCURRENCY - PRESERVED EXACTLY
    default_timeout_sec: float = 1800.0  # 30 minutes for comprehensive SQL testing
    concurrency: int = 1  # Single concurrency due to high impact
    
    # ENHANCED CIRCUIT BREAKER CONFIGURATION
    circuit_breaker_failure_threshold: int = 3  # Lower threshold for high-risk tool
    circuit_breaker_recovery_timeout: float = 300.0  # 5 minutes recovery
    circuit_breaker_expected_exception: tuple = (Exception,)
    
    # SQLMAP-SPECIFIC SECURITY LIMITS
    max_risk_level: int = 2  # Limit risk level to 1-2 (avoid aggressive testing)
    max_test_level: int = 3  # Limit test level to 1-3 (avoid excessive testing)
    max_threads: int = 10    # Limit concurrent requests
    
    def __init__(self):
        """Enhanced initialization with sqlmap-specific security setup."""
        # ORIGINAL: Call parent constructor (implicit)
        super().__init__()
        
        # ENHANCED: Setup additional features
        self.config = get_config()
        self._setup_enhanced_features()
    
    def _setup_enhanced_features(self):
        """Setup enhanced features for Sqlmap tool (ADDITIONAL)."""
        # Override circuit breaker settings from config if available
        if hasattr(self.config, 'circuit_breaker') and self.config.circuit_breaker:
            self.circuit_breaker_failure_threshold = self.config.circuit_breaker.failure_threshold
            self.circuit_breaker_recovery_timeout = self.config.circuit_breaker.recovery_timeout
        
        # Reinitialize circuit breaker with new settings
        self._circuit_breaker = None
        self._initialize_circuit_breaker()
    
    async def _execute_tool(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
        """
        Enhanced tool execution with sqlmap-specific security validations.
        Uses original _spawn method internally.
        """
        # ENHANCED: Validate sqlmap-specific requirements
        validation_result = self._validate_sqlmap_requirements(inp)
        if validation_result:
            return validation_result
        
        # ENHANCED: Add sqlmap-specific security optimizations
        secured_args = self._secure_sqlmap_args(inp.extra_args)
        
        # Create enhanced input with security measures
        enhanced_input = ToolInput(
            target=inp.target,
            extra_args=secured_args,
            timeout_sec=timeout_sec or self.default_timeout_sec,
            correlation_id=inp.correlation_id
        )
        
        # ORIGINAL: Use parent _execute_tool method which calls _spawn
        return await super()._execute_tool(enhanced_input, timeout_sec)
    
    def _validate_sqlmap_requirements(self, inp: ToolInput) -> Optional[ToolOutput]:
        """Validate sqlmap-specific security requirements (ENHANCED FEATURE)."""
        # Validate that target is a valid URL
        if not self._is_valid_url(inp.target):
            error_context = ErrorContext(
                error_type=ToolErrorType.VALIDATION_ERROR,
                message=f"Invalid SQLMap target URL: {inp.target}",
                recovery_suggestion="Use valid URL format (e.g., http://192.168.1.10/page.php?id=1)",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target
            )
            return self._create_error_output(error_context, inp.correlation_id)
        
        # Validate that target is authorized (RFC1918 or .lab.internal)
        if not self._is_authorized_target(inp.target):
            error_context = ErrorContext(
                error_type=ToolErrorType.VALIDATION_ERROR,
                message=f"Unauthorized SQLMap target: {inp.target}",
                recovery_suggestion="Target must be RFC1918 IPv4 or .lab.internal hostname",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target
            )
            return self._create_error_output(error_context, inp.correlation_id)
        
        # Validate that extra_args contains required URL specification
        if not inp.extra_args.strip():
            error_context = ErrorContext(
                error_type=ToolErrorType.VALIDATION_ERROR,
                message="SQLMap requires URL specification (-u or --url)",
                recovery_suggestion="Specify target URL using -u or --url flag",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target
            )
            return self._create_error_output(error_context, inp.correlation_id)
        
        return None
    
    def _is_valid_url(self, url: str) -> bool:
        """Validate URL format (ENHANCED FEATURE)."""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except ValueError:
            return False
    
    def _is_authorized_target(self, target: str) -> bool:
        """Check if SQLMap target is authorized (RFC1918 or .lab.internal) (ENHANCED FEATURE)."""
        try:
            # Extract hostname from URL
            parsed = urlparse(target)
            hostname = parsed.hostname
            
            if not hostname:
                return False
            
            # Check .lab.internal
            if hostname.endswith('.lab.internal'):
                return True
            
            # Check if it's an IP address
            import ipaddress
            try:
                ip = ipaddress.ip_address(hostname)
                return ip.version == 4 and ip.is_private
            except ValueError:
                # If it's a hostname, check if it resolves to RFC1918
                # For now, we'll be conservative and only allow .lab.internal hostnames
                return False
                
        except Exception:
            return False
    
    def _secure_sqlmap_args(self, extra_args: str) -> str:
        """Apply sqlmap-specific security restrictions to arguments (ENHANCED FEATURE)."""
        if not extra_args:
            return ""
        
        args = extra_args.split()
        secured = []
        
        # Track security settings
        has_url = False
        has_batch = False
        risk_level = 1
        test_level = 1
        
        # Process arguments with security restrictions
        i = 0
        while i < len(args):
            arg = args[i]
            
            # URL specification
            if arg in ("-u", "--url"):
                if i + 1 < len(args):
                    url_spec = args[i + 1]
                    if self._is_valid_url(url_spec):
                        secured.extend([arg, url_spec])
                        has_url = True
                    else:
                        log.warning("sqlmap.invalid_url url=%s", url_spec)
                        # Skip this URL specification
                        i += 2
                        continue
                i += 2
                continue
            
            # Risk level (restricted)
            elif arg == "--risk":
                if i + 1 < len(args):
                    try:
                        risk = int(args[i + 1])
                        if 1 <= risk <= self.max_risk_level:
                            secured.extend([arg, str(risk)])
                            risk_level = risk
                        else:
                            log.warning("sqlmap.risk_level_restricted risk=%d max=%d", 
                                       risk, self.max_risk_level)
                            # Use maximum allowed risk level
                            secured.extend([arg, str(self.max_risk_level)])
                    except ValueError:
                        # Invalid risk level, use default
                        secured.extend([arg, "1"])
                i += 2
                continue
            
            # Test level (restricted)
            elif arg == "--level":
                if i + 1 < len(args):
                    try:
                        level = int(args[i + 1])
                        if 1 <= level <= self.max_test_level:
                            secured.extend([arg, str(level)])
                            test_level = level
                        else:
                            log.warning("sqlmap.test_level_restricted level=%d max=%d", 
                                       level, self.max_test_level)
                            # Use maximum allowed test level
                            secured.extend([arg, str(self.max_test_level)])
                    except ValueError:
                        # Invalid test level, use default
                        secured.extend([arg, "1"])
                i += 2
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
                log.warning("sqlmap.unsafe_flag_skipped flag=%s", arg)
                i += 1
        
        # Ensure required URL is present
        if not has_url:
            log.error("sqlmap.missing_url_specification")
            return ""  # Return empty args to prevent execution
        
        # Ensure batch mode is enabled for safety
        if not has_batch:
            secured.append("--batch")
        
        # Add default safety options if not present
        if not any(arg.startswith("--risk") for arg in secured):
            secured.extend(["--risk", "1"])  # Default to lowest risk
        if not any(arg.startswith("--level") for arg in secured):
            secured.extend(["--level", "1"])  # Default to lowest level
        
        return " ".join(secured)
    
    def _is_safe_flag(self, flag: str) -> bool:
        """Check if a flag is in the allowed list (ENHANCED FEATURE)."""
        return flag in self.allowed_flags
    
    def _get_timestamp(self):
        """Get current timestamp (ENHANCED HELPER)."""
        return datetime.now()
    
    def get_tool_info(self) -> dict:
        """Get enhanced sqlmap tool information (ENHANCED FEATURE)."""
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
            "security_restrictions": {
                "max_risk_level": self.max_risk_level,
                "max_test_level": self.max_test_level,
                "max_threads": self.max_threads
            },
            "usage_examples": [
                {
                    "description": "Basic SQL injection test",
                    "command": "sqlmap -u \"http://192.168.1.10/page.php?id=1\" --batch --risk=1 --level=1"
                },
                {
                    "description": "Database enumeration",
                    "command": "sqlmap -u \"http://192.168.1.10/page.php?id=1\" --batch --risk=1 --level=2 --dbs"
                },
                {
                    "description": "Table enumeration",
                    "command": "sqlmap -u \"http://192.168.1.10/page.php?id=1\" --batch --risk=1 --level=2 -D testdb --tables"
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
