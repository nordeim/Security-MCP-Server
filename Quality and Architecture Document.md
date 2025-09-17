Plan to conduct a meticulous line-by-line code review of the MCP server files, followed by a code quality assessment report and a Project Architecture Document. Let us approach this systematically with a critical QA engineer mindset.

# 1. Meticulous Line-by-Line Code Review

## 1.1 mcp_server/base_tool.py

### Imports and Dependencies
```python
import asyncio
import logging
import os
import re
import shlex
import shutil
import time
import contextlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Optional, Sequence, Dict, Any
from datetime import datetime, timedelta
```
**Observation**: All necessary imports are present and well-organized. No issues found.

### Pydantic Compatibility Shim
```python
# Pydantic v1/v2 compatibility shim
try: # Pydantic v2
    from pydantic import BaseModel, field_validator
    _PD_V2 = True
except ImportError: # Pydantic v1
    from pydantic import BaseModel, validator as field_validator # type: ignore
    _PD_V2 = False
```
**Observation**: Good compatibility shim for handling both Pydantic v1 and v2. The type ignore comment is appropriate for the compatibility layer.

### Metrics and Circuit Breaker Imports
```python
# Metrics integration with graceful handling
try:
    from prometheus_client import Counter, Histogram, Gauge, Info
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# Circuit breaker implementation with fallback import
try:
    from .circuit_breaker import CircuitBreaker, CircuitBreakerState
except ImportError:
    from circuit_breaker import CircuitBreaker, CircuitBreakerState

# Tool metrics with fallback import
try:
    from .metrics import ToolMetrics
except ImportError:
    from metrics import ToolMetrics
```
**Observation**: Good graceful handling of optional dependencies. The fallback imports allow the code to work even when these dependencies are not available.

### Constants and Configuration
```python
log = logging.getLogger(__name__)

# Conservative denylist for arg tokens we never want to see (even though shell=False)
_DENY_CHARS = re.compile(r"[;&|`$><\n\r]") # control/meta chars
_TOKEN_ALLOWED = re.compile(r"^[A-Za-z0-9.:/=+-,@%]+$") # reasonably safe superset
_MAX_ARGS_LEN = int(os.getenv("MCP_MAX_ARGS_LEN", "2048"))
_MAX_STDOUT_BYTES = int(os.getenv("MCP_MAX_STDOUT_BYTES", "1048576")) # 1 MiB
_MAX_STDERR_BYTES = int(os.getenv("MCP_MAX_STDERR_BYTES", "262144")) # 256 KiB
_DEFAULT_TIMEOUT_SEC = float(os.getenv("MCP_DEFAULT_TIMEOUT_SEC", "300")) # 5 minutes
_DEFAULT_CONCURRENCY = int(os.getenv("MCP_DEFAULT_CONCURRENCY", "2"))
```
**Observation**: 
- Good use of environment variables for configuration with sensible defaults.
- The regex patterns for input validation are well-defined.
- **Potential Issue**: The `_DENY_CHARS` regex includes backslashes which need to be escaped in raw strings. However, in this case, it's correctly escaped as `\\n` and `\\r`, so no issue.

### Private Network Validation Function
```python
def _is_private_or_lab(value: str) -> bool:
    """
    Accept:
    - RFC1918 IPv4 address (10/8, 172.16/12, 192.168/16)
    - RFC1918 IPv4 network in CIDR form
    - Hostname ending with .lab.internal
    """
    import ipaddress
    v = value.strip()
    # Hostname allowance
    if v.endswith(".lab.internal"):
        return True
    # IP or CIDR
    try:
        if "/" in v:
            net = ipaddress.ip_network(v, strict=False)
            return net.version == 4 and net.is_private
        else:
            ip = ipaddress.ip_address(v)
            return ip.version == 4 and ip.is_private
    except ValueError:
        return False
```
**Observation**: 
- Good validation function for private networks and lab hostnames.
- **Potential Issue**: The function imports `ipaddress` inside the function. While this works, it's more conventional to put imports at the top of the file. However, this might be intentional to avoid importing if the function is never called.
- **Security Consideration**: The function correctly handles both IP addresses and CIDR notation, and properly restricts to IPv4 private networks.

### Error Type Enum
```python
class ToolErrorType(Enum):
    """Enhanced error taxonomy with recovery suggestions."""
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"
    VALIDATION_ERROR = "validation_error"
    EXECUTION_ERROR = "execution_error"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"
    UNKNOWN = "unknown"
```
**Observation**: Well-defined error types with clear naming. No issues found.

### Error Context Dataclass
```python
@dataclass
class ErrorContext:
    """Context for enhanced error reporting."""
    error_type: ToolErrorType
    message: str
    recovery_suggestion: str
    timestamp: datetime
    tool_name: str
    target: str
    metadata: Dict[str, Any]
```
**Observation**: Well-structured error context with all necessary information. No issues found.

### Tool Input Model
```python
class ToolInput(BaseModel):
    """Enhanced ToolInput with additional validation."""
    target: str
    extra_args: str = ""
    timeout_sec: Optional[float] = None
    correlation_id: Optional[str] = None
    
    # v1/v2 compatible field validator
    if _PD_V2:
        @field_validator("target")
        @classmethod
        def _validate_target(cls, v: str) -> str:
            if not _is_private_or_lab(v):
                raise ValueError("Target must be RFC1918 IPv4 or a .lab.internal hostname (CIDR allowed).")
            return v
        
        @field_validator("extra_args")
        @classmethod
        def _validate_extra_args(cls, v: str) -> str:
            v = v or ""
            if len(v) > _MAX_ARGS_LEN:
                raise ValueError(f"extra_args too long (> {_MAX_ARGS_LEN} bytes)")
            if _DENY_CHARS.search(v):
                raise ValueError("extra_args contains forbidden metacharacters")
            return v
    else:
        @field_validator("target")
        def _validate_target(cls, v: str) -> str: # type: ignore
            if not _is_private_or_lab(v):
                raise ValueError("Target must be RFC1918 IPv4 or a .lab.internal hostname (CIDR allowed).")
            return v
        
        @field_validator("extra_args")
        def _validate_extra_args(cls, v: str) -> str: # type: ignore
            v = v or ""
            if len(v) > _MAX_ARGS_LEN:
                raise ValueError(f"extra_args too long (> {_MAX_ARGS_LEN} bytes)")
            if _DENY_CHARS.search(v):
                raise ValueError("extra_args contains forbidden metacharacters")
            return v
```
**Observation**:
- Good validation for both target and extra_args.
- Proper handling of Pydantic v1/v2 compatibility.
- **Potential Issue**: The validation for extra_args checks for forbidden characters but doesn't validate that the arguments are appropriate for the specific tool. This might be intentional to keep the base tool generic.

### Tool Output Model
```python
class ToolOutput(BaseModel):
    """Enhanced ToolOutput with additional metadata."""
    stdout: str
    stderr: str
    returncode: int
    truncated_stdout: bool = False
    truncated_stderr: bool = False
    timed_out: bool = False
    error: Optional[str] = None
    error_type: Optional[str] = None
    execution_time: Optional[float] = None
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = {}
```
**Observation**: Well-structured output model with all necessary fields. No issues found.

### MCP Base Tool Class
```python
class MCPBaseTool(ABC):
    """
    Enhanced base class for MCP tools with circuit breaker, metrics, and advanced features.
    """
    
    # Required: name of the binary to execute, e.g., "nmap"
    command_name: ClassVar[str]
    
    # Optional: a whitelist of flags (prefix match) to allow
    allowed_flags: ClassVar[Optional[Sequence[str]]] = None
    
    # Concurrency limit per tool instance
    concurrency: ClassVar[int] = _DEFAULT_CONCURRENCY
    
    # Default timeout for a run in seconds
    default_timeout_sec: ClassVar[float] = _DEFAULT_TIMEOUT_SEC
    
    # Circuit breaker configuration
    circuit_breaker_failure_threshold: ClassVar[int] = 5
    circuit_breaker_recovery_timeout: ClassVar[float] = 60.0
    circuit_breaker_expected_exception: ClassVar[tuple] = (Exception,)
    
    # Semaphore created on first use per subclass
    _semaphore: ClassVar[Optional[asyncio.Semaphore]] = None
    
    # Circuit breaker instance per tool
    _circuit_breaker: ClassVar[Optional[CircuitBreaker]] = None
```
**Observation**: Well-defined class variables with appropriate types and defaults. No issues found.

### Initialization Methods
```python
def __init__(self):
    self.tool_name = self.__class__.__name__
    self._initialize_metrics()
    self._initialize_circuit_breaker()

def _initialize_metrics(self):
    """Initialize Prometheus metrics for this tool."""
    if PROMETHEUS_AVAILABLE:
        try:
            self.metrics = ToolMetrics(self.tool_name)
        except Exception as e:
            log.warning("metrics.initialization_failed tool=%s error=%s", self.tool_name, str(e))
            self.metrics = None
    else:
        self.metrics = None

def _initialize_circuit_breaker(self):
    """Initialize circuit breaker for this tool."""
    if self.__class__._circuit_breaker is None:
        try:
            self.__class__._circuit_breaker = CircuitBreaker(
                failure_threshold=self.circuit_breaker_failure_threshold,
                recovery_timeout=self.circuit_breaker_recovery_timeout,
                expected_exception=self.circuit_breaker_expected_exception,
                name=self.tool_name
            )
        except Exception as e:
            log.error("circuit_breaker.initialization_failed tool=%s error=%s", self.tool_name, str(e))
            self.__class__._circuit_breaker = None
```
**Observation**:
- Good initialization of metrics and circuit breaker with proper error handling.
- **Potential Issue**: The circuit breaker is stored as a class variable, which means it's shared across all instances of the same tool class. This is appropriate for controlling access to the same resource, but it's worth noting that all instances share the same circuit breaker state.

### Semaphore Management
```python
def _ensure_semaphore(self) -> asyncio.Semaphore:
    """Ensure semaphore exists for this tool class."""
    if self.__class__._semaphore is None:
        self.__class__._semaphore = asyncio.Semaphore(self.concurrency)
    return self.__class__._semaphore
