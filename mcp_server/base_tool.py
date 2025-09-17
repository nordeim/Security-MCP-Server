# File: base_tool.py
"""
Enhanced MCP Base Tool with circuit breaker, metrics, and advanced error handling.
Production-ready implementation with all critical fixes applied.
"""
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

# Pydantic v1/v2 compatibility shim
try: # Pydantic v2
    from pydantic import BaseModel, field_validator
    _PD_V2 = True
except ImportError: # Pydantic v1
    from pydantic import BaseModel, validator as field_validator # type: ignore
    _PD_V2 = False

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

log = logging.getLogger(__name__)

# Conservative denylist for arg tokens we never want to see (even though shell=False)
_DENY_CHARS = re.compile(r"[;&|`$><\n\r]") # control/meta chars
_TOKEN_ALLOWED = re.compile(r"^[A-Za-z0-9.:/=+-,@%]+$") # reasonably safe superset
_MAX_ARGS_LEN = int(os.getenv("MCP_MAX_ARGS_LEN", "2048"))
_MAX_STDOUT_BYTES = int(os.getenv("MCP_MAX_STDOUT_BYTES", "1048576")) # 1 MiB
_MAX_STDERR_BYTES = int(os.getenv("MCP_MAX_STDERR_BYTES", "262144")) # 256 KiB
_DEFAULT_TIMEOUT_SEC = float(os.getenv("MCP_DEFAULT_TIMEOUT_SEC", "300")) # 5 minutes
_DEFAULT_CONCURRENCY = int(os.getenv("MCP_DEFAULT_CONCURRENCY", "2"))

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

class ToolErrorType(Enum):
    """Enhanced error taxonomy with recovery suggestions."""
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"
    VALIDATION_ERROR = "validation_error"
    EXECUTION_ERROR = "execution_error"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"
    UNKNOWN = "unknown"

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
    
    def _ensure_semaphore(self) -> asyncio.Semaphore:
        """Ensure semaphore exists for this tool class."""
        if self.__class__._semaphore is None:
            self.__class__._semaphore = asyncio.Semaphore(self.concurrency)
        return self.__class__._semaphore
    
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
    
    def _resolve_command(self) -> Optional[str]:
        """Resolve command path using shutil.which."""
        return shutil.which(self.command_name)
    
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