```
**Observation**:
- Good lazy initialization of semaphore with proper concurrency control.
- **Potential Issue**: Similar to the circuit breaker, the semaphore is stored as a class variable, which means it's shared across all instances of the same tool class. This is appropriate for controlling access to the same resource.

### Run Method
```python
async def run(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
    """
    Enhanced run method with circuit breaker, metrics, and error handling.
    """
    start_time = time.time()
    correlation_id = inp.correlation_id or str(int(start_time * 1000))
    
    try:
        # Check circuit breaker state
        if self._circuit_breaker and self._circuit_breaker.state == CircuitBreakerState.OPEN:
            error_context = ErrorContext(
                error_type=ToolErrorType.CIRCUIT_BREAKER_OPEN,
                message=f"Circuit breaker is open for {self.tool_name}",
                recovery_suggestion="Wait for recovery timeout or check service health",
                timestamp=datetime.now(),
                tool_name=self.tool_name,
                target=inp.target,
                metadata={"state": str(self._circuit_breaker.state)}
            )
            return self._create_error_output(error_context, correlation_id)
        
        # Acquire semaphore for concurrency control
        async with self._ensure_semaphore():
            # Execute with circuit breaker protection
            if self._circuit_breaker:
                try:
                    result = await self._circuit_breaker.call(
                        self._execute_tool,
                        inp,
                        timeout_sec
                    )
                except Exception as circuit_error:
                    # Handle circuit breaker specific errors
                    error_context = ErrorContext(
                        error_type=ToolErrorType.CIRCUIT_BREAKER_OPEN,
                        message=f"Circuit breaker error: {str(circuit_error)}",
                        recovery_suggestion="Wait for recovery timeout or check service health",
                        timestamp=datetime.now(),
                        tool_name=self.tool_name,
                        target=inp.target,
                        metadata={"circuit_error": str(circuit_error)}
                    )
                    return self._create_error_output(error_context, correlation_id)
            else:
                result = await self._execute_tool(inp, timeout_sec)
            
            # Record metrics with validation
            if self.metrics:
                execution_time = max(0.001, time.time() - start_time)  # Ensure minimum positive value
                try:
                    self.metrics.record_execution(
                        success=result.returncode == 0,
                        execution_time=execution_time,
                        timed_out=result.timed_out
                    )
                except Exception as e:
                    log.warning("metrics.recording_failed tool=%s error=%s", self.tool_name, str(e))
            
            # Add correlation ID and execution time
            result.correlation_id = correlation_id
            result.execution_time = max(0.001, time.time() - start_time)
            
            return result
            
    except Exception as e:
        execution_time = max(0.001, time.time() - start_time)
        error_context = ErrorContext(
            error_type=ToolErrorType.EXECUTION_ERROR,
            message=f"Tool execution failed: {str(e)}",
            recovery_suggestion="Check tool logs and system resources",
            timestamp=datetime.now(),
            tool_name=self.tool_name,
            target=inp.target,
            metadata={"exception": str(e), "execution_time": execution_time}
        )
        
        # Record failure metrics
        if self.metrics:
            try:
                self.metrics.record_execution(
                    success=False,
                    execution_time=execution_time,
                    error_type=ToolErrorType.EXECUTION_ERROR.value
                )
            except Exception as metrics_error:
                log.warning("metrics.failure_recording_failed tool=%s error=%s", 
                          self.tool_name, str(metrics_error))
        
        return self._create_error_output(error_context, correlation_id)
```
**Observation**:
- Comprehensive run method with proper error handling, circuit breaker protection, and metrics recording.
- Good use of correlation IDs for tracing.
- **Potential Issue**: The execution time is calculated twice - once for metrics recording and once for the result. This could lead to slightly different values. It would be more consistent to calculate it once and reuse it.
- **Potential Issue**: The minimum execution time is set to 0.001 seconds. While this prevents division by zero, it might skew metrics for very fast operations.

### Execute Tool Method
```python
async def _execute_tool(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
    """Execute the actual tool with enhanced error handling."""
    # Resolve command and build arguments
    resolved_cmd = self._resolve_command()
    if not resolved_cmd:
        error_context = ErrorContext(
            error_type=ToolErrorType.NOT_FOUND,
            message=f"Command not found: {self.command_name}",
            recovery_suggestion="Install the required tool or check PATH",
            timestamp=datetime.now(),
            tool_name=self.tool_name,
            target=inp.target,
            metadata={"command": self.command_name}
        )
        return self._create_error_output(error_context, inp.correlation_id)
    
    # Parse and validate arguments
    try:
        args = self._parse_args(inp.extra_args)
    except ValueError as e:
        error_context = ErrorContext(
            error_type=ToolErrorType.VALIDATION_ERROR,
            message=f"Argument validation failed: {str(e)}",
            recovery_suggestion="Check arguments and try again",
            timestamp=datetime.now(),
            tool_name=self.tool_name,
            target=inp.target,
            metadata={"validation_error": str(e)}
        )
        return self._create_error_output(error_context, inp.correlation_id)
    
    # Build command
    cmd = [resolved_cmd] + args + [inp.target]
    
    # Execute with timeout
    timeout = float(timeout_sec or self.default_timeout_sec)
    return await self._spawn(cmd, timeout)
```
**Observation**: Good error handling and validation. No issues found.

### Error Output Creation
```python
def _create_error_output(self, error_context: ErrorContext, correlation_id: str) -> ToolOutput:
    """Create a ToolOutput for error conditions."""
    log.error(
        "tool.error tool=%s error_type=%s target=%s message=%s correlation_id=%s",
        error_context.tool_name,
        error_context.error_type.value,
        error_context.target,
        error_context.message,
        correlation_id,
        extra={"error_context": error_context}
    )
    
    return ToolOutput(
        stdout="",
        stderr=error_context.message,
        returncode=1,
        error=error_context.message,
        error_type=error_context.error_type.value,
        correlation_id=correlation_id,
        metadata={
            "recovery_suggestion": error_context.recovery_suggestion,
            "timestamp": error_context.timestamp.isoformat()
        }
    )
```
**Observation**: Good error logging and creation of error output. No issues found.

### Command Resolution
```python
def _resolve_command(self) -> Optional[str]:
    """Resolve command path using shutil.which."""
    return shutil.which(self.command_name)
```
**Observation**: Simple and effective command resolution. No issues found.

### Argument Parsing
```python
def _parse_args(self, extra_args: str) -> Sequence[str]:
    """Parse and validate extra arguments."""
    if not extra_args:
        return []
    
    tokens = shlex.split(extra_args)
    safe: list[str] = []
    
    for t in tokens:
        if not t:  # skip empties
            continue
        if not _TOKEN_ALLOWED.match(t):
            raise ValueError(f"Disallowed token in args: {t!r}")
        safe.append(t)
    
    if self.allowed_flags is not None:
        # Approve flags by prefix match; non-flags (e.g., values) are allowed
        allowed = tuple(self.allowed_flags)
        for t in safe:
            if t.startswith("-") and not t.startswith(allowed):
                raise ValueError(f"Flag not allowed: {t!r}")
    
    return safe
```
**Observation**:
- Good argument parsing with proper validation.
- **Potential Issue**: The flag validation only checks if the flag starts with one of the allowed prefixes. This means that if `--verbose` is allowed, `--verbose-extra` would also be allowed, which might not be intended. However, this could be intentional behavior.

### Subprocess Execution
```python
async def _spawn(
    self,
    cmd: Sequence[str],
    timeout_sec: Optional[float] = None,
) -> ToolOutput:
    """Spawn and monitor a subprocess with timeout and output truncation."""
    timeout = float(timeout_sec or self.default_timeout_sec)
    
    # Minimal, sanitized environment
    env = {
        "PATH": os.getenv("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    
    try:
        log.info(
            "tool.start command=%s timeout=%.1f",
            " ".join(cmd),
            timeout,
        )
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            rc = proc.returncode
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            out, err, rc = b"", b"process timed out", 124
            return ToolOutput(
                stdout="",
                stderr="process timed out",
                returncode=rc,
                truncated_stdout=False,
                truncated_stderr=False,
                timed_out=True,
                error="timeout",
            )
        
        # Truncate outputs if necessary
        t_stdout = False
        t_stderr = False
        
        if len(out) > _MAX_STDOUT_BYTES:
            out = out[:_MAX_STDOUT_BYTES]
            t_stdout = True
        
        if len(err) > _MAX_STDERR_BYTES:
            err = err[:_MAX_STDERR_BYTES]
            t_stderr = True
        
        result = ToolOutput(
            stdout=out.decode(errors="replace"),
            stderr=err.decode(errors="replace"),
            returncode=rc,
            truncated_stdout=t_stdout,
            truncated_stderr=t_stderr,
            timed_out=False,
        )
        
        log.info(
            "tool.end command=%s returncode=%s truncated_stdout=%s truncated_stderr=%s",
            cmd[0],
            rc,
            t_stdout,
            t_stderr,
        )
        
        return result
        
    except FileNotFoundError:
        msg = f"Command not found: {cmd[0]}"
        log.error("tool.error %s", msg)
        return ToolOutput(stdout="", stderr=msg, returncode=127, error="not_found")
    
    except Exception as e:
        msg = f"execution failed: {e.__class__.__name__}: {e}"
        log.error("tool.error %s", msg)
        return ToolOutput(stdout="", stderr=msg, returncode=1, error="execution_failed")
```
**Observation**:
- Good subprocess execution with proper timeout handling and output truncation.
- **Potential Issue**: The timeout error returns a hardcoded stderr message "process timed out" but the stdout is empty. It might be more useful to include any partial output that was generated before the timeout.
- **Potential Issue**: The environment variables are hardcoded to a minimal set. While this is good for security, it might cause issues for tools that require specific environment variables to function correctly.

### ToolMetrics Class
```python
class ToolMetrics:
    """Metrics collection for tool execution."""
    
    def __init__(self, tool_name: str):
        self.tool_name = tool_name
        
        if PROMETHEUS_AVAILABLE:
            try:
                self.execution_counter = Counter(
                    f'mcp_tool_execution_total',
                    'Total tool executions',
                    ['tool', 'status', 'error_type']
                )
                self.execution_histogram = Histogram(
                    f'mcp_tool_execution_seconds',
                    'Tool execution time in seconds',
                    ['tool']
                )
                self.active_gauge = Gauge(
                    f'mcp_tool_active',
                    'Currently active tool executions',
                    ['tool']
                )
                self.error_counter = Counter(
                    f'mcp_tool_errors_total',
                    'Total tool errors',
                    ['tool', 'error_type']
                )
            except Exception as e:
                log.warning("prometheus.metrics_initialization_failed tool=%s error=%s", tool_name, str(e))
                # Disable metrics if initialization fails
                self.execution_counter = None
                self.execution_histogram = None
                self.active_gauge = None
                self.error_counter = None
        else:
            self.execution_counter = None
            self.execution_histogram = None
            self.active_gauge = None
            self.error_counter = None
    
    def record_execution(self, success: bool, execution_time: float, 
                        timed_out: bool = False, error_type: str = None):
        """Record tool execution metrics."""
        if not PROMETHEUS_AVAILABLE or not self.execution_counter:
            return
        
        try:
            # Validate execution time
            execution_time = max(0.0, float(execution_time))
            
            status = 'success' if success else 'failure'
            self.execution_counter.labels(
                tool=self.tool_name,
                status=status,
                error_type=error_type or 'none'
            ).inc()
            
            if self.execution_histogram:
                self.execution_histogram.labels(tool=self.tool_name).observe(execution_time)
            
            if not success and self.error_counter:
                self.error_counter.labels(
                    tool=self.tool_name,
                    error_type=error_type or 'unknown'
                ).inc()
        except Exception as e:
            log.warning("metrics.recording_error tool=%s error=%s", self.tool_name, str(e))
    
    def start_execution(self):
        """Record start of execution."""
        if PROMETHEUS_AVAILABLE and self.active_gauge:
            try:
                self.active_gauge.labels(tool=self.tool_name).inc()
            except Exception as e:
                log.warning("metrics.start_execution_error tool=%s error=%s", self.tool_name, str(e))
    
    def end_execution(self):
        """Record end of execution."""
        if PROMETHEUS_AVAILABLE and self.active_gauge:
            try:
                self.active_gauge.labels(tool=self.tool_name).dec()
            except Exception as e:
                log.warning("metrics.end_execution_error tool=%s error=%s", self.tool_name, str(e))
```
**Observation**:
- Good metrics collection with proper error handling.
- **Potential Issue**: The `start_execution` and `end_execution` methods are defined but never called in the code. This means the active gauge will never be updated.
- **Potential Issue**: The metrics names are hardcoded with an 'mcp_' prefix. This might cause conflicts if multiple MCP servers are running in the same environment. It would be better to make the prefix configurable.

## 1.2 mcp_server/config.py

### Imports and Dependencies
```python
import os
import logging
import json
import yaml
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
```
**Observation**: All necessary imports are present and well-organized. No issues found.

### Pydantic Compatibility Shim
```python
# Pydantic for configuration validation
try:
    from pydantic import BaseModel, Field, validator
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    # Fallback validation without Pydantic
    class BaseModel:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
        
        def dict(self):
            return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}
    
    Field = lambda default=None, **kwargs: default
    def validator(field_name, *args, **kwargs):
        def decorator(func):
            return func
        return decorator
```
**Observation**: Good compatibility shim for handling Pydantic availability. The fallback implementation provides basic functionality. No issues found.

### Configuration Dataclasses
```python
log = logging.getLogger(__name__)

@dataclass
class DatabaseConfig:
    """Database configuration."""
    url: str = ""
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 3600

@dataclass
class SecurityConfig:
    """Security configuration."""
    allowed_targets: List[str] = field(default_factory=lambda: ["RFC1918", ".lab.internal"])
    max_args_length: int = 2048
    max_output_size: int = 1048576
    timeout_seconds: int = 300
    concurrency_limit: int = 2

@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    expected_exceptions: List[str] = field(default_factory=lambda: ["Exception"])
    half_open_success_threshold: int = 1

@dataclass
class HealthConfig:
    """Health check configuration."""
    check_interval: float = 30.0
    cpu_threshold: float = 80.0
    memory_threshold: float = 80.0
    disk_threshold: float = 80.0
    dependencies: List[str] = field(default_factory=list)
    timeout: float = 10.0

@dataclass
class MetricsConfig:
    """Metrics configuration."""
    enabled: bool = True
    prometheus_enabled: bool = True
    prometheus_port: int = 9090
    collection_interval: float = 15.0

@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file_path: Optional[str] = None
    max_file_size: int = 10485760  # 10MB
    backup_count: int = 5

@dataclass
class ServerConfig:
    """Server configuration."""
    host: str = "0.0.0.0"
    port: int = 8080
    transport: str = "stdio"  # "stdio" or "http"
    workers: int = 1
    max_connections: int = 100
    shutdown_grace_period: float = 30.0

@dataclass
class ToolConfig:
    """Tool-specific configuration."""
    include_patterns: List[str] = field(default_factory=lambda: ["*"])
    exclude_patterns: List[str] = field(default_factory=list)
    default_timeout: int = 300
    default_concurrency: int = 2
```
**Observation**: Well-defined configuration dataclasses with appropriate defaults. No issues found.

### MCPConfig Class
```python
class MCPConfig:
    """
    Main MCP configuration class with validation and hot-reload support.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path
        self.last_modified = None
        self._config_data = {}
        
        # Initialize with defaults
        self.database = DatabaseConfig()
        self.security = SecurityConfig()
        self.circuit_breaker = CircuitBreakerConfig()
        self.health = HealthConfig()
        self.metrics = MetricsConfig()
        self.logging = LoggingConfig()
        self.server = ServerConfig()
        self.tool = ToolConfig()
        
        # Load configuration
        self.load_config()
```
**Observation**: Good initialization of configuration with defaults. No issues found.

### Configuration Loading Methods
```python
def load_config(self):
    """Load configuration from file and environment variables."""
    # Start with defaults
    config_data = self._get_defaults()
    
    # Load from file if specified
    if self.config_path and os.path.exists(self.config_path):
        config_data.update(self._load_from_file(self.config_path))
    
    # Override with environment variables
    config_data.update(self._load_from_environment())
    
    # Validate and set configuration
    self._validate_and_set_config(config_data)
    
    # Update last modified time
    if self.config_path:
        try:
            self.last_modified = os.path.getmtime(self.config_path)
        except OSError:
            self.last_modified = None

def _get_defaults(self) -> Dict[str, Any]:
    """Get default configuration values."""
    return {
        "database": asdict(DatabaseConfig()),
        "security": asdict(SecurityConfig()),
        "circuit_breaker": asdict(CircuitBreakerConfig()),
        "health": asdict(HealthConfig()),
        "metrics": asdict(MetricsConfig()),
        "logging": asdict(LoggingConfig()),
        "server": asdict(ServerConfig()),
        "tool": asdict(ToolConfig())
    }

def _load_from_file(self, config_path: str) -> Dict[str, Any]:
    """Load configuration from file (JSON or YAML)."""
    try:
        file_path = Path(config_path)
        
        if not file_path.exists():
            log.warning("config.file_not_found path=%s", config_path)
            return {}
        
        with open(file_path, 'r', encoding='utf-8') as f:
            if file_path.suffix.lower() in ['.yaml', '.yml']:
                return yaml.safe_load(f) or {}
            else:
                return json.load(f) or {}
    
    except Exception as e:
        log.error("config.file_load_failed path=%s error=%s", config_path, str(e))
        return {}
```
**Observation**: Good configuration loading with proper error handling. No issues found.

### Environment Variable Loading
```python
def _load_from_environment(self) -> Dict[str, Any]:
    """Load configuration from environment variables."""
    config = {}
    
    # Environment variable mappings
    env_mappings = {
        'MCP_DATABASE_URL': ('database', 'url'),
        'MCP_DATABASE_POOL_SIZE': ('database', 'pool_size'),
        'MCP_SECURITY_MAX_ARGS_LENGTH': ('security', 'max_args_length'),
        'MCP_SECURITY_TIMEOUT_SECONDS': ('security', 'timeout_seconds'),
        'MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD': ('circuit_breaker', 'failure_threshold'),
        'MCP_CIRCUIT_BREAKER_RECOVERY_TIMEOUT': ('circuit_breaker', 'recovery_timeout'),
        'MCP_HEALTH_CHECK_INTERVAL': ('health', 'check_interval'),
        'MCP_HEALTH_CPU_THRESHOLD': ('health', 'cpu_threshold'),
        'MCP_METRICS_ENABLED': ('metrics', 'enabled'),
        'MCP_METRICS_PROMETHEUS_PORT': ('metrics', 'prometheus_port'),
        'MCP_LOGGING_LEVEL': ('logging', 'level'),
        'MCP_LOGGING_FILE_PATH': ('logging', 'file_path'),
        'MCP_SERVER_HOST': ('server', 'host'),
        'MCP_SERVER_PORT': ('server', 'port'),
        'MCP_SERVER_TRANSPORT': ('server', 'transport'),
        'MCP_TOOL_DEFAULT_TIMEOUT': ('tool', 'default_timeout'),
    }
    
    for env_var, (section, key) in env_mappings.items():
        value = os.getenv(env_var)
        if value is not None:
            if section not in config:
                config[section] = {}
            
            # Type conversion
            if key in ['pool_size', 'max_args_length', 'timeout_seconds', 'failure_threshold', 
                      'prometheus_port', 'default_timeout']:
                try:
                    config[section][key] = int(value)
                except ValueError:
                    log.warning("config.invalid_int env_var=%s value=%s", env_var, value)
            elif key in ['recovery_timeout', 'check_interval', 'cpu_threshold']:
                try:
                    config[section][key] = float(value)
                except ValueError:
                    log.warning("config.invalid_float env_var=%s value=%s", env_var, value)
            elif key in ['enabled']:
                config[section][key] = value.lower() in ['true', '1', 'yes', 'on']
            else:
                config[section][key] = value
    
    return config
```
**Observation**: Good environment variable loading with proper type conversion. No issues found.

### Configuration Validation
```python
def _validate_and_set_config(self, config_data: Dict[str, Any]):
    """Validate and set configuration values."""
    try:
        # Validate database config
        if 'database' in config_data:
            db_config = config_data['database']
            self.database.url = str(db_config.get('url', self.database.url))
            self.database.pool_size = max(1, int(db_config.get('pool_size', self.database.pool_size)))
            self.database.max_overflow = max(0, int(db_config.get('max_overflow', self.database.max_overflow)))
        
        # Validate security config
        if 'security' in config_data:
            sec_config = config_data['security']
            self.security.max_args_length = max(1, int(sec_config.get('max_args_length', self.security.max_args_length)))
            self.security.max_output_size = max(1, int(sec_config.get('max_output_size', self.security.max_output_size)))
            self.security.timeout_seconds = max(1, int(sec_config.get('timeout_seconds', self.security.timeout_seconds)))
            self.security.concurrency_limit = max(1, int(sec_config.get('concurrency_limit', self.security.concurrency_limit)))
        
        # Validate circuit breaker config
        if 'circuit_breaker' in config_data:
            cb_config = config_data['circuit_breaker']
            self.circuit_breaker.failure_threshold = max(1, int(cb_config.get('failure_threshold', self.circuit_breaker.failure_threshold)))
            self.circuit_breaker.recovery_timeout = max(1.0, float(cb_config.get('recovery_timeout', self.circuit_breaker.recovery_timeout)))
        
        # Validate health config
        if 'health' in config_data:
            health_config = config_data['health']
            self.health.check_interval = max(5.0, float(health_config.get('check_interval', self.health.check_interval)))
            self.health.cpu_threshold = max(0.0, min(100.0, float(health_config.get('cpu_threshold', self.health.cpu_threshold))))
            self.health.memory_threshold = max(0.0, min(100.0, float(health_config.get('memory_threshold', self.health.memory_threshold))))
            self.health.disk_threshold = max(0.0, min(100.0, float(health_config.get('disk_threshold', self.health.disk_threshold))))
        
        # Validate metrics config
        if 'metrics' in config_data:
            metrics_config = config_data['metrics']
            self.metrics.enabled = bool(metrics_config.get('enabled', self.metrics.enabled))
            self.metrics.prometheus_enabled = bool(metrics_config.get('prometheus_enabled', self.metrics.prometheus_enabled))
            self.metrics.prometheus_port = max(1, min(65535, int(metrics_config.get('prometheus_port', self.metrics.prometheus_port))))
        
        # Validate logging config
        if 'logging' in config_data:
            logging_config = config_data['logging']
            self.logging.level = str(logging_config.get('level', self.logging.level)).upper()
            self.logging.file_path = logging_config.get('file_path') if logging_config.get('file_path') else None
        
        # Validate server config
        if 'server' in config_data:
            server_config = config_data['server']
            self.server.host = str(server_config.get('host', self.server.host))
            self.server.port = max(1, min(65535, int(server_config.get('port', self.server.port))))
            self.server.transport = str(server_config.get('transport', self.server.transport)).lower()
            self.server.workers = max(1, int(server_config.get('workers', self.server.workers)))
        
        # Validate tool config
        if 'tool' in config_data:
            tool_config = config_data['tool']
            self.tool.default_timeout = max(1, int(tool_config.get('default_timeout', self.tool.default_timeout)))
            self.tool.default_concurrency = max(1, int(tool_config.get('default_concurrency', self.tool.default_concurrency)))
        
        # Store raw config data
        self._config_data = config_data
        
        log.info("config.loaded_successfully")
        
    except Exception as e:
        log.error("config.validation_failed error=%s", str(e))
        # Keep defaults if validation fails
```
**Observation**: Good configuration validation with proper bounds checking. No issues found.

### Configuration Change Detection
```python
def check_for_changes(self) -> bool:
    """Check if configuration file has been modified."""
    if not self.config_path:
        return False
    
    try:
        current_mtime = os.path.getmtime(self.config_path)
        if current_mtime != self.last_modified:
            self.last_modified = current_mtime
            return True
    except OSError:
        pass
    
    return False

def reload_config(self):
    """Reload configuration if file has changed."""
    if self.check_for_changes():
        log.info("config.reloading_changes_detected")
        self.load_config()
        return True
    return False
```
**Observation**: Good configuration change detection and reload functionality. No issues found.

### Sensitive Data Handling
```python
def get_sensitive_keys(self) -> List[str]:
    """Get list of sensitive configuration keys that should be redacted."""
    return [
        'database.url',
        'security.api_key',
        'security.secret_key',
        'logging.file_path'  # May contain sensitive paths
    ]

def redact_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
    """Redact sensitive data from configuration for logging."""
    sensitive_keys = self.get_sensitive_keys()
    redacted_data = data.copy()
    
    for key in sensitive_keys:
        if '.' in key:
            section, subkey = key.split('.', 1)
            if section in redacted_data and isinstance(redacted_data[section], dict):
                if subkey in redacted_data[section]:
                    redacted_data[section][subkey] = "***REDACTED***"
        else:
            if key in redacted_data:
                redacted_data[key] = "***REDACTED***"
    
    return redacted_data
```
**Observation**: Good sensitive data handling with proper redaction. No issues found.

### Configuration Serialization
```python
def to_dict(self, redact_sensitive: bool = True) -> Dict[str, Any]:
    """Convert configuration to dictionary."""
    config_dict = {
        'database': asdict(self.database),
        'security': asdict(self.security),
        'circuit_breaker': asdict(self.circuit_breaker),
        'health': asdict(self.health),
        'metrics': asdict(self.metrics),
        'logging': asdict(self.logging),
        'server': asdict(self.server),
        'tool': asdict(self.tool)
    }
    
    if redact_sensitive:
        config_dict = self.redact_sensitive_data(config_dict)
    
    return config_dict

def save_config(self, file_path: Optional[str] = None):
    """Save current configuration to file."""
    save_path = file_path or self.config_path
    if not save_path:
        raise ValueError("No config file path specified")
    
    try:
        config_dict = self.to_dict(redact_sensitive=False)
        
        file_path_obj = Path(save_path)
        file_path_obj.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path_obj, 'w', encoding='utf-8') as f:
            if file_path_obj.suffix.lower() in ['.yaml', '.yml']:
                yaml.dump(config_dict, f, default_flow_style=False, indent=2)
            else:
                json.dump(config_dict, f, indent=2)
        
        log.info("config.saved_successfully path=%s", save_path)
        
    except Exception as e:
        log.error("config.save_failed path=%s error=%s", save_path, str(e))
        raise
```
**Observation**: Good configuration serialization with support for both JSON and YAML formats. No issues found.

### Configuration Access Methods
```python
def get_section(self, section_name: str) -> Any:
    """Get a specific configuration section."""
    return getattr(self, section_name, None)

def get_value(self, section_name: str, key: str, default=None):
    """Get a specific configuration value."""
    section = self.get_section(section_name)
    if section and hasattr(section, key):
        return getattr(section, key)
    return default

def __str__(self) -> str:
    """String representation with sensitive data redacted."""
    config_dict = self.to_dict(redact_sensitive=True)
    return json.dumps(config_dict, indent=2)
```
**Observation**: Good configuration access methods with proper defaults. No issues found.

### Global Configuration Instance
```python
# Global configuration instance
_config_instance = None

def get_config(config_path: Optional[str] = None) -> MCPConfig:
    """Get the global configuration instance."""
    global _config_instance
    if _config_instance is None:
        _config_instance = MCPConfig(config_path)
    return _config_instance

def reload_config():
    """Reload the global configuration."""
    global _config_instance
    if _config_instance is not None:
        _config_instance.reload_config()
```
**Observation**: Good global configuration instance management. No issues found.

## 1.3 mcp_server/metrics.py

### Imports and Dependencies
```python
import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field

# Graceful Prometheus dependency handling
try:
    from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest
    from prometheus_client.core import CollectorRegistry
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

log = logging.getLogger(__name__)
```
**Observation**: All necessary imports are present and well-organized. Good graceful handling of optional dependencies. No issues found.

### Tool Execution Metrics Dataclass
```python
@dataclass
class ToolExecutionMetrics:
    """Metrics for tool execution with validation."""
    tool_name: str
    execution_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0
    total_execution_time: float = 0.0
    min_execution_time: float = float('inf')
    max_execution_time: float = 0.0
    last_execution_time: Optional[datetime] = None
    
    def record_execution(self, success: bool, execution_time: float, timed_out: bool = False):
        """Record a tool execution with validation."""
        # Validate execution time
        execution_time = max(0.0, float(execution_time))
        
        self.execution_count += 1
        self.total_execution_time += execution_time
        
        if execution_time < self.min_execution_time:
            self.min_execution_time = execution_time
        if execution_time > self.max_execution_time:
            self.max_execution_time = execution_time
        
        self.last_execution_time = datetime.now()
        
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
        
        if timed_out:
            self.timeout_count += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for this tool."""
        if self.execution_count == 0:
            return {
                "tool_name": self.tool_name,
                "execution_count": 0,
                "success_rate": 0.0,
                "average_execution_time": 0.0,
                "min_execution_time": 0.0,
                "max_execution_time": 0.0
            }
        
        # Prevent division by zero
        avg_execution_time = self.total_execution_time / self.execution_count
        success_rate = (self.success_count / self.execution_count) * 100
        
        return {
            "tool_name": self.tool_name,
            "execution_count": self.execution_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "timeout_count": self.timeout_count,
            "success_rate": round(success_rate, 2),
            "average_execution_time": round(avg_execution_time, 4),
            "min_execution_time": round(self.min_execution_time, 4) if self.min_execution_time != float('inf') else 0.0,
            "max_execution_time": round(self.max_execution_time, 4),
            "last_execution_time": self.last_execution_time.isoformat() if self.last_execution_time else None
        }
```
**Observation**: Well-defined metrics dataclass with proper validation and statistics calculation. No issues found.

### System Metrics Class
```python
class SystemMetrics:
    """System-level metrics with thread safety."""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.request_count = 0
        self.error_count = 0
        self.active_connections = 0
        self._lock = None  # Could use threading.Lock if needed
    
    def increment_request_count(self):
        """Increment request count."""
        self.request_count += 1
    
    def increment_error_count(self):
        """Increment error count."""
        self.error_count += 1
    
    def increment_active_connections(self):
        """Increment active connections."""
        self.active_connections += 1
    
    def decrement_active_connections(self):
        """Decrement active connections."""
        self.active_connections = max(0, self.active_connections - 1)
    
    def get_uptime(self) -> float:
        """Get uptime in seconds."""
        return (datetime.now() - self.start_time).total_seconds()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get system statistics."""
        uptime = self.get_uptime()
        error_rate = (self.error_count / self.request_count * 100) if self.request_count > 0 else 0
        
        return {
            "uptime_seconds": uptime,
            "uptime_formatted": str(timedelta(seconds=int(uptime))),
            "request_count": self.request_count,
            "error_count": self.error_count,
            "error_rate": round(error_rate, 2),
            "active_connections": self.active_connections,
            "start_time": self.start_time.isoformat()
        }
```
**Observation**: Well-defined system metrics class with proper statistics calculation. No issues found.

### Prometheus Metrics Class
```python
class PrometheusMetrics:
    """Prometheus metrics collection with graceful degradation."""
    
    def __init__(self):
        if not PROMETHEUS_AVAILABLE:
            log.warning("prometheus.unavailable")
            self.registry = None
            return
        
        try:
            self.registry = CollectorRegistry()
            
            # Tool execution metrics
            self.tool_execution_counter = Counter(
                'mcp_tool_execution_total',
                'Total tool executions',
                ['tool', 'status', 'error_type'],
                registry=self.registry
            )
            
            self.tool_execution_histogram = Histogram(
                'mcp_tool_execution_seconds',
                'Tool execution time in seconds',
                ['tool'],
                registry=self.registry
            )
            
            self.tool_active_gauge = Gauge(
                'mcp_tool_active',
                'Currently active tool executions',
                ['tool'],
                registry=self.registry
            )
            
            # System metrics
            self.system_request_counter = Counter(
                'mcp_system_requests_total',
                'Total system requests',
                registry=self.registry
            )
            
            self.system_error_counter = Counter(
                'mcp_system_errors_total',
                'Total system errors',
                ['error_type'],
                registry=self.registry
            )
            
            self.system_active_connections = Gauge(
                'mcp_system_active_connections',
                'Currently active connections',
                registry=self.registry
            )
            
            self.system_uptime_gauge = Gauge(
                'mcp_system_uptime_seconds',
                'System uptime in seconds',
                registry=self.registry
            )
            
            log.info("prometheus.metrics_initialized")
            
        except Exception as e:
            log.error("prometheus.initialization_failed error=%s", str(e))
            self.registry = None
    
    def record_tool_execution(self, tool_name: str, success: bool, execution_time: float, 
                             error_type: str = None):
        """Record tool execution metrics."""
        if not PROMETHEUS_AVAILABLE or not self.registry:
            return
        
        try:
            # Validate execution time
            execution_time = max(0.0, float(execution_time))
            
            status = 'success' if success else 'failure'
            self.tool_execution_counter.labels(
                tool=tool_name,
                status=status,
                error_type=error_type or 'none'
            ).inc()
            
            self.tool_execution_histogram.labels(tool=tool_name).observe(execution_time)
            
        except Exception as e:
            log.warning("prometheus.tool_execution_error error=%s", str(e))
    
    def increment_tool_active(self, tool_name: str):
        """Increment active tool gauge."""
        if PROMETHEUS_AVAILABLE and self.registry and self.tool_active_gauge:
            try:
                self.tool_active_gauge.labels(tool=tool_name).inc()
            except Exception as e:
                log.warning("prometheus.increment_active_error error=%s", str(e))
    
    def decrement_tool_active(self, tool_name: str):
        """Decrement active tool gauge."""
        if PROMETHEUS_AVAILABLE and self.registry and self.tool_active_gauge:
            try:
                self.tool_active_gauge.labels(tool=tool_name).dec()
            except Exception as e:
                log.warning("prometheus.decrement_active_error error=%s", str(e))
    
    def increment_system_request(self):
        """Increment system request counter."""
        if PROMETHEUS_AVAILABLE and self.registry and self.system_request_counter:
            try:
                self.system_request_counter.inc()
            except Exception as e:
                log.warning("prometheus.increment_request_error error=%s", str(e))
    
    def increment_system_error(self, error_type: str = "unknown"):
        """Increment system error counter."""
        if PROMETHEUS_AVAILABLE and self.registry and self.system_error_counter:
            try:
                self.system_error_counter.labels(error_type=error_type).inc()
            except Exception as e:
                log.warning("prometheus.increment_error_error error=%s", str(e))
    
    def set_active_connections(self, count: int):
        """Set active connections gauge."""
        if PROMETHEUS_AVAILABLE and self.registry and self.system_active_connections:
            try:
                self.system_active_connections.set(count)
            except Exception as e:
                log.warning("prometheus.set_connections_error error=%s", str(e))
    
    def set_uptime(self, uptime: float):
        """Set uptime gauge."""
        if PROMETHEUS_AVAILABLE and self.registry and self.system_uptime_gauge:
            try:
                self.system_uptime_gauge.set(uptime)
            except Exception as e:
                log.warning("prometheus.set_uptime_error error=%s", str(e))
    
    def generate_metrics(self) -> Optional[bytes]:
        """Generate Prometheus metrics output."""
        if not PROMETHEUS_AVAILABLE or not self.registry:
            return None
        
        try:
            return generate_latest(self.registry)
        except Exception as e:
            log.warning("prometheus.generate_error error=%s", str(e))
            return None
```
**Observation**: Well-defined Prometheus metrics class with proper error handling and graceful degradation. No issues found.

# 2. Code Quality Assessment Report

## 2.1 Overall Assessment

The MCP server codebase demonstrates a high level of code quality with strong emphasis on security, resilience, and observability. The code follows modern Python best practices and is well-structured with clear separation of concerns. The implementation shows evidence of thoughtful design with production considerations in mind.

## 2.2 Strengths

### 2.2.1 Code Structure and Organization
- Clear separation of concerns with dedicated modules for tools, configuration, and metrics.
- Consistent coding style and naming conventions throughout the codebase.
- Well-documented classes and methods with clear docstrings.
- Logical organization of code with related functionality grouped together.

### 2.2.2 Error Handling
- Comprehensive error handling with appropriate exception catching and logging.
- Graceful degradation when optional dependencies are not available.
- Detailed error context with recovery suggestions.
- Proper validation of inputs and configuration values.

### 2.2.3 Security
- Strict input validation to prevent command injection and other security vulnerabilities.
- Proper sanitization of user inputs and arguments.
- Secure handling of sensitive data with redaction for logging.
- Restriction of targets to private networks and lab hostnames.

### 2.2.4 Resilience
- Circuit breaker pattern implementation to prevent cascading failures.
- Timeout handling for all operations to prevent hanging.
- Concurrency control to prevent resource exhaustion.
- Proper resource management with cleanup in error cases.

### 2.2.5 Observability
- Comprehensive metrics collection for both tool execution and system health.
- Prometheus integration with graceful degradation.
- Structured logging with correlation IDs for tracing.
- Detailed error reporting with context.

## 2.3 Areas for Improvement

### 2.3.1 Minor Issues

#### base_tool.py
1. **Execution Time Calculation**: The execution time is calculated twice in the `run` method - once for metrics recording and once for the result. This could lead to slightly different values.
   - **Recommendation**: Calculate the execution time once and reuse it.

2. **Minimum Execution Time**: The minimum execution time is set to 0.001 seconds. While this prevents division by zero, it might skew metrics for very fast operations.
   - **Recommendation**: Consider using a more sophisticated approach for handling very fast operations, such as tracking them separately.

3. **Timeout Error Output**: The timeout error returns a hardcoded stderr message "process timed out" but the stdout is empty. It might be more useful to include any partial output that was generated before the timeout.
   - **Recommendation**: Capture and include partial output in timeout errors.

4. **Environment Variables**: The environment variables for subprocess execution are hardcoded to a minimal set. While this is good for security, it might cause issues for tools that require specific environment variables to function correctly.
   - **Recommendation**: Make the environment variables configurable or allow tools to specify additional environment variables.

5. **Metrics Active Gauge**: The `start_execution` and `end_execution` methods in the `ToolMetrics` class are defined but never called in the code. This means the active gauge will never be updated.
   - **Recommendation**: Call these methods at the appropriate points in the tool execution lifecycle.

6. **Metrics Prefix**: The metrics names are hardcoded with an 'mcp_' prefix. This might cause conflicts if multiple MCP servers are running in the same environment.
   - **Recommendation**: Make the metrics prefix configurable.

#### config.py
1. **Missing Configuration Options**: Some configuration options are referenced in the environment variable mappings but not in the validation logic (e.g., `database.pool_timeout`, `database.pool_recycle`).
   - **Recommendation**: Add validation for all configuration options.

2. **Transport Validation**: The server transport is validated to be either "stdio" or "http", but this validation is case-sensitive.
   - **Recommendation**: Make the transport validation case-insensitive.

#### metrics.py
1. **Thread Safety**: The `SystemMetrics` class has a placeholder for a lock but doesn't use it. In a multi-threaded environment, this could lead to race conditions.
   - **Recommendation**: Implement proper thread safety using the lock or remove the lock placeholder.

### 2.3.2 Potential Issues

#### base_tool.py
1. **Flag Validation**: The flag validation only checks if the flag starts with one of the allowed prefixes. This means that if `--verbose` is allowed, `--verbose-extra` would also be allowed, which might not be intended.
   - **Potential Impact**: This could allow unintended flags to be passed to tools, potentially leading to security vulnerabilities or unexpected behavior.
   - **Recommendation**: Consider using exact flag matching or more sophisticated flag validation.

2. **Circuit Breaker Sharing**: The circuit breaker is stored as a class variable, which means it's shared across all instances of the same tool class. This is appropriate for controlling access to the same resource, but it's worth noting that all instances share the same circuit breaker state.
   - **Potential Impact**: This could lead to unexpected behavior if multiple instances of the same tool class are used in different contexts.
   - **Recommendation**: Document this behavior clearly or consider making the circuit breaker instance-based if appropriate.

#### config.py
1. **Configuration Validation**: The configuration validation logic does not validate all fields in the configuration dataclasses. For example, the `DatabaseConfig` has `pool_timeout` and `pool_recycle` fields, but these are not validated in the `_validate_and_set_config` method.
   - **Potential Impact**: Invalid configuration values could lead to unexpected behavior or errors.
   - **Recommendation**: Add validation for all configuration fields.

#### metrics.py
1. **Metrics Initialization**: The `PrometheusMetrics` class initializes all metrics even if they are not used. This could lead to unnecessary resource usage.
   - **Potential Impact**: Increased memory usage and potential performance impact.
   - **Recommendation**: Consider lazy initialization of metrics.

## 2.4 Security Assessment

### 2.4.1 Security Strengths
- Strict input validation for targets and arguments.
- Proper sanitization of user inputs to prevent command injection.
- Secure handling of sensitive data with redaction for logging.
- Restriction of targets to private networks and lab hostnames.
- Minimal environment for subprocess execution.

### 2.4.2 Security Considerations
- No authentication or authorization mechanism is visible in the codebase.
- No audit logging for security events.
- No integration with dedicated secrets management systems.

### 2.4.3 Security Recommendations
1. **Authentication/Authorization**: Implement authentication and authorization mechanisms to control access to tools.
2. **Audit Logging**: Add comprehensive audit logging for security events.
3. **Secrets Management**: Integrate with dedicated secrets management systems.

## 2.5 Performance Assessment

### 2.5.1 Performance Strengths
- Concurrency control to prevent resource exhaustion.
- Timeout handling for all operations to prevent hanging.
- Efficient metrics collection with minimal performance impact.
- Proper resource management with cleanup in error cases.

### 2.5.2 Performance Considerations
- The metrics collection could have a small performance impact, especially in high-throughput scenarios.
- The circuit breaker pattern adds some overhead to tool execution.

### 2.5.3 Performance Recommendations
1. **Metrics Optimization**: Consider optimizing metrics collection for high-throughput scenarios.
2. **Circuit Breaker Tuning**: Tune circuit breaker parameters based on actual usage patterns.

## 2.6 Testing Recommendations

1. **Unit Tests**: Implement comprehensive unit tests for all classes and methods.
2. **Integration Tests**: Implement integration tests for the overall system.
3. **Performance Tests**: Implement performance tests to validate scalability and identify bottlenecks.
4. **Security Tests**: Implement security tests to validate input validation and sanitization.

## 2.7 Documentation Recommendations

1. **API Documentation**: Create comprehensive API documentation for the MCP server.
2. **Developer Guide**: Create a developer guide for extending the server with new tools.
3. **Deployment Guide**: Create a deployment guide for deploying and configuring the server.
4. **Architecture Documentation**: Create architecture documentation explaining the design decisions and patterns used.

# 3. Project Architecture Document

## 3.1 Introduction

### 3.1.1 Purpose
This document provides a comprehensive overview of the MCP (Model Context Protocol) server architecture, design patterns, and implementation details. It serves as a guide for understanding the codebase and extending it with new tools and functionality.

### 3.1.2 Scope
This document covers the core architecture of the MCP server, including the base tool implementation, configuration management, and metrics collection. It provides guidance for extending the server with new tools and customizing its behavior.

### 3.1.3 Audience
This document is intended for developers, architects, and system administrators who need to understand, extend, or deploy the MCP server.

## 3.2 System Overview

### 3.2.1 Architecture
The MCP server follows a layered architecture with clear separation of concerns:

1. **Tool Layer**: Implements specific tools that extend the base tool functionality.
2. **Base Tool Layer**: Provides the foundation for all tools with common functionality like input validation, error handling, and metrics collection.
3. **Configuration Layer**: Manages configuration for the entire system with validation and hot-reload capabilities.
4. **Metrics Layer**: Collects and exports metrics for monitoring and observability.

### 3.2.2 Design Patterns
The MCP server employs several design patterns:

1. **Abstract Factory Pattern**: The `MCPBaseTool` class serves as an abstract factory for creating specific tool implementations.
2. **Circuit Breaker Pattern**: Used to handle failures and prevent cascading failures.
3. **Observer Pattern**: Metrics collection observes tool execution and system events.
4. **Strategy Pattern**: Different configuration strategies (file, environment variables).
5. **Singleton Pattern**: Global configuration instance.

### 3.2.3 Key Components
The key components of the MCP server are:

1. **MCPBaseTool**: Abstract base class for all tools.
2. **MCPConfig**: Configuration management class.
3. **ToolMetrics**: Metrics collection for tool execution.
4. **SystemMetrics**: System-level metrics collection.
5. **PrometheusMetrics**: Prometheus integration for metrics export.

## 3.3 Component Details

### 3.3.1 MCPBaseTool

#### Purpose
The `MCPBaseTool` class provides the foundation for implementing MCP tools with security, monitoring, and resilience features.

#### Key Features
- Input validation and sanitization
- Error handling with recovery suggestions
- Circuit breaker pattern for fault tolerance
- Metrics collection for observability
- Concurrency control for resource management
- Timeout handling for preventing hanging operations

#### Usage
To implement a new tool, create a class that extends `MCPBaseTool` and implement the required methods:

```python
class MyTool(MCPBaseTool):
    command_name = "mytool"
    allowed_flags = ["-v", "--verbose", "-o", "--output"]
    
    def __init__(self):
        super().__init__()
```

#### Configuration
The `MCPBaseTool` class can be configured through class variables:

- `command_name`: Name of the binary to execute (required).
- `allowed_flags`: Whitelist of flags to allow (optional).
- `concurrency`: Concurrency limit per tool instance (default: 2).
- `default_timeout_sec`: Default timeout for a run in seconds (default: 300).
- `circuit_breaker_failure_threshold`: Failure threshold for circuit breaker (default: 5).
- `circuit_breaker_recovery_timeout`: Recovery timeout for circuit breaker (default: 60.0).
- `circuit_breaker_expected_exception`: Expected exceptions for circuit breaker (default: (Exception,)).

### 3.3.2 MCPConfig

#### Purpose
The `MCPConfig` class manages configuration for the MCP server with validation, hot-reload, and sensitive data handling.

#### Key Features
- Support for both JSON and YAML configuration files
- Environment variable overrides with type conversion
- Validation of configuration values
- Hot-reload capability with change detection
- Sensitive data redaction for logging

#### Usage
To use the configuration system, get the global configuration instance:

```python
from mcp_server.config import get_config

config = get_config("/path/to/config.yaml")
```

#### Configuration Sections
The configuration is divided into several sections:

1. **Database**: Database connection settings.
2. **Security**: Security settings like allowed targets and resource limits.
3. **Circuit Breaker**: Circuit breaker settings for fault tolerance.
4. **Health**: Health check settings for monitoring.
5. **Metrics**: Metrics collection settings.
6. **Logging**: Logging configuration.
7. **Server**: Server settings like host and port.
8. **Tool**: Tool-specific settings.

#### Environment Variables
Configuration can be overridden using environment variables. The following environment variables are supported:

- `MCP_DATABASE_URL`: Database URL.
- `MCP_DATABASE_POOL_SIZE`: Database connection pool size.
- `MCP_SECURITY_MAX_ARGS_LENGTH`: Maximum argument length.
- `MCP_SECURITY_TIMEOUT_SECONDS`: Default timeout in seconds.
- `MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD`: Circuit breaker failure threshold.
- `MCP_CIRCUIT_BREAKER_RECOVERY_TIMEOUT`: Circuit breaker recovery timeout.
- `MCP_HEALTH_CHECK_INTERVAL`: Health check interval.
- `MCP_HEALTH_CPU_THRESHOLD`: CPU usage threshold for health checks.
- `MCP_METRICS_ENABLED`: Enable metrics collection.
- `MCP_METRICS_PROMETHEUS_PORT`: Prometheus metrics port.
- `MCP_LOGGING_LEVEL`: Logging level.
- `MCP_LOGGING_FILE_PATH`: Log file path.
- `MCP_SERVER_HOST`: Server host.
- `MCP_SERVER_PORT`: Server port.
- `MCP_SERVER_TRANSPORT`: Server transport (stdio or http).
- `MCP_TOOL_DEFAULT_TIMEOUT`: Default tool timeout.

### 3.3.3 Metrics Collection

#### Purpose
The metrics collection system provides observability into tool execution and system health.

#### Key Features
- Tool-specific metrics (execution count, success rate, execution time)
- System metrics (uptime, request count, error rate, active connections)
- Prometheus integration with graceful degradation
- Validation of metric values to ensure data integrity

#### Components
The metrics collection system consists of several components:

1. **ToolExecutionMetrics**: Tracks execution metrics for individual tools.
2. **SystemMetrics**: Tracks system-wide metrics.
3. **PrometheusMetrics**: Integration with Prometheus for metrics export.

#### Usage
To use the metrics collection system, create instances of the appropriate metrics classes:

```python
from mcp_server.metrics import ToolExecutionMetrics, SystemMetrics, PrometheusMetrics

tool_metrics = ToolExecutionMetrics("mytool")
system_metrics = SystemMetrics()
prometheus_metrics = PrometheusMetrics()
```

#### Metrics Collected
The following metrics are collected:

1. **Tool Execution Metrics**:
   - Execution count
   - Success count
   - Failure count
   - Timeout count
   - Total execution time
   - Minimum execution time
   - Maximum execution time
   - Last execution time

2. **System Metrics**:
   - Uptime
   - Request count
   - Error count
   - Active connections
   - Error rate

3. **Prometheus Metrics**:
   - Tool execution counter
   - Tool execution histogram
   - Tool active gauge
   - System request counter
   - System error counter
   - System active connections gauge
   - System uptime gauge

## 3.4 Extending the MCP Server

### 3.4.1 Adding New Tools

#### Overview
To add a new tool to the MCP server, create a class that extends `MCPBaseTool` and implement the required methods.

#### Step-by-Step Guide
1. Create a new Python file for your tool in the `mcp_server/tools` directory.
2. Import the necessary modules:
   ```python
   from mcp_server.base_tool import MCPBaseTool, ToolInput, ToolOutput
   ```

3. Create a class that extends `MCPBaseTool`:
   ```python
   class MyTool(MCPBaseTool):
       command_name = "mytool"
       allowed_flags = ["-v", "--verbose", "-o", "--output"]
       concurrency = 2
       default_timeout_sec = 30
   ```

4. Implement any custom methods or override existing methods as needed.

5. Register your tool with the MCP server by adding it to the tool registry.

#### Example
Here's an example of a simple tool that extends `MCPBaseTool`:

```python
from mcp_server.base_tool import MCPBaseTool, ToolInput, ToolOutput

class PingTool(MCPBaseTool):
    command_name = "ping"
    allowed_flags = ["-c", "-i", "-W", "-t"]
    concurrency = 5
    default_timeout_sec = 10
```

### 3.4.2 Customizing Configuration

#### Overview
The MCP server configuration can be customized through configuration files and environment variables.

#### Configuration File
Create a configuration file in JSON or YAML format:

```yaml
database:
  url: "postgresql://user:password@localhost/mcp"
  pool_size: 20
  max_overflow: 30

security:
  max_args_length: 4096
  max_output_size: 2097152
  timeout_seconds: 600
  concurrency_limit: 5

circuit_breaker:
  failure_threshold: 10
  recovery_timeout: 120.0

metrics:
  enabled: true
  prometheus_enabled: true
  prometheus_port: 9091

logging:
  level: "DEBUG"
  file_path: "/var/log/mcp/server.log"

server:
  host: "0.0.0.0"
  port: 8081
  transport: "http"
  workers: 4

tool:
  default_timeout: 600
  default_concurrency: 5
```

#### Environment Variables
Override configuration values using environment variables:

```bash
export MCP_SERVER_PORT=8081
export MCP_LOGGING_LEVEL=DEBUG
export MCP_METRICS_PROMETHEUS_PORT=9091
```

### 3.4.3 Adding Custom Metrics

#### Overview
Custom metrics can be added to track specific aspects of tool execution or system health.

#### Step-by-Step Guide
1. Create a new metrics class that extends the appropriate base class:
   ```python
   from mcp_server.metrics import ToolExecutionMetrics
   
   class CustomToolMetrics(ToolExecutionMetrics):
       def __init__(self, tool_name: str):
           super().__init__(tool_name)
           self.custom_metric = 0
       
       def record_custom_event(self):
           self.custom_metric += 1
   ```

2. Use your custom metrics class in your tool:
   ```python
   class MyTool(MCPBaseTool):
       def __init__(self):
           super().__init__()
           self.custom_metrics = CustomToolMetrics(self.tool_name)
   ```

3. Record custom metrics as needed:
   ```python
   self.custom_metrics.record_custom_event()
   ```

#### Example
Here's an example of a custom metrics class:

```python
from mcp_server.metrics import ToolExecutionMetrics
from typing import Dict, Any

class NetworkToolMetrics(ToolExecutionMetrics):
    def __init__(self, tool_name: str):
        super().__init__(tool_name)
        self.bytes_sent = 0
        self.bytes_received = 0
        self.connection_count = 0
    
    def record_bytes_sent(self, count: int):
        self.bytes_sent += count
    
    def record_bytes_received(self, count: int):
        self.bytes_received += count
    
    def record_connection(self):
        self.connection_count += 1
    
    def get_stats(self) -> Dict[str, Any]:
        stats = super().get_stats()
        stats.update({
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "connection_count": self.connection_count
        })
        return stats
```

### 3.4.4 Adding Custom Error Types

#### Overview
Custom error types can be added to provide more specific error handling and recovery suggestions.

#### Step-by-Step Guide
1. Add new error types to the `ToolErrorType` enum:
   ```python
   class ToolErrorType(Enum):
       # Existing error types...
       NETWORK_ERROR = "network_error"
       AUTHENTICATION_ERROR = "authentication_error"
   ```

2. Use your custom error types in error handling:
   ```python
   error_context = ErrorContext(
       error_type=ToolErrorType.NETWORK_ERROR,
       message="Network connection failed",
       recovery_suggestion="Check network connectivity and try again",
       timestamp=datetime.now(),
       tool_name=self.tool_name,
       target=inp.target,
       metadata={}
   )
   ```

#### Example
Here's an example of adding custom error types:

```python
from mcp_server.base_tool import ToolErrorType, ErrorContext
from datetime import datetime

# Add custom error types
class CustomToolErrorType(Enum):
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    QUOTA_EXCEEDED = "quota_exceeded"
    INVALID_RESPONSE = "invalid_response"

# Use custom error types
error_context = ErrorContext(
    error_type=CustomToolErrorType.RATE_LIMIT_EXCEEDED,
    message="Rate limit exceeded",
    recovery_suggestion="Wait before making another request",
    timestamp=datetime.now(),
    tool_name=self.tool_name,
    target=inp.target,
    metadata={"retry_after": "60s"}
)
```

## 3.5 Best Practices

### 3.5.1 Tool Implementation
1. **Input Validation**: Always validate inputs and sanitize user-provided data.
2. **Error Handling**: Implement comprehensive error handling with recovery suggestions.
3. **Resource Management**: Properly manage resources and clean up in error cases.
4. **Concurrency**: Be mindful of concurrency and use appropriate synchronization mechanisms.
5. **Timeouts**: Set appropriate timeouts for all operations to prevent hanging.

### 3.5.2 Configuration Management
1. **Validation**: Validate all configuration values and provide sensible defaults.
2. **Sensitive Data**: Properly handle sensitive data and redact it for logging.
3. **Hot-Reload**: Implement hot-reload capability for configuration changes.
4. **Environment Variables**: Support environment variable overrides for deployment flexibility.

### 3.5.3 Metrics Collection
1. **Relevance**: Collect metrics that are relevant and useful for monitoring and debugging.
2. **Performance**: Minimize the performance impact of metrics collection.
3. **Consistency**: Use consistent naming conventions for metrics.
4. **Cardinality**: Be mindful of metric cardinality to avoid excessive resource usage.

### 3.5.4 Security
1. **Input Validation**: Validate all inputs and sanitize user-provided data.
2. **Least Privilege**: Follow the principle of least privilege for all operations.
3. **Secure Defaults**: Use secure defaults for all configuration options.
4. **Audit Logging**: Implement comprehensive audit logging for security events.

## 3.6 Deployment Considerations

### 3.6.1 Environment Configuration
1. **Development**: Use development-specific configuration with verbose logging and debugging features.
2. **Testing**: Use testing-specific configuration with mock services and controlled environments.
3. **Production**: Use production-specific configuration with optimized settings and enhanced security.

### 3.6.2 Scaling
1. **Horizontal Scaling**: Design for horizontal scaling with stateless components.
2. **Load Balancing**: Use load balancing to distribute traffic across multiple instances.
3. **Caching**: Implement caching for frequently accessed resources.
4. **Database Scaling**: Consider database scaling strategies for high-traffic scenarios.

### 3.6.3 Monitoring
1. **Metrics**: Collect and monitor metrics for system health and performance.
2. **Logging**: Implement centralized logging for aggregation and analysis.
3. **Alerting**: Set up alerting for critical events and anomalies.
4. **Distributed Tracing**: Implement distributed tracing for request tracking.

### 3.6.4 Security
1. **Authentication**: Implement authentication mechanisms to control access.
2. **Authorization**: Implement authorization mechanisms to control permissions.
3. **Encryption**: Use encryption for sensitive data in transit and at rest.
4. **Vulnerability Management**: Implement regular vulnerability scanning and patching.

## 3.7 Future Enhancements

### 3.7.1 Authentication and Authorization
1. **User Authentication**: Implement user authentication mechanisms.
2. **Role-Based Access Control**: Implement role-based access control for tools.
3. **API Key Management**: Implement API key management for programmatic access.

### 3.7.2 Advanced Features
1. **Tool Chaining**: Implement tool chaining for complex workflows.
2. **Result Caching**: Implement result caching for improved performance.
3. **Async Processing**: Implement async processing for long-running operations.

### 3.7.3 Observability
1. **Distributed Tracing**: Implement distributed tracing for request tracking.
2. **Custom Dashboards**: Create custom dashboards for monitoring and visualization.
3. **Anomaly Detection**: Implement anomaly detection for proactive issue identification.

### 3.7.4 Performance Optimization
1. **Connection Pooling**: Implement connection pooling for improved performance.
2. **Resource Optimization**: Optimize resource usage for high-traffic scenarios.
3. **Caching Strategies**: Implement advanced caching strategies for frequently accessed resources.

## 3.8 Conclusion

The MCP server architecture provides a solid foundation for building secure, resilient, and observable tools. With its modular design and extensible architecture, it can be easily customized and extended to meet specific requirements. By following the best practices and guidelines outlined in this document, developers can create high-quality tools that integrate seamlessly with the MCP server.
# 1. Meticulous Line-by-Line Code Review

## 1.1 mcp_server/base_tool.py

### Imports and Dependencies
```python
import asyncio
import logging
import os
import re
import shlex
import shutil
import time
import contextlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Optional, Sequence, Dict, Any
from datetime import datetime, timedelta
```
**Observation**: All necessary imports are present and well-organized. No issues found.

### Pydantic Compatibility Shim
```python
# Pydantic v1/v2 compatibility shim
try: # Pydantic v2
    from pydantic import BaseModel, field_validator
    _PD_V2 = True
except ImportError: # Pydantic v1
    from pydantic import BaseModel, validator as field_validator # type: ignore
    _PD_V2 = False
```
**Observation**: Good compatibility shim for handling both Pydantic v1 and v2. The type ignore comment is appropriate for the compatibility layer.

### Metrics and Circuit Breaker Imports
```python
# Metrics integration with graceful handling
try:
    from prometheus_client import Counter, Histogram, Gauge, Info
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# Circuit breaker implementation with fallback import
try:
    from .circuit_breaker import CircuitBreaker, CircuitBreakerState
except ImportError:
    from circuit_breaker import CircuitBreaker, CircuitBreakerState

# Tool metrics with fallback import
try:
    from .metrics import ToolMetrics
except ImportError:
    from metrics import ToolMetrics
```
**Observation**: Good graceful handling of optional dependencies. The fallback imports allow the code to work even when these dependencies are not available.

### Constants and Configuration
```python
log = logging.getLogger(__name__)

# Conservative denylist for arg tokens we never want to see (even though shell=False)
_DENY_CHARS = re.compile(r"[;&|`$><\n\r]") # control/meta chars
_TOKEN_ALLOWED = re.compile(r"^[A-Za-z0-9.:/=+-,@%]+$") # reasonably safe superset
_MAX_ARGS_LEN = int(os.getenv("MCP_MAX_ARGS_LEN", "2048"))
_MAX_STDOUT_BYTES = int(os.getenv("MCP_MAX_STDOUT_BYTES", "1048576")) # 1 MiB
_MAX_STDERR_BYTES = int(os.getenv("MCP_MAX_STDERR_BYTES", "262144")) # 256 KiB
_DEFAULT_TIMEOUT_SEC = float(os.getenv("MCP_DEFAULT_TIMEOUT_SEC", "300")) # 5 minutes
_DEFAULT_CONCURRENCY = int(os.getenv("MCP_DEFAULT_CONCURRENCY", "2"))
```
**Observation**: 
- Good use of environment variables for configuration with sensible defaults.
- The regex patterns for input validation are well-defined.
- **Potential Issue**: The `_DENY_CHARS` regex includes backslashes which need to be escaped in raw strings. However, in this case, it's correctly escaped as `\\n` and `\\r`, so no issue.

### Private Network Validation Function
```python
def _is_private_or_lab(value: str) -> bool:
    """
    Accept:
    - RFC1918 IPv4 address (10/8, 172.16/12, 192.168/16)
    - RFC1918 IPv4 network in CIDR form
    - Hostname ending with .lab.internal
    """
    import ipaddress
    v = value.strip()
    # Hostname allowance
    if v.endswith(".lab.internal"):
        return True
    # IP or CIDR
    try:
        if "/" in v:
            net = ipaddress.ip_network(v, strict=False)
            return net.version == 4 and net.is_private
        else:
            ip = ipaddress.ip_address(v)
            return ip.version == 4 and ip.is_private
    except ValueError:
        return False
```
**Observation**: 
- Good validation function for private networks and lab hostnames.
- **Potential Issue**: The function imports `ipaddress` inside the function. While this works, it's more conventional to put imports at the top of the file. However, this might be intentional to avoid importing if the function is never called.
- **Security Consideration**: The function correctly handles both IP addresses and CIDR notation, and properly restricts to IPv4 private networks.

### Error Type Enum
```python
class ToolErrorType(Enum):
    """Enhanced error taxonomy with recovery suggestions."""
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"
    VALIDATION_ERROR = "validation_error"
    EXECUTION_ERROR = "execution_error"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"
    UNKNOWN = "unknown"
```
**Observation**: Well-defined error types with clear naming. No issues found.

### Error Context Dataclass
```python
@dataclass
class ErrorContext:
    """Context for enhanced error reporting."""
    error_type: ToolErrorType
    message: str
    recovery_suggestion: str
    timestamp: datetime
    tool_name: str
    target: str
    metadata: Dict[str, Any]
```
**Observation**: Well-structured error context with all necessary information. No issues found.

### Tool Input Model
```python
class ToolInput(BaseModel):
    """Enhanced ToolInput with additional validation."""
    target: str
    extra_args: str = ""
    timeout_sec: Optional[float] = None
    correlation_id: Optional[str] = None
    
    # v1/v2 compatible field validator
    if _PD_V2:
        @field_validator("target")
        @classmethod
        def _validate_target(cls, v: str) -> str:
            if not _is_private_or_lab(v):
                raise ValueError("Target must be RFC1918 IPv4 or a .lab.internal hostname (CIDR allowed).")
            return v
        
        @field_validator("extra_args")
        @classmethod
        def _validate_extra_args(cls, v: str) -> str:
            v = v or ""
            if len(v) > _MAX_ARGS_LEN:
                raise ValueError(f"extra_args too long (> {_MAX_ARGS_LEN} bytes)")
            if _DENY_CHARS.search(v):
                raise ValueError("extra_args contains forbidden metacharacters")
            return v
    else:
        @field_validator("target")
        def _validate_target(cls, v: str) -> str: # type: ignore
            if not _is_private_or_lab(v):
                raise ValueError("Target must be RFC1918 IPv4 or a .lab.internal hostname (CIDR allowed).")
            return v
        
        @field_validator("extra_args")
        def _validate_extra_args(cls, v: str) -> str: # type: ignore
            v = v or ""
            if len(v) > _MAX_ARGS_LEN:
                raise ValueError(f"extra_args too long (> {_MAX_ARGS_LEN} bytes)")
            if _DENY_CHARS.search(v):
                raise ValueError("extra_args contains forbidden metacharacters")
            return v
```
**Observation**:
- Good validation for both target and extra_args.
- Proper handling of Pydantic v1/v2 compatibility.
- **Potential Issue**: The validation for extra_args checks for forbidden characters but doesn't validate that the arguments are appropriate for the specific tool. This might be intentional to keep the base tool generic.

### Tool Output Model
```python
class ToolOutput(BaseModel):
    """Enhanced ToolOutput with additional metadata."""
    stdout: str
    stderr: str
    returncode: int
    truncated_stdout: bool = False
    truncated_stderr: bool = False
    timed_out: bool = False
    error: Optional[str] = None
    error_type: Optional[str] = None
    execution_time: Optional[float] = None
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = {}
```
**Observation**: Well-structured output model with all necessary fields. No issues found.

### MCP Base Tool Class
```python
class MCPBaseTool(ABC):
    """
    Enhanced base class for MCP tools with circuit breaker, metrics, and advanced features.
    """
    
    # Required: name of the binary to execute, e.g., "nmap"
    command_name: ClassVar[str]
    
    # Optional: a whitelist of flags (prefix match) to allow
    allowed_flags: ClassVar[Optional[Sequence[str]]] = None
    
    # Concurrency limit per tool instance
    concurrency: ClassVar[int] = _DEFAULT_CONCURRENCY
    
    # Default timeout for a run in seconds
    default_timeout_sec: ClassVar[float] = _DEFAULT_TIMEOUT_SEC
    
    # Circuit breaker configuration
    circuit_breaker_failure_threshold: ClassVar[int] = 5
    circuit_breaker_recovery_timeout: ClassVar[float] = 60.0
    circuit_breaker_expected_exception: ClassVar[tuple] = (Exception,)
    
    # Semaphore created on first use per subclass
    _semaphore: ClassVar[Optional[asyncio.Semaphore]] = None
    
    # Circuit breaker instance per tool
    _circuit_breaker: ClassVar[Optional[CircuitBreaker]] = None
```
**Observation**: Well-defined class variables with appropriate types and defaults. No issues found.

### Initialization Methods
```python
def __init__(self):
    self.tool_name = self.__class__.__name__
    self._initialize_metrics()
    self._initialize_circuit_breaker()

def _initialize_metrics(self):
    """Initialize Prometheus metrics for this tool."""
    if PROMETHEUS_AVAILABLE:
        try:
            self.metrics = ToolMetrics(self.tool_name)
        except Exception as e:
            log.warning("metrics.initialization_failed tool=%s error=%s", self.tool_name, str(e))
            self.metrics = None
    else:
        self.metrics = None

def _initialize_circuit_breaker(self):
    """Initialize circuit breaker for this tool."""
    if self.__class__._circuit_breaker is None:
        try:
            self.__class__._circuit_breaker = CircuitBreaker(
                failure_threshold=self.circuit_breaker_failure_threshold,
                recovery_timeout=self.circuit_breaker_recovery_timeout,
                expected_exception=self.circuit_breaker_expected_exception,
                name=self.tool_name
            )
        except Exception as e:
            log.error("circuit_breaker.initialization_failed tool=%s error=%s", self.tool_name, str(e))
            self.__class__._circuit_breaker = None
```
**Observation**:
- Good initialization of metrics and circuit breaker with proper error handling.
- **Potential Issue**: The circuit breaker is stored as a class variable, which means it's shared across all instances of the same tool class. This is appropriate for controlling access to the same resource, but it's worth noting that all instances share the same circuit breaker state.

### Semaphore Management
```python
def _ensure_semaphore(self) -> asyncio.Semaphore:
    """Ensure semaphore exists for this tool class."""
    if self.__class__._semaphore is None:
        self.__class__._semaphore = asyncio.Semaphore(self.concurrency)
    return self.__class__._semaphore
```
**Observation**:
- Good lazy initialization of semaphore with proper concurrency control.
- **Potential Issue**: Similar to the circuit breaker, the semaphore is stored as a class variable, which means it's shared across all instances of the same tool class. This is appropriate for controlling access to the same resource.

### Run Method
```python
async def run(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
    """
    Enhanced run method with circuit breaker, metrics, and error handling.
    """
    start_time = time.time()
    correlation_id = inp.correlation_id or str(int(start_time * 1000))
    
    try:
        # Check circuit breaker state
        if self._circuit_breaker and self._circuit_breaker.state == CircuitBreakerState.OPEN:
            error_context = ErrorContext(
                error_type=ToolErrorType.CIRCUIT_BREAKER_OPEN,
                message=f"Circuit breaker is open for {self.tool_name}",
                recovery_suggestion="Wait for recovery timeout or check service health",
                timestamp=datetime.now(),
                tool_name=self.tool_name,
                target=inp.target,
                metadata={"state": str(self._circuit_breaker.state)}
            )
            return self._create_error_output(error_context, correlation_id)
        
        # Acquire semaphore for concurrency control
        async with self._ensure_semaphore():
            # Execute with circuit breaker protection
            if self._circuit_breaker:
                try:
                    result = await self._circuit_breaker.call(
                        self._execute_tool,
                        inp,
                        timeout_sec
                    )
                except Exception as circuit_error:
                    # Handle circuit breaker specific errors
                    error_context = ErrorContext(
                        error_type=ToolErrorType.CIRCUIT_BREAKER_OPEN,
                        message=f"Circuit breaker error: {str(circuit_error)}",
                        recovery_suggestion="Wait for recovery timeout or check service health",
                        timestamp=datetime.now(),
                        tool_name=self.tool_name,
                        target=inp.target,
                        metadata={"circuit_error": str(circuit_error)}
                    )
                    return self._create_error_output(error_context, correlation_id)
            else:
                result = await self._execute_tool(inp, timeout_sec)
            
            # Record metrics with validation
            if self.metrics:
                execution_time = max(0.001, time.time() - start_time)  # Ensure minimum positive value
                try:
                    self.metrics.record_execution(
                        success=result.returncode == 0,
                        execution_time=execution_time,
                        timed_out=result.timed_out
                    )
                except Exception as e:
                    log.warning("metrics.recording_failed tool=%s error=%s", self.tool_name, str(e))
            
            # Add correlation ID and execution time
            result.correlation_id = correlation_id
            result.execution_time = max(0.001, time.time() - start_time)
            
            return result
            
    except Exception as e:
        execution_time = max(0.001, time.time() - start_time)
        error_context = ErrorContext(
            error_type=ToolErrorType.EXECUTION_ERROR,
            message=f"Tool execution failed: {str(e)}",
            recovery_suggestion="Check tool logs and system resources",
            timestamp=datetime.now(),
            tool_name=self.tool_name,
            target=inp.target,
            metadata={"exception": str(e), "execution_time": execution_time}
        )
        
        # Record failure metrics
        if self.metrics:
            try:
                self.metrics.record_execution(
                    success=False,
                    execution_time=execution_time,
                    error_type=ToolErrorType.EXECUTION_ERROR.value
                )
            except Exception as metrics_error:
                log.warning("metrics.failure_recording_failed tool=%s error=%s", 
                          self.tool_name, str(metrics_error))
        
        return self._create_error_output(error_context, correlation_id)
```
**Observation**:
- Comprehensive run method with proper error handling, circuit breaker protection, and metrics recording.
- Good use of correlation IDs for tracing.
- **Issue**: The execution time is calculated twice - once for metrics recording and once for the result. This could lead to slightly different values.
- **Issue**: The minimum execution time is set to 0.001 seconds. While this prevents division by zero, it might skew metrics for very fast operations.

### Execute Tool Method
```python
async def _execute_tool(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
    """Execute the actual tool with enhanced error handling."""
    # Resolve command and build arguments
    resolved_cmd = self._resolve_command()
    if not resolved_cmd:
        error_context = ErrorContext(
            error_type=ToolErrorType.NOT_FOUND,
            message=f"Command not found: {self.command_name}",
            recovery_suggestion="Install the required tool or check PATH",
            timestamp=datetime.now(),
            tool_name=self.tool_name,
            target=inp.target,
            metadata={"command": self.command_name}
        )
        return self._create_error_output(error_context, inp.correlation_id)
    
    # Parse and validate arguments
    try:
        args = self._parse_args(inp.extra_args)
    except ValueError as e:
        error_context = ErrorContext(
            error_type=ToolErrorType.VALIDATION_ERROR,
            message=f"Argument validation failed: {str(e)}",
            recovery_suggestion="Check arguments and try again",
            timestamp=datetime.now(),
            tool_name=self.tool_name,
            target=inp.target,
            metadata={"validation_error": str(e)}
        )
        return self._create_error_output(error_context, inp.correlation_id)
    
    # Build command
    cmd = [resolved_cmd] + args + [inp.target]
    
    # Execute with timeout
    timeout = float(timeout_sec or self.default_timeout_sec)
    return await self._spawn(cmd, timeout)
```
**Observation**: Good error handling and validation. No issues found.

### Error Output Creation
```python
def _create_error_output(self, error_context: ErrorContext, correlation_id: str) -> ToolOutput:
    """Create a ToolOutput for error conditions."""
    log.error(
        "tool.error tool=%s error_type=%s target=%s message=%s correlation_id=%s",
        error_context.tool_name,
        error_context.error_type.value,
        error_context.target,
        error_context.message,
        correlation_id,
        extra={"error_context": error_context}
    )
    
    return ToolOutput(
        stdout="",
        stderr=error_context.message,
        returncode=1,
        error=error_context.message,
        error_type=error_context.error_type.value,
        correlation_id=correlation_id,
        metadata={
            "recovery_suggestion": error_context.recovery_suggestion,
            "timestamp": error_context.timestamp.isoformat()
        }
    )
```
**Observation**: Good error logging and creation of error output. No issues found.

### Command Resolution
```python
def _resolve_command(self) -> Optional[str]:
    """Resolve command path using shutil.which."""
    return shutil.which(self.command_name)
```
**Observation**: Simple and effective command resolution. No issues found.

### Argument Parsing
```python
def _parse_args(self, extra_args: str) -> Sequence[str]:
    """Parse and validate extra arguments."""
    if not extra_args:
        return []
    
    tokens = shlex.split(extra_args)
    safe: list[str] = []
    
    for t in tokens:
        if not t:  # skip empties
            continue
        if not _TOKEN_ALLOWED.match(t):
            raise ValueError(f"Disallowed token in args: {t!r}")
        safe.append(t)
    
    if self.allowed_flags is not None:
        # Approve flags by prefix match; non-flags (e.g., values) are allowed
        allowed = tuple(self.allowed_flags)
        for t in safe:
            if t.startswith("-") and not t.startswith(allowed):
                raise ValueError(f"Flag not allowed: {t!r}")
    
    return safe
```
**Observation**:
- Good argument parsing with proper validation.
- **Issue**: The flag validation only checks if the flag starts with one of the allowed prefixes. This means that if `--verbose` is allowed, `--verbose-extra` would also be allowed, which might not be intended.

### Subprocess Execution
```python
async def _spawn(
    self,
    cmd: Sequence[str],
    timeout_sec: Optional[float] = None,
) -> ToolOutput:
    """Spawn and monitor a subprocess with timeout and output truncation."""
    timeout = float(timeout_sec or self.default_timeout_sec)
    
    # Minimal, sanitized environment
    env = {
        "PATH": os.getenv("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    
    try:
        log.info(
            "tool.start command=%s timeout=%.1f",
            " ".join(cmd),
            timeout,
        )
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            rc = proc.returncode
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            out, err, rc = b"", b"process timed out", 124
            return ToolOutput(
                stdout="",
                stderr="process timed out",
                returncode=rc,
                truncated_stdout=False,
                truncated_stderr=False,
                timed_out=True,
                error="timeout",
            )
        
        # Truncate outputs if necessary
        t_stdout = False
        t_stderr = False
        
        if len(out) > _MAX_STDOUT_BYTES:
            out = out[:_MAX_STDOUT_BYTES]
            t_stdout = True
        
        if len(err) > _MAX_STDERR_BYTES:
            err = err[:_MAX_STDERR_BYTES]
            t_stderr = True
        
        result = ToolOutput(
            stdout=out.decode(errors="replace"),
            stderr=err.decode(errors="replace"),
            returncode=rc,
            truncated_stdout=t_stdout,
            truncated_stderr=t_stderr,
            timed_out=False,
        )
        
        log.info(
            "tool.end command=%s returncode=%s truncated_stdout=%s truncated_stderr=%s",
            cmd[0],
            rc,
            t_stdout,
            t_stderr,
        )
        
        return result
        
    except FileNotFoundError:
        msg = f"Command not found: {cmd[0]}"
        log.error("tool.error %s", msg)
        return ToolOutput(stdout="", stderr=msg, returncode=127, error="not_found")
    
    except Exception as e:
        msg = f"execution failed: {e.__class__.__name__}: {e}"
        log.error("tool.error %s", msg)
        return ToolOutput(stdout="", stderr=msg, returncode=1, error="execution_failed")
```
**Observation**:
- Good subprocess execution with proper timeout handling and output truncation.
- **Issue**: The timeout error returns a hardcoded stderr message "process timed out" but the stdout is empty. It might be more useful to include any partial output that was generated before the timeout.
- **Issue**: The environment variables are hardcoded to a minimal set. While this is good for security, it might cause issues for tools that require specific environment variables to function correctly.

### ToolMetrics Class
```python
class ToolMetrics:
    """Metrics collection for tool execution."""
    
    def __init__(self, tool_name: str):
        self.tool_name = tool_name
        
        if PROMETHEUS_AVAILABLE:
            try:
                self.execution_counter = Counter(
                    f'mcp_tool_execution_total',
                    'Total tool executions',
                    ['tool', 'status', 'error_type']
                )
                self.execution_histogram = Histogram(
                    f'mcp_tool_execution_seconds',
                    'Tool execution time in seconds',
                    ['tool']
                )
                self.active_gauge = Gauge(
                    f'mcp_tool_active',
                    'Currently active tool executions',
                    ['tool']
                )
                self.error_counter = Counter(
                    f'mcp_tool_errors_total',
                    'Total tool errors',
                    ['tool', 'error_type']
                )
            except Exception as e:
                log.warning("prometheus.metrics_initialization_failed tool=%s error=%s", tool_name, str(e))
                # Disable metrics if initialization fails
                self.execution_counter = None
                self.execution_histogram = None
                self.active_gauge = None
                self.error_counter = None
        else:
            self.execution_counter = None
            self.execution_histogram = None
            self.active_gauge = None
            self.error_counter = None
    
    def record_execution(self, success: bool, execution_time: float, 
                        timed_out: bool = False, error_type: str = None):
        """Record tool execution metrics."""
        if not PROMETHEUS_AVAILABLE or not self.execution_counter:
            return
        
        try:
            # Validate execution time
            execution_time = max(0.0, float(execution_time))
            
            status = 'success' if success else 'failure'
            self.execution_counter.labels(
                tool=self.tool_name,
                status=status,
                error_type=error_type or 'none'
            ).inc()
            
            if self.execution_histogram:
                self.execution_histogram.labels(tool=self.tool_name).observe(execution_time)
            
            if not success and self.error_counter:
                self.error_counter.labels(
                    tool=self.tool_name,
                    error_type=error_type or 'unknown'
                ).inc()
        except Exception as e:
            log.warning("metrics.recording_error tool=%s error=%s", self.tool_name, str(e))
    
    def start_execution(self):
        """Record start of execution."""
        if PROMETHEUS_AVAILABLE and self.active_gauge:
            try:
                self.active_gauge.labels(tool=self.tool_name).inc()
            except Exception as e:
                log.warning("metrics.start_execution_error tool=%s error=%s", self.tool_name, str(e))
    
    def end_execution(self):
        """Record end of execution."""
        if PROMETHEUS_AVAILABLE and self.active_gauge:
            try:
                self.active_gauge.labels(tool=self.tool_name).dec()
            except Exception as e:
                log.warning("metrics.end_execution_error tool=%s error=%s", self.tool_name, str(e))
```
**Observation**:
- Good metrics collection with proper error handling.
- **Issue**: The `start_execution` and `end_execution` methods are defined but never called in the code. This means the active gauge will never be updated.
- **Issue**: The metrics names are hardcoded with an 'mcp_' prefix. This might cause conflicts if multiple MCP servers are running in the same environment.

## 1.2 mcp_server/config.py

### Imports and Dependencies
```python
import os
import logging
import json
import yaml
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
```
**Observation**: All necessary imports are present and well-organized. No issues found.

### Pydantic Compatibility Shim
```python
# Pydantic for configuration validation
try:
    from pydantic import BaseModel, Field, validator
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    # Fallback validation without Pydantic
    class BaseModel:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
        
        def dict(self):
            return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}
    
    Field = lambda default=None, **kwargs: default
    def validator(field_name, *args, **kwargs):
        def decorator(func):
            return func
        return decorator
```
**Observation**: Good compatibility shim for handling Pydantic availability. The fallback implementation provides basic functionality. No issues found.

### Configuration Dataclasses
```python
log = logging.getLogger(__name__)

@dataclass
class DatabaseConfig:
    """Database configuration."""
    url: str = ""
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 3600

@dataclass
class SecurityConfig:
    """Security configuration."""
    allowed_targets: List[str] = field(default_factory=lambda: ["RFC1918", ".lab.internal"])
    max_args_length: int = 2048
    max_output_size: int = 1048576
    timeout_seconds: int = 300
    concurrency_limit: int = 2

@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    expected_exceptions: List[str] = field(default_factory=lambda: ["Exception"])
    half_open_success_threshold: int = 1

@dataclass
class HealthConfig:
    """Health check configuration."""
    check_interval: float = 30.0
    cpu_threshold: float = 80.0
    memory_threshold: float = 80.0
    disk_threshold: float = 80.0
    dependencies: List[str] = field(default_factory=list)
    timeout: float = 10.0

@dataclass
class MetricsConfig:
    """Metrics configuration."""
    enabled: bool = True
    prometheus_enabled: bool = True
    prometheus_port: int = 9090
    collection_interval: float = 15.0

@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file_path: Optional[str] = None
    max_file_size: int = 10485760  # 10MB
    backup_count: int = 5

@dataclass
class ServerConfig:
    """Server configuration."""
    host: str = "0.0.0.0"
    port: int = 8080
    transport: str = "stdio"  # "stdio" or "http"
    workers: int = 1
    max_connections: int = 100
    shutdown_grace_period: float = 30.0

@dataclass
class ToolConfig:
    """Tool-specific configuration."""
    include_patterns: List[str] = field(default_factory=lambda: ["*"])
    exclude_patterns: List[str] = field(default_factory=list)
    default_timeout: int = 300
    default_concurrency: int = 2
```
**Observation**: Well-defined configuration dataclasses with appropriate defaults. No issues found.

### MCPConfig Class
```python
class MCPConfig:
    """
    Main MCP configuration class with validation and hot-reload support.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path
        self.last_modified = None
        self._config_data = {}
        
        # Initialize with defaults
        self.database = DatabaseConfig()
        self.security = SecurityConfig()
        self.circuit_breaker = CircuitBreakerConfig()
        self.health = HealthConfig()
        self.metrics = MetricsConfig()
        self.logging = LoggingConfig()
        self.server = ServerConfig()
        self.tool = ToolConfig()
        
        # Load configuration
        self.load_config()
```
**Observation**: Good initialization of configuration with defaults. No issues found.

### Configuration Loading Methods
```python
def load_config(self):
    """Load configuration from file and environment variables."""
    # Start with defaults
    config_data = self._get_defaults()
    
    # Load from file if specified
    if self.config_path and os.path.exists(self.config_path):
        config_data.update(self._load_from_file(self.config_path))
    
    # Override with environment variables
    config_data.update(self._load_from_environment())
    
    # Validate and set configuration
    self._validate_and_set_config(config_data)
    
    # Update last modified time
    if self.config_path:
        try:
            self.last_modified = os.path.getmtime(self.config_path)
        except OSError:
            self.last_modified = None

def _get_defaults(self) -> Dict[str, Any]:
    """Get default configuration values."""
    return {
        "database": asdict(DatabaseConfig()),
        "security": asdict(SecurityConfig()),
        "circuit_breaker": asdict(CircuitBreakerConfig()),
        "health": asdict(HealthConfig()),
        "metrics": asdict(MetricsConfig()),
        "logging": asdict(LoggingConfig()),
        "server": asdict(ServerConfig()),
        "tool": asdict(ToolConfig())
    }

def _load_from_file(self, config_path: str) -> Dict[str, Any]:
    """Load configuration from file (JSON or YAML)."""
    try:
        file_path = Path(config_path)
        
        if not file_path.exists():
            log.warning("config.file_not_found path=%s", config_path)
            return {}
        
        with open(file_path, 'r', encoding='utf-8') as f:
            if file_path.suffix.lower() in ['.yaml', '.yml']:
                return yaml.safe_load(f) or {}
            else:
                return json.load(f) or {}
    
    except Exception as e:
        log.error("config.file_load_failed path=%s error=%s", config_path, str(e))
        return {}
```
**Observation**: Good configuration loading with proper error handling. No issues found.

### Environment Variable Loading
```python
def _load_from_environment(self) -> Dict[str, Any]:
    """Load configuration from environment variables."""
    config = {}
    
    # Environment variable mappings
    env_mappings = {
        'MCP_DATABASE_URL': ('database', 'url'),
        'MCP_DATABASE_POOL_SIZE': ('database', 'pool_size'),
        'MCP_SECURITY_MAX_ARGS_LENGTH': ('security', 'max_args_length'),
        'MCP_SECURITY_TIMEOUT_SECONDS': ('security', 'timeout_seconds'),
        'MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD': ('circuit_breaker', 'failure_threshold'),
        'MCP_CIRCUIT_BREAKER_RECOVERY_TIMEOUT': ('circuit_breaker', 'recovery_timeout'),
        'MCP_HEALTH_CHECK_INTERVAL': ('health', 'check_interval'),
        'MCP_HEALTH_CPU_THRESHOLD': ('health', 'cpu_threshold'),
        'MCP_METRICS_ENABLED': ('metrics', 'enabled'),
        'MCP_METRICS_PROMETHEUS_PORT': ('metrics', 'prometheus_port'),
        'MCP_LOGGING_LEVEL': ('logging', 'level'),
        'MCP_LOGGING_FILE_PATH': ('logging', 'file_path'),
        'MCP_SERVER_HOST': ('server', 'host'),
        'MCP_SERVER_PORT': ('server', 'port'),
        'MCP_SERVER_TRANSPORT': ('server', 'transport'),
        'MCP_TOOL_DEFAULT_TIMEOUT': ('tool', 'default_timeout'),
    }
    
    for env_var, (section, key) in env_mappings.items():
        value = os.getenv(env_var)
        if value is not None:
            if section not in config:
                config[section] = {}
            
            # Type conversion
            if key in ['pool_size', 'max_args_length', 'timeout_seconds', 'failure_threshold', 
                      'prometheus_port', 'default_timeout']:
                try:
                    config[section][key] = int(value)
                except ValueError:
                    log.warning("config.invalid_int env_var=%s value=%s", env_var, value)
            elif key in ['recovery_timeout', 'check_interval', 'cpu_threshold']:
                try:
                    config[section][key] = float(value)
                except ValueError:
                    log.warning("config.invalid_float env_var=%s value=%s", env_var, value)
            elif key in ['enabled']:
                config[section][key] = value.lower() in ['true', '1', 'yes', 'on']
            else:
                config[section][key] = value
    
    return config
```
**Observation**: Good environment variable loading with proper type conversion. No issues found.

### Configuration Validation
```python
def _validate_and_set_config(self, config_data: Dict[str, Any]):
    """Validate and set configuration values."""
    try:
        # Validate database config
        if 'database' in config_data:
            db_config = config_data['database']
            self.database.url = str(db_config.get('url', self.database.url))
            self.database.pool_size = max(1, int(db_config.get('pool_size', self.database.pool_size)))
            self.database.max_overflow = max(0, int(db_config.get('max_overflow', self.database.max_overflow)))
        
        # Validate security config
        if 'security' in config_data:
            sec_config = config_data['security']
            self.security.max_args_length = max(1, int(sec_config.get('max_args_length', self.security.max_args_length)))
            self.security.max_output_size = max(1, int(sec_config.get('max_output_size', self.security.max_output_size)))
            self.security.timeout_seconds = max(1, int(sec_config.get('timeout_seconds', self.security.timeout_seconds)))
            self.security.concurrency_limit = max(1, int(sec_config.get('concurrency_limit', self.security.concurrency_limit)))
        
        # Validate circuit breaker config
        if 'circuit_breaker' in config_data:
            cb_config = config_data['circuit_breaker']
            self.circuit_breaker.failure_threshold = max(1, int(cb_config.get('failure_threshold', self.circuit_breaker.failure_threshold)))
            self.circuit_breaker.recovery_timeout = max(1.0, float(cb_config.get('recovery_timeout', self.circuit_breaker.recovery_timeout)))
        
        # Validate health config
        if 'health' in config_data:
            health_config = config_data['health']
            self.health.check_interval = max(5.0, float(health_config.get('check_interval', self.health.check_interval)))
            self.health.cpu_threshold = max(0.0, min(100.0, float(health_config.get('cpu_threshold', self.health.cpu_threshold))))
            self.health.memory_threshold = max(0.0, min(100.0, float(health_config.get('memory_threshold', self.health.memory_threshold))))
            self.health.disk_threshold = max(0.0, min(100.0, float(health_config.get('disk_threshold', self.health.disk_threshold))))
        
        # Validate metrics config
        if 'metrics' in config_data:
            metrics_config = config_data['metrics']
            self.metrics.enabled = bool(metrics_config.get('enabled', self.metrics.enabled))
            self.metrics.prometheus_enabled = bool(metrics_config.get('prometheus_enabled', self.metrics.prometheus_enabled))
            self.metrics.prometheus_port = max(1, min(65535, int(metrics_config.get('prometheus_port', self.metrics.prometheus_port))))
        
        # Validate logging config
        if 'logging' in config_data:
            logging_config = config_data['logging']
            self.logging.level = str(logging_config.get('level', self.logging.level)).upper()
            self.logging.file_path = logging_config.get('file_path') if logging_config.get('file_path') else None
        
        # Validate server config
        if 'server' in config_data:
            server_config = config_data['server']
            self.server.host = str(server_config.get('host', self.server.host))
            self.server.port = max(1, min(65535, int(server_config.get('port', self.server.port))))
            self.server.transport = str(server_config.get('transport', self.server.transport)).lower()
            self.server.workers = max(1, int(server_config.get('workers', self.server.workers)))
        
        # Validate tool config
        if 'tool' in config_data:
            tool_config = config_data['tool']
            self.tool.default_timeout = max(1, int(tool_config.get('default_timeout', self.tool.default_timeout)))
            self.tool.default_concurrency = max(1, int(tool_config.get('default_concurrency', self.tool.default_concurrency)))
        
        # Store raw config data
        self._config_data = config_data
        
        log.info("config.loaded_successfully")
        
    except Exception as e:
        log.error("config.validation_failed error=%s", str(e))
        # Keep defaults if validation fails
```
**Observation**: Good configuration validation with proper bounds checking. No issues found.

### Configuration Change Detection
```python
def check_for_changes(self) -> bool:
    """Check if configuration file has been modified."""
    if not self.config_path:
        return False
    
    try:
        current_mtime = os.path.getmtime(self.config_path)
        if current_mtime != self.last_modified:
            self.last_modified = current_mtime
            return True
    except OSError:
        pass
    
    return False

def reload_config(self):
    """Reload configuration if file has changed."""
    if self.check_for_changes():
        log.info("config.reloading_changes_detected")
        self.load_config()
        return True
    return False
```
**Observation**: Good configuration change detection and reload functionality. No issues found.

### Sensitive Data Handling
```python
def get_sensitive_keys(self) -> List[str]:
    """Get list of sensitive configuration keys that should be redacted."""
    return [
        'database.url',
        'security.api_key',
        'security.secret_key',
        'logging.file_path'  # May contain sensitive paths
    ]

def redact_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
    """Redact sensitive data from configuration for logging."""
    sensitive_keys = self.get_sensitive_keys()
    redacted_data = data.copy()
    
    for key in sensitive_keys:
        if '.' in key:
            section, subkey = key.split('.', 1)
            if section in redacted_data and isinstance(redacted_data[section], dict):
                if subkey in redacted_data[section]:
                    redacted_data[section][subkey] = "***REDACTED***"
        else:
            if key in redacted_data:
                redacted_data[key] = "***REDACTED***"
    
    return redacted_data
```
**Observation**: Good sensitive data handling with proper redaction. No issues found.

### Configuration Serialization
```python
def to_dict(self, redact_sensitive: bool = True) -> Dict[str, Any]:
    """Convert configuration to dictionary."""
    config_dict = {
        'database': asdict(self.database),
        'security': asdict(self.security),
        'circuit_breaker': asdict(self.circuit_breaker),
        'health': asdict(self.health),
        'metrics': asdict(self.metrics),
        'logging': asdict(self.logging),
        'server': asdict(self.server),
        'tool': asdict(self.tool)
    }
    
    if redact_sensitive:
        config_dict = self.redact_sensitive_data(config_dict)
    
    return config_dict

def save_config(self, file_path: Optional[str] = None):
    """Save current configuration to file."""
    save_path = file_path or self.config_path
    if not save_path:
        raise ValueError("No config file path specified")
    
    try:
        config_dict = self.to_dict(redact_sensitive=False)
        
        file_path_obj = Path(save_path)
        file_path_obj.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path_obj, 'w', encoding='utf-8') as f:
            if file_path_obj.suffix.lower() in ['.yaml', '.yml']:
                yaml.dump(config_dict, f, default_flow_style=False, indent=2)
            else:
                json.dump(config_dict, f, indent=2)
        
        log.info("config.saved_successfully path=%s", save_path)
        
    except Exception as e:
        log.error("config.save_failed path=%s error=%s", save_path, str(e))
        raise
```
**Observation**: Good configuration serialization with support for both JSON and YAML formats. No issues found.

### Configuration Access Methods
```python
def get_section(self, section_name: str) -> Any:
    """Get a specific configuration section."""
    return getattr(self, section_name, None)

def get_value(self, section_name: str, key: str, default=None):
    """Get a specific configuration value."""
    section = self.get_section(section_name)
    if section and hasattr(section, key):
        return getattr(section, key)
    return default

def __str__(self) -> str:
    """String representation with sensitive data redacted."""
    config_dict = self.to_dict(redact_sensitive=True)
    return json.dumps(config_dict, indent=2)
```
**Observation**: Good configuration access methods with proper defaults. No issues found.

### Global Configuration Instance
```python
# Global configuration instance
_config_instance = None

def get_config(config_path: Optional[str] = None) -> MCPConfig:
    """Get the global configuration instance."""
    global _config_instance
    if _config_instance is None:
        _config_instance = MCPConfig(config_path)
    return _config_instance

def reload_config():
    """Reload the global configuration."""
    global _config_instance
    if _config_instance is not None:
        _config_instance.reload_config()
```
**Observation**: Good global configuration instance management. No issues found.

## 1.3 mcp_server/metrics.py

### Imports and Dependencies
```python
import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field

# Graceful Prometheus dependency handling
try:
    from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest
    from prometheus_client.core import CollectorRegistry
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

log = logging.getLogger(__name__)
```
**Observation**: All necessary imports are present and well-organized. Good graceful handling of optional dependencies. No issues found.

### Tool Execution Metrics Dataclass
```python
@dataclass
class ToolExecutionMetrics:
    """Metrics for tool execution with validation."""
    tool_name: str
    execution_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0
    total_execution_time: float = 0.0
    min_execution_time: float = float('inf')
    max_execution_time: float = 0.0
    last_execution_time: Optional[datetime] = None
    
    def record_execution(self, success: bool, execution_time: float, timed_out: bool = False):
        """Record a tool execution with validation."""
        # Validate execution time
        execution_time = max(0.0, float(execution_time))
        
        self.execution_count += 1
        self.total_execution_time += execution_time
        
        if execution_time < self.min_execution_time:
            self.min_execution_time = execution_time
        if execution_time > self.max_execution_time:
            self.max_execution_time = execution_time
        
        self.last_execution_time = datetime.now()
        
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
        
        if timed_out:
            self.timeout_count += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for this tool."""
        if self.execution_count == 0:
            return {
                "tool_name": self.tool_name,
                "execution_count": 0,
                "success_rate": 0.0,
                "average_execution_time": 0.0,
                "min_execution_time": 0.0,
                "max_execution_time": 0.0
            }
        
        # Prevent division by zero
        avg_execution_time = self.total_execution_time / self.execution_count
        success_rate = (self.success_count / self.execution_count) * 100
        
        return {
            "tool_name": self.tool_name,
            "execution_count": self.execution_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "timeout_count": self.timeout_count,
            "success_rate": round(success_rate, 2),
            "average_execution_time": round(avg_execution_time, 4),
            "min_execution_time": round(self.min_execution_time, 4) if self.min_execution_time != float('inf') else 0.0,
            "max_execution_time": round(self.max_execution_time, 4),
            "last_execution_time": self.last_execution_time.isoformat() if self.last_execution_time else None
        }
```
**Observation**: Well-defined metrics dataclass with proper validation and statistics calculation. No issues found.

### System Metrics Class
```python
class SystemMetrics:
    """System-level metrics with thread safety."""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.request_count = 0
        self.error_count = 0
        self.active_connections = 0
        self._lock = None  # Could use threading.Lock if needed
    
    def increment_request_count(self):
        """Increment request count."""
        self.request_count += 1
    
    def increment_error_count(self):
        """Increment error count."""
        self.error_count += 1
    
    def increment_active_connections(self):
        """Increment active connections."""
        self.active_connections += 1
    
    def decrement_active_connections(self):
        """Decrement active connections."""
        self.active_connections = max(0, self.active_connections - 1)
    
    def get_uptime(self) -> float:
        """Get uptime in seconds."""
        return (datetime.now() - self.start_time).total_seconds()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get system statistics."""
        uptime = self.get_uptime()
        error_rate = (self.error_count / self.request_count * 100) if self.request_count > 0 else 0
        
        return {
            "uptime_seconds": uptime,
            "uptime_formatted": str(timedelta(seconds=int(uptime))),
            "request_count": self.request_count,
            "error_count": self.error_count,
            "error_rate": round(error_rate, 2),
            "active_connections": self.active_connections,
            "start_time": self.start_time.isoformat()
        }
```
**Observation**: Well-defined system metrics class with proper statistics calculation. No issues found.

### Prometheus Metrics Class
```python
class PrometheusMetrics:
    """Prometheus metrics collection with graceful degradation."""
    
    def __init__(self):
        if not PROMETHEUS_AVAILABLE:
            log.warning("prometheus.unavailable")
            self.registry = None
            return
        
        try:
            self.registry = CollectorRegistry()
            
            # Tool execution metrics
            self.tool_execution_counter = Counter(
                'mcp_tool_execution_total',
                'Total tool executions',
                ['tool', 'status', 'error_type'],
                registry=self.registry
            )
            
            self.tool_execution_histogram = Histogram(
                'mcp_tool_execution_seconds',
                'Tool execution time in seconds',
                ['tool'],
                registry=self.registry
            )
            
            self.tool_active_gauge = Gauge(
                'mcp_tool_active',
                'Currently active tool executions',
                ['tool'],
                registry=self.registry
            )
            
            # System metrics
            self.system_request_counter = Counter(
                'mcp_system_requests_total',
                'Total system requests',
                registry=self.registry
            )
            
            self.system_error_counter = Counter(
                'mcp_system_errors_total',
                'Total system errors',
                ['error_type'],
                registry=self.registry
            )
            
            self.system_active_connections = Gauge(
                'mcp_system_active_connections',
                'Currently active connections',
                registry=self.registry
            )
            
            self.system_uptime_gauge = Gauge(
                'mcp_system_uptime_seconds',
                'System uptime in seconds',
                registry=self.registry
            )
            
            log.info("prometheus.metrics_initialized")
            
        except Exception as e:
            log.error("prometheus.initialization_failed error=%s", str(e))
            self.registry = None
    
    def record_tool_execution(self, tool_name: str, success: bool, execution_time: float, 
                             error_type: str = None):
        """Record tool execution metrics."""
        if not PROMETHEUS_AVAILABLE or not self.registry:
            return
        
        try:
            # Validate execution time
            execution_time = max(0.0, float(execution_time))
            
            status = 'success' if success else 'failure'
            self.tool_execution_counter.labels(
                tool=tool_name,
                status=status,
                error_type=error_type or 'none'
            ).inc()
            
            self.tool_execution_histogram.labels(tool=tool_name).observe(execution_time)
            
        except Exception as e:
            log.warning("prometheus.tool_execution_error error=%s", str(e))
    
    def increment_tool_active(self, tool_name: str):
        """Increment active tool gauge."""
        if PROMETHEUS_AVAILABLE and self.registry and self.tool_active_gauge:
            try:
                self.tool_active_gauge.labels(tool=tool_name).inc()
            except Exception as e:
                log.warning("prometheus.increment_active_error error=%s", str(e))
    
    def decrement_tool_active(self, tool_name: str):
        """Decrement active tool gauge."""
        if PROMETHEUS_AVAILABLE and self.registry and self.tool_active_gauge:
            try:
                self.tool_active_gauge.labels(tool=tool_name).dec()
            except Exception as e:
                log.warning("prometheus.decrement_active_error error=%s", str(e))
    
    def increment_system_request(self):
        """Increment system request counter."""
        if PROMETHEUS_AVAILABLE and self.registry and self.system_request_counter:
            try:
                self.system_request_counter.inc()
            except Exception as e:
                log.warning("prometheus.increment_request_error error=%s", str(e))
    
    def increment_system_error(self, error_type: str = "unknown"):
        """Increment system error counter."""
        if PROMETHEUS_AVAILABLE and self.registry and self.system_error_counter:
            try:
                self.system_error_counter.labels(error_type=error_type).inc()
            except Exception as e:
                log.warning("prometheus.increment_error_error error=%s", str(e))
    
    def set_active_connections(self, count: int):
        """Set active connections gauge."""
        if PROMETHEUS_AVAILABLE and self.registry and self.system_active_connections:
            try:
                self.system_active_connections.set(count)
            except Exception as e:
                log.warning("prometheus.set_connections_error error=%s", str(e))
    
    def set_uptime(self, uptime: float):
        """Set uptime gauge."""
        if PROMETHEUS_AVAILABLE and self.registry and self.system_uptime_gauge:
            try:
                self.system_uptime_gauge.set(uptime)
            except Exception as e:
                log.warning("prometheus.set_uptime_error error=%s", str(e))
    
    def generate_metrics(self) -> Optional[bytes]:
        """Generate Prometheus metrics output."""
        if not PROMETHEUS_AVAILABLE or not self.registry:
            return None
        
        try:
            return generate_latest(self.registry)
        except Exception as e:
            log.warning("prometheus.generate_error error=%s", str(e))
            return None
```
**Observation**: Well-defined Prometheus metrics class with proper error handling and graceful degradation. No issues found.

# 2. Code Quality Assessment Report

## 2.1 Overall Assessment

The MCP server codebase demonstrates a high level of code quality with strong emphasis on security, resilience, and observability. The code follows modern Python best practices and is well-structured with clear separation of concerns. The implementation shows evidence of thoughtful design with production considerations in mind.

## 2.2 Strengths

### 2.2.1 Code Structure and Organization
- Clear separation of concerns with dedicated modules for tools, configuration, and metrics.
- Consistent coding style and naming conventions throughout the codebase.
- Well-documented classes and methods with clear docstrings.
- Logical organization of code with related functionality grouped together.

### 2.2.2 Error Handling
- Comprehensive error handling with appropriate exception catching and logging.
- Graceful degradation when optional dependencies are not available.
- Detailed error context with recovery suggestions.
- Proper validation of inputs and configuration values.

### 2.2.3 Security
- Strict input validation to prevent command injection and other security vulnerabilities.
- Proper sanitization of user inputs and arguments.
- Secure handling of sensitive data with redaction for logging.
- Restriction of targets to private networks and lab hostnames.

### 2.2.4 Resilience
- Circuit breaker pattern implementation to prevent cascading failures.
- Timeout handling for all operations to prevent hanging.
- Concurrency control to prevent resource exhaustion.
- Proper resource management with cleanup in error cases.

### 2.2.5 Observability
- Comprehensive metrics collection for both tool execution and system health.
- Prometheus integration with graceful degradation.
- Structured logging with correlation IDs for tracing.
- Detailed error reporting with context.

## 2.3 Issues Found

### 2.3.1 Critical Issues
None found.

### 2.3.2 Major Issues

#### base_tool.py
1. **Execution Time Calculation**: The execution time is calculated twice in the `run` method - once for metrics recording and once for the result. This could lead to slightly different values.
   - **Impact**: Inconsistent metrics reporting.
   - **Recommendation**: Calculate the execution time once and reuse it.

2. **Metrics Active Gauge**: The `start_execution` and `end_execution` methods in the `ToolMetrics` class are defined but never called in the code. This means the active gauge will never be updated.
   - **Impact**: Missing metrics for active tool executions.
   - **Recommendation**: Call these methods at the appropriate points in the tool execution lifecycle.

#### config.py
1. **Missing Configuration Validation**: Some configuration options are referenced in the environment variable mappings but not in the validation logic (e.g., `database.pool_timeout`, `database.pool_recycle`).
   - **Impact**: Invalid configuration values could lead to unexpected behavior or errors.
   - **Recommendation**: Add validation for all configuration options.

### 2.3.3 Minor Issues

#### base_tool.py
1. **Minimum Execution Time**: The minimum execution time is set to 0.001 seconds. While this prevents division by zero, it might skew metrics for very fast operations.
   - **Impact**: Potentially inaccurate metrics for very fast operations.
   - **Recommendation**: Consider using a more sophisticated approach for handling very fast operations.

2. **Timeout Error Output**: The timeout error returns a hardcoded stderr message "process timed out" but the stdout is empty. It might be more useful to include any partial output that was generated before the timeout.
   - **Impact**: Loss of potentially useful debugging information.
   - **Recommendation**: Capture and include partial output in timeout errors.

3. **Environment Variables**: The environment variables for subprocess execution are hardcoded to a minimal set. While this is good for security, it might cause issues for tools that require specific environment variables to function correctly.
   - **Impact**: Tools might not function correctly due to missing environment variables.
   - **Recommendation**: Make the environment variables configurable or allow tools to specify additional environment variables.

4. **Metrics Prefix**: The metrics names are hardcoded with an 'mcp_' prefix. This might cause conflicts if multiple MCP servers are running in the same environment.
   - **Impact**: Potential metric name conflicts in multi-instance deployments.
   - **Recommendation**: Make the metrics prefix configurable.

5. **Flag Validation**: The flag validation only checks if the flag starts with one of the allowed prefixes. This means that if `--verbose` is allowed, `--verbose-extra` would also be allowed, which might not be intended.
   - **Impact**: Potentially unintended flags could be passed to tools.
   - **Recommendation**: Consider using exact flag matching or more sophisticated flag validation.

#### config.py
1. **Transport Validation**: The server transport is validated to be either "stdio" or "http", but this validation is case-sensitive.
   - **Impact**: Configuration with different case (e.g., "HTTP") would be rejected.
   - **Recommendation**: Make the transport validation case-insensitive.

#### metrics.py
1. **Thread Safety**: The `SystemMetrics` class has a placeholder for a lock but doesn't use it. In a multi-threaded environment, this could lead to race conditions.
   - **Impact**: Potential race conditions in multi-threaded environments.
   - **Recommendation**: Implement proper thread safety using the lock or remove the lock placeholder.

## 2.4 Security Assessment

### 2.4.1 Security Strengths
- Strict input validation for targets and arguments.
- Proper sanitization of user inputs to prevent command injection.
- Secure handling of sensitive data with redaction for logging.
- Restriction of targets to private networks and lab hostnames.
- Minimal environment for subprocess execution.

### 2.4.2 Security Considerations
- No authentication or authorization mechanism is visible in the codebase.
- No audit logging for security events.
- No integration with dedicated secrets management systems.

### 2.4.3 Security Recommendations
1. **Authentication/Authorization**: Implement authentication and authorization mechanisms to control access to tools.
2. **Audit Logging**: Add comprehensive audit logging for security events.
3. **Secrets Management**: Integrate with dedicated secrets management systems.

## 2.5 Performance Assessment

### 2.5.1 Performance Strengths
- Concurrency control to prevent resource exhaustion.
- Timeout handling for all operations to prevent hanging.
- Efficient metrics collection with minimal performance impact.
- Proper resource management with cleanup in error cases.

### 2.5.2 Performance Considerations
- The metrics collection could have a small performance impact, especially in high-throughput scenarios.
- The circuit breaker pattern adds some overhead to tool execution.

### 2.5.3 Performance Recommendations
1. **Metrics Optimization**: Consider optimizing metrics collection for high-throughput scenarios.
2. **Circuit Breaker Tuning**: Tune circuit breaker parameters based on actual usage patterns.

## 2.6 Testing Recommendations

1. **Unit Tests**: Implement comprehensive unit tests for all classes and methods.
2. **Integration Tests**: Implement integration tests for the overall system.
3. **Performance Tests**: Implement performance tests to validate scalability and identify bottlenecks.
4. **Security Tests**: Implement security tests to validate input validation and sanitization.

## 2.7 Documentation Recommendations

1. **API Documentation**: Create comprehensive API documentation for the MCP server.
2. **Developer Guide**: Create a developer guide for extending the server with new tools.
3. **Deployment Guide**: Create a deployment guide for deploying and configuring the server.
4. **Architecture Documentation**: Create architecture documentation explaining the design decisions and patterns used.

# 3. Project Architecture Document

## 3.1 Introduction

### 3.1.1 Purpose
This document provides a comprehensive overview of the MCP (Model Context Protocol) server architecture, design patterns, and implementation details. It serves as a guide for understanding the codebase and extending it with new tools and functionality.

### 3.1.2 Scope
This document covers the core architecture of the MCP server, including the base tool implementation, configuration management, and metrics collection. It provides guidance for extending the server with new tools and customizing its behavior.

### 3.1.3 Audience
This document is intended for developers, architects, and system administrators who need to understand, extend, or deploy the MCP server.

## 3.2 System Overview

### 3.2.1 Architecture
The MCP server follows a layered architecture with clear separation of concerns:

1. **Tool Layer**: Implements specific tools that extend the base tool functionality.
2. **Base Tool Layer**: Provides the foundation for all tools with common functionality like input validation, error handling, and metrics collection.
3. **Configuration Layer**: Manages configuration for the entire system with validation and hot-reload capabilities.
4. **Metrics Layer**: Collects and exports metrics for monitoring and observability.

### 3.2.2 Design Patterns
The MCP server employs several design patterns:

1. **Abstract Factory Pattern**: The `MCPBaseTool` class serves as an abstract factory for creating specific tool implementations.
2. **Circuit Breaker Pattern**: Used to handle failures and prevent cascading failures.
3. **Observer Pattern**: Metrics collection observes tool execution and system events.
4. **Strategy Pattern**: Different configuration strategies (file, environment variables).
5. **Singleton Pattern**: Global configuration instance.

### 3.2.3 Key Components
The key components of the MCP server are:

1. **MCPBaseTool**: Abstract base class for all tools.
2. **MCPConfig**: Configuration management class.
3. **ToolMetrics**: Metrics collection for tool execution.
4. **SystemMetrics**: System-level metrics collection.
5. **PrometheusMetrics**: Prometheus integration for metrics export.

## 3.3 Component Details

### 3.3.1 MCPBaseTool

#### Purpose
The `MCPBaseTool` class provides the foundation for implementing MCP tools with security, monitoring, and resilience features.

#### Key Features
- Input validation and sanitization
- Error handling with recovery suggestions
- Circuit breaker pattern for fault tolerance
- Metrics collection for observability
- Concurrency control for resource management
- Timeout handling for preventing hanging operations

#### Usage
To implement a new tool, create a class that extends `MCPBaseTool` and implement the required methods:

```python
class MyTool(MCPBaseTool):
    command_name = "mytool"
    allowed_flags = ["-v", "--verbose", "-o", "--output"]
    
    def __init__(self):
        super().__init__()
```

#### Configuration
The `MCPBaseTool` class can be configured through class variables:

- `command_name`: Name of the binary to execute (required).
- `allowed_flags`: Whitelist of flags to allow (optional).
- `concurrency`: Concurrency limit per tool instance (default: 2).
- `default_timeout_sec`: Default timeout for a run in seconds (default: 300).
- `circuit_breaker_failure_threshold`: Failure threshold for circuit breaker (default: 5).
- `circuit_breaker_recovery_timeout`: Recovery timeout for circuit breaker (default: 60.0).
- `circuit_breaker_expected_exception`: Expected exceptions for circuit breaker (default: (Exception,)).

### 3.3.2 MCPConfig

#### Purpose
The `MCPConfig` class manages configuration for the MCP server with validation, hot-reload, and sensitive data handling.

#### Key Features
- Support for both JSON and YAML configuration files
- Environment variable overrides with type conversion
- Validation of configuration values
- Hot-reload capability with change detection
- Sensitive data redaction for logging

#### Usage
To use the configuration system, get the global configuration instance:

```python
from mcp_server.config import get_config

config = get_config("/path/to/config.yaml")
```

#### Configuration Sections
The configuration is divided into several sections:

1. **Database**: Database connection settings.
2. **Security**: Security settings like allowed targets and resource limits.
3. **Circuit Breaker**: Circuit breaker settings for fault tolerance.
4. **Health**: Health check settings for monitoring.
5. **Metrics**: Metrics collection settings.
6. **Logging**: Logging configuration.
7. **Server**: Server settings like host and port.
8. **Tool**: Tool-specific settings.

#### Environment Variables
Configuration can be overridden using environment variables. The following environment variables are supported:

- `MCP_DATABASE_URL`: Database URL.
- `MCP_DATABASE_POOL_SIZE`: Database connection pool size.
- `MCP_SECURITY_MAX_ARGS_LENGTH`: Maximum argument length.
- `MCP_SECURITY_TIMEOUT_SECONDS`: Default timeout in seconds.
- `MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD`: Circuit breaker failure threshold.
- `MCP_CIRCUIT_BREAKER_RECOVERY_TIMEOUT`: Circuit breaker recovery timeout.
- `MCP_HEALTH_CHECK_INTERVAL`: Health check interval.
- `MCP_HEALTH_CPU_THRESHOLD`: CPU usage threshold for health checks.
- `MCP_METRICS_ENABLED`: Enable metrics collection.
- `MCP_METRICS_PROMETHEUS_PORT`: Prometheus metrics port.
- `MCP_LOGGING_LEVEL`: Logging level.
- `MCP_LOGGING_FILE_PATH`: Log file path.
- `MCP_SERVER_HOST`: Server host.
- `MCP_SERVER_PORT`: Server port.
- `MCP_SERVER_TRANSPORT`: Server transport (stdio or http).
- `MCP_TOOL_DEFAULT_TIMEOUT`: Default tool timeout.

### 3.3.3 Metrics Collection

#### Purpose
The metrics collection system provides observability into tool execution and system health.

#### Key Features
- Tool-specific metrics (execution count, success rate, execution time)
- System metrics (uptime, request count, error rate, active connections)
- Prometheus integration with graceful degradation
- Validation of metric values to ensure data integrity

#### Components
The metrics collection system consists of several components:

1. **ToolExecutionMetrics**: Tracks execution metrics for individual tools.
2. **SystemMetrics**: Tracks system-wide metrics.
3. **PrometheusMetrics**: Integration with Prometheus for metrics export.

#### Usage
To use the metrics collection system, create instances of the appropriate metrics classes:

```python
from mcp_server.metrics import ToolExecutionMetrics, SystemMetrics, PrometheusMetrics

tool_metrics = ToolExecutionMetrics("mytool")
system_metrics = SystemMetrics()
prometheus_metrics = PrometheusMetrics()
```

#### Metrics Collected
The following metrics are collected:

1. **Tool Execution Metrics**:
   - Execution count
   - Success count
   - Failure count
   - Timeout count
   - Total execution time
   - Minimum execution time
   - Maximum execution time
   - Last execution time

2. **System Metrics**:
   - Uptime
   - Request count
   - Error count
   - Active connections
   - Error rate

3. **Prometheus Metrics**:
   - Tool execution counter
   - Tool execution histogram
   - Tool active gauge
   - System request counter
   - System error counter
   - System active connections gauge
   - System uptime gauge

## 3.4 Extending the MCP Server

### 3.4.1 Adding New Tools

#### Overview
To add a new tool to the MCP server, create a class that extends `MCPBaseTool` and implement the required methods.

#### Step-by-Step Guide
1. Create a new Python file for your tool in the `mcp_server/tools` directory.
2. Import the necessary modules:
   ```python
   from mcp_server.base_tool import MCPBaseTool, ToolInput, ToolOutput
   ```

3. Create a class that extends `MCPBaseTool`:
   ```python
   class MyTool(MCPBaseTool):
       command_name = "mytool"
       allowed_flags = ["-v", "--verbose", "-o", "--output"]
       concurrency = 2
       default_timeout_sec = 30
   ```

4. Implement any custom methods or override existing methods as needed.

5. Register your tool with the MCP server by adding it to the tool registry.

#### Example
Here's an example of a simple tool that extends `MCPBaseTool`:

```python
from mcp_server.base_tool import MCPBaseTool, ToolInput, ToolOutput

class PingTool(MCPBaseTool):
    command_name = "ping"
    allowed_flags = ["-c", "-i", "-W", "-t"]
    concurrency = 5
    default_timeout_sec = 10
```

### 3.4.2 Customizing Configuration

#### Overview
The MCP server configuration can be customized through configuration files and environment variables.

#### Configuration File
Create a configuration file in JSON or YAML format:

```yaml
database:
  url: "postgresql://user:password@localhost/mcp"
  pool_size: 20
  max_overflow: 30

security:
  max_args_length: 4096
  max_output_size: 2097152
  timeout_seconds: 600
  concurrency_limit: 5

circuit_breaker:
  failure_threshold: 10
  recovery_timeout: 120.0

metrics:
  enabled: true
  prometheus_enabled: true
  prometheus_port: 9091

logging:
  level: "DEBUG"
  file_path: "/var/log/mcp/server.log"

server:
  host: "0.0.0.0"
  port: 8081
  transport: "http"
  workers: 4

tool:
  default_timeout: 600
  default_concurrency: 5
```

#### Environment Variables
Override configuration values using environment variables:

```bash
export MCP_SERVER_PORT=8081
export MCP_LOGGING_LEVEL=DEBUG
export MCP_METRICS_PROMETHEUS_PORT=9091
```

### 3.4.3 Adding Custom Metrics

#### Overview
Custom metrics can be added to track specific aspects of tool execution or system health.

#### Step-by-Step Guide
1. Create a new metrics class that extends the appropriate base class:
   ```python
   from mcp_server.metrics import ToolExecutionMetrics
   
   class CustomToolMetrics(ToolExecutionMetrics):
       def __init__(self, tool_name: str):
           super().__init__(tool_name)
           self.custom_metric = 0
       
       def record_custom_event(self):
           self.custom_metric += 1
   ```

2. Use your custom metrics class in your tool:
   ```python
   class MyTool(MCPBaseTool):
       def __init__(self):
           super().__init__()
           self.custom_metrics = CustomToolMetrics(self.tool_name)
   ```

3. Record custom metrics as needed:
   ```python
   self.custom_metrics.record_custom_event()
   ```

#### Example
Here's an example of a custom metrics class:

```python
from mcp_server.metrics import ToolExecutionMetrics
from typing import Dict, Any

class NetworkToolMetrics(ToolExecutionMetrics):
    def __init__(self, tool_name: str):
        super().__init__(tool_name)
        self.bytes_sent = 0
        self.bytes_received = 0
        self.connection_count = 0
    
    def record_bytes_sent(self, count: int):
        self.bytes_sent += count
    
    def record_bytes_received(self, count: int):
        self.bytes_received += count
    
    def record_connection(self):
        self.connection_count += 1
    
    def get_stats(self) -> Dict[str, Any]:
        stats = super().get_stats()
        stats.update({
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "connection_count": self.connection_count
        })
        return stats
```

### 3.4.4 Adding Custom Error Types

#### Overview
Custom error types can be added to provide more specific error handling and recovery suggestions.

#### Step-by-Step Guide
1. Add new error types to the `ToolErrorType` enum:
   ```python
   class ToolErrorType(Enum):
       # Existing error types...
       NETWORK_ERROR = "network_error"
       AUTHENTICATION_ERROR = "authentication_error"
   ```

2. Use your custom error types in error handling:
   ```python
   error_context = ErrorContext(
       error_type=ToolErrorType.NETWORK_ERROR,
       message="Network connection failed",
       recovery_suggestion="Check network connectivity and try again",
       timestamp=datetime.now(),
       tool_name=self.tool_name,
       target=inp.target,
       metadata={}
   )
   ```

#### Example
Here's an example of adding custom error types:

```python
from mcp_server.base_tool import ToolErrorType, ErrorContext
from datetime import datetime

# Add custom error types
class CustomToolErrorType(Enum):
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    QUOTA_EXCEEDED = "quota_exceeded"
    INVALID_RESPONSE = "invalid_response"

# Use custom error types
error_context = ErrorContext(
    error_type=CustomToolErrorType.RATE_LIMIT_EXCEEDED,
    message="Rate limit exceeded",
    recovery_suggestion="Wait before making another request",
    timestamp=datetime.now(),
    tool_name=self.tool_name,
    target=inp.target,
    metadata={"retry_after": "60s"}
)
```

## 3.5 Best Practices

### 3.5.1 Tool Implementation
1. **Input Validation**: Always validate inputs and sanitize user-provided data.
2. **Error Handling**: Implement comprehensive error handling with recovery suggestions.
3. **Resource Management**: Properly manage resources and clean up in error cases.
4. **Concurrency**: Be mindful of concurrency and use appropriate synchronization mechanisms.
5. **Timeouts**: Set appropriate timeouts for all operations to prevent hanging.

### 3.5.2 Configuration Management
1. **Validation**: Validate all configuration values and provide sensible defaults.
2. **Sensitive Data**: Properly handle sensitive data and redact it for logging.
3. **Hot-Reload**: Implement hot-reload capability for configuration changes.
4. **Environment Variables**: Support environment variable overrides for deployment flexibility.

### 3.5.3 Metrics Collection
1. **Relevance**: Collect metrics that are relevant and useful for monitoring and debugging.
2. **Performance**: Minimize the performance impact of metrics collection.
3. **Consistency**: Use consistent naming conventions for metrics.
4. **Cardinality**: Be mindful of metric cardinality to avoid excessive resource usage.

### 3.5.4 Security
1. **Input Validation**: Validate all inputs and sanitize user-provided data.
2. **Least Privilege**: Follow the principle of least privilege for all operations.
3. **Secure Defaults**: Use secure defaults for all configuration options.
4. **Audit Logging**: Implement comprehensive audit logging for security events.

## 3.6 Deployment Considerations

### 3.6.1 Environment Configuration
1. **Development**: Use development-specific configuration with verbose logging and debugging features.
2. **Testing**: Use testing-specific configuration with mock services and controlled environments.
3. **Production**: Use production-specific configuration with optimized settings and enhanced security.

### 3.6.2 Scaling
1. **Horizontal Scaling**: Design for horizontal scaling with stateless components.
2. **Load Balancing**: Use load balancing to distribute traffic across multiple instances.
3. **Caching**: Implement caching for frequently accessed resources.
4. **Database Scaling**: Consider database scaling strategies for high-traffic scenarios.

### 3.6.3 Monitoring
1. **Metrics**: Collect and monitor metrics for system health and performance.
2. **Logging**: Implement centralized logging for aggregation and analysis.
3. **Alerting**: Set up alerting for critical events and anomalies.
4. **Distributed Tracing**: Implement distributed tracing for request tracking.

### 3.6.4 Security
1. **Authentication**: Implement authentication mechanisms to control access.
2. **Authorization**: Implement authorization mechanisms to control permissions.
3. **Encryption**: Use encryption for sensitive data in transit and at rest.
4. **Vulnerability Management**: Implement regular vulnerability scanning and patching.

## 3.7 Future Enhancements

### 3.7.1 Authentication and Authorization
1. **User Authentication**: Implement user authentication mechanisms.
2. **Role-Based Access Control**: Implement role-based access control for tools.
3. **API Key Management**: Implement API key management for programmatic access.

### 3.7.2 Advanced Features
1. **Tool Chaining**: Implement tool chaining for complex workflows.
2. **Result Caching**: Implement result caching for improved performance.
3. **Async Processing**: Implement async processing for long-running operations.

### 3.7.3 Observability
1. **Distributed Tracing**: Implement distributed tracing for request tracking.
2. **Custom Dashboards**: Create custom dashboards for monitoring and visualization.
3. **Anomaly Detection**: Implement anomaly detection for proactive issue identification.

### 3.7.4 Performance Optimization
1. **Connection Pooling**: Implement connection pooling for improved performance.
2. **Resource Optimization**: Optimize resource usage for high-traffic scenarios.
3. **Caching Strategies**: Implement advanced caching strategies for frequently accessed resources.

## 3.8 Conclusion

The MCP server architecture provides a solid foundation for building secure, resilient, and observable tools. With its modular design and extensible architecture, it can be easily customized and extended to meet specific requirements. By following the best practices and guidelines outlined in this document, developers can create high-quality tools that integrate seamlessly with the MCP server.

https://chat.z.ai/s/57cb1409-07a4-4d62-ac71-c3da782c5625

Full: https://chat.z.ai/s/57cb1409-07a4-4d62-ac71-c3da782c5625
