# File: base_tool.py
```python
"""
Enhanced MCP Base Tool with circuit breaker, metrics, and advanced error handling.
Production-ready implementation with proper async support, validation, and resource limits.
"""
import asyncio
import logging
import os
import re
import shlex
import shutil
import time
import contextlib
import inspect
import threading
import sys
import resource
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Optional, Sequence, Dict, Any
from datetime import datetime, timedelta

try:
    from pydantic import BaseModel, Field
    try:
        from pydantic import field_validator
        _PD_V2 = True
    except ImportError:
        from pydantic import validator as field_validator
        _PD_V2 = False
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    
    class BaseModel:
        def __init__(self, **data):
            for k, v in data.items():
                setattr(self, k, v)
        
        def dict(self):
            return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}
    
    def Field(default=None, **kwargs):
        return default
    
    def field_validator(*args, **kwargs):
        def _decorator(func):
            return func
        return _decorator
    
    _PD_V2 = False

try:
    from .circuit_breaker import CircuitBreaker, CircuitBreakerState
except ImportError:
    CircuitBreaker = None
    CircuitBreakerState = None

try:
    from .metrics import ToolMetrics
except ImportError:
    ToolMetrics = None

log = logging.getLogger(__name__)

_DENY_CHARS = re.compile(r"[;&|`$><\n\r]")
_TOKEN_ALLOWED = re.compile(r"^[A-Za-z0-9.:/=+,\-@%_]+$")
_HOSTNAME_PATTERN = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$')
_MAX_ARGS_LEN = int(os.getenv("MCP_MAX_ARGS_LEN", "2048"))
_MAX_STDOUT_BYTES = int(os.getenv("MCP_MAX_STDOUT_BYTES", "1048576"))
_MAX_STDERR_BYTES = int(os.getenv("MCP_MAX_STDERR_BYTES", "262144"))
_DEFAULT_TIMEOUT_SEC = float(os.getenv("MCP_DEFAULT_TIMEOUT_SEC", "300"))
_DEFAULT_CONCURRENCY = int(os.getenv("MCP_DEFAULT_CONCURRENCY", "2"))
_MAX_MEMORY_MB = int(os.getenv("MCP_MAX_MEMORY_MB", "512"))
_MAX_FILE_DESCRIPTORS = int(os.getenv("MCP_MAX_FILE_DESCRIPTORS", "256"))

# Thread-safe semaphore creation lock
_semaphore_lock = threading.Lock()
_semaphore_registry = {}


def _is_private_or_lab(value: str) -> bool:
    """Enhanced validation with hostname format checking."""
    import ipaddress
    v = value.strip()
    
    # Validate .lab.internal hostname format
    if v.endswith(".lab.internal"):
        hostname_part = v[:-len(".lab.internal")]
        if not hostname_part or not _HOSTNAME_PATTERN.match(hostname_part):
            return False
        return True
    
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
    """Tool error types."""
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"
    VALIDATION_ERROR = "validation_error"
    EXECUTION_ERROR = "execution_error"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"
    UNKNOWN = "unknown"


@dataclass
class ErrorContext:
    """Error context with recovery suggestions."""
    error_type: ToolErrorType
    message: str
    recovery_suggestion: str
    timestamp: datetime
    tool_name: str
    target: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class ToolInput(BaseModel):
    """Tool input model with enhanced validation."""
    target: str
    extra_args: str = ""
    timeout_sec: Optional[float] = None
    correlation_id: Optional[str] = None
    
    if PYDANTIC_AVAILABLE:
        if _PD_V2:
            @classmethod
            @field_validator("target", mode='after')
            def _validate_target(cls, v: str) -> str:
                if not _is_private_or_lab(v):
                    raise ValueError("Target must be RFC1918 IPv4 or a .lab.internal hostname (CIDR allowed).")
                return v
            
            @classmethod
            @field_validator("extra_args", mode='after')
            def _validate_extra_args(cls, v: str) -> str:
                v = v or ""
                if len(v) > _MAX_ARGS_LEN:
                    raise ValueError(f"extra_args too long (> {_MAX_ARGS_LEN} bytes)")
                if _DENY_CHARS.search(v):
                    raise ValueError("extra_args contains forbidden metacharacters")
                return v
        else:
            @field_validator("target")
            def _validate_target(cls, v: str) -> str:
                if not _is_private_or_lab(v):
                    raise ValueError("Target must be RFC1918 IPv4 or a .lab.internal hostname (CIDR allowed).")
                return v
            
            @field_validator("extra_args")
            def _validate_extra_args(cls, v: str) -> str:
                v = v or ""
                if len(v) > _MAX_ARGS_LEN:
                    raise ValueError(f"extra_args too long (> {_MAX_ARGS_LEN} bytes)")
                if _DENY_CHARS.search(v):
                    raise ValueError("extra_args contains forbidden metacharacters")
                return v


class ToolOutput(BaseModel):
    """Tool output model."""
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
    metadata: Dict[str, Any] = Field(default_factory=dict) if PYDANTIC_AVAILABLE else {}
    
    def ensure_metadata(self):
        """Ensure metadata is initialized."""
        if self.metadata is None:
            self.metadata = {}


class MCPBaseTool(ABC):
    """Enhanced base class for MCP tools with production-ready features."""
    
    command_name: ClassVar[str]
    allowed_flags: ClassVar[Optional[Sequence[str]]] = None
    concurrency: ClassVar[int] = _DEFAULT_CONCURRENCY
    default_timeout_sec: ClassVar[float] = _DEFAULT_TIMEOUT_SEC
    circuit_breaker_failure_threshold: ClassVar[int] = 5
    circuit_breaker_recovery_timeout: ClassVar[float] = 60.0
    circuit_breaker_expected_exception: ClassVar[tuple] = (Exception,)
    _semaphore: ClassVar[Optional[asyncio.Semaphore]] = None
    
    def __init__(self):
        self.tool_name = self.__class__.__name__
        self._circuit_breaker = None
        self.metrics = None
        self._initialize_metrics()
        self._initialize_circuit_breaker()
    
    def _initialize_metrics(self):
        """Initialize tool metrics."""
        if ToolMetrics is not None:
            try:
                self.metrics = ToolMetrics(self.tool_name)
            except Exception as e:
                log.warning("metrics.initialization_failed tool=%s error=%s", self.tool_name, str(e))
                self.metrics = None
        else:
            self.metrics = None
    
    def _initialize_circuit_breaker(self):
        """Initialize instance-level circuit breaker."""
        if CircuitBreaker is None:
            self._circuit_breaker = None
            return
        
        try:
            self._circuit_breaker = CircuitBreaker(
                failure_threshold=self.circuit_breaker_failure_threshold,
                recovery_timeout=self.circuit_breaker_recovery_timeout,
                expected_exception=self.circuit_breaker_expected_exception,
                name=f"{self.tool_name}_{id(self)}"
            )
        except Exception as e:
            log.error("circuit_breaker.initialization_failed tool=%s error=%s", 
                     self.tool_name, str(e))
            self._circuit_breaker = None
    
    def _ensure_semaphore(self) -> asyncio.Semaphore:
        """Thread-safe semaphore initialization per event loop."""
        global _semaphore_registry
        
        try:
            loop = asyncio.get_running_loop()
            loop_id = id(loop)
        except RuntimeError:
            # Create new loop if needed
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop_id = id(loop)
        
        # Use class name as key combined with loop id
        key = f"{self.__class__.__name__}_{loop_id}"
        
        with _semaphore_lock:
            if key not in _semaphore_registry:
                _semaphore_registry[key] = asyncio.Semaphore(self.concurrency)
            return _semaphore_registry[key]
    
    async def run(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
        """Run tool with circuit breaker, metrics, and resource limits."""
        start_time = time.time()
        correlation_id = inp.correlation_id or str(int(start_time * 1000))
        
        # Record active execution
        if self.metrics:
            self.metrics.increment_active()
        
        try:
            # Check circuit breaker state
            if self._circuit_breaker:
                state = getattr(self._circuit_breaker, 'state', None)
                if state == getattr(CircuitBreakerState, 'OPEN', 'OPEN'):
                    return self._create_circuit_breaker_error(inp, correlation_id)
            
            # Execute with semaphore for concurrency control
            async with self._ensure_semaphore():
                if self._circuit_breaker:
                    if inspect.iscoroutinefunction(getattr(self._circuit_breaker, 'call', None)):
                        result = await self._circuit_breaker.call(
                            self._execute_tool, inp, timeout_sec
                        )
                    else:
                        result = await self._execute_with_sync_breaker(inp, timeout_sec)
                else:
                    result = await self._execute_tool(inp, timeout_sec)
                
                execution_time = time.time() - start_time
                await self._record_metrics(result, execution_time)
                
                result.correlation_id = correlation_id
                result.execution_time = execution_time
                result.ensure_metadata()
                
                return result
                
        except Exception as e:
            return await self._handle_execution_error(e, inp, correlation_id, start_time)
        
        finally:
            # Decrement active execution
            if self.metrics:
                self.metrics.decrement_active()
    
    def _create_circuit_breaker_error(self, inp: ToolInput, correlation_id: str) -> ToolOutput:
        """Create error output for open circuit breaker."""
        error_context = ErrorContext(
            error_type=ToolErrorType.CIRCUIT_BREAKER_OPEN,
            message=f"Circuit breaker is open for {self.tool_name}",
            recovery_suggestion="Wait for recovery timeout or check service health",
            timestamp=datetime.now(),
            tool_name=self.tool_name,
            target=inp.target,
            metadata={"state": str(getattr(self._circuit_breaker, 'state', None))}
        )
        return self._create_error_output(error_context, correlation_id)
    
    async def _execute_with_sync_breaker(self, inp: ToolInput, 
                                         timeout_sec: Optional[float]) -> ToolOutput:
        """Handle sync circuit breaker with async execution."""
        try:
            result = await self._execute_tool(inp, timeout_sec)
            if hasattr(self._circuit_breaker, 'call_succeeded'):
                self._circuit_breaker.call_succeeded()
            return result
        except Exception as e:
            if hasattr(self._circuit_breaker, 'call_failed'):
                self._circuit_breaker.call_failed()
            raise
    
    async def _record_metrics(self, result: ToolOutput, execution_time: float):
        """Record metrics with proper error handling."""
        if not self.metrics:
            return
        
        try:
            success = (result.returncode == 0)
            error_type = result.error_type if not success else None
            
            if hasattr(self.metrics, 'record_execution'):
                # Handle both sync and async versions
                record_func = self.metrics.record_execution
                if inspect.iscoroutinefunction(record_func):
                    await record_func(
                        success=success,
                        execution_time=execution_time,
                        timed_out=result.timed_out,
                        error_type=error_type
                    )
                else:
                    # Run sync function in thread pool to avoid blocking
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        record_func,
                        success,
                        execution_time,
                        result.timed_out,
                        error_type
                    )
        except Exception as e:
            log.warning("metrics.recording_failed tool=%s error=%s", 
                       self.tool_name, str(e))
    
    async def _handle_execution_error(self, e: Exception, inp: ToolInput, 
                                      correlation_id: str, start_time: float) -> ToolOutput:
        """Handle execution errors with detailed context."""
        execution_time = time.time() - start_time
        error_context = ErrorContext(
            error_type=ToolErrorType.EXECUTION_ERROR,
            message=f"Tool execution failed: {str(e)}",
            recovery_suggestion="Check tool logs and system resources",
            timestamp=datetime.now(),
            tool_name=self.tool_name,
            target=inp.target,
            metadata={"exception": str(e), "execution_time": execution_time}
        )
        
        if self.metrics:
            await self._record_metrics(
                ToolOutput(
                    stdout="", stderr=str(e), returncode=1,
                    error_type=ToolErrorType.EXECUTION_ERROR.value
                ),
                execution_time
            )
        
        return self._create_error_output(error_context, correlation_id)
    
    async def _execute_tool(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
        """Execute the tool with validation and resource limits."""
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
            return self._create_error_output(error_context, inp.correlation_id or "")
        
        try:
            args = self._parse_args(inp.extra_args or "")
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
            return self._create_error_output(error_context, inp.correlation_id or "")
        
        cmd = [resolved_cmd] + list(args) + [inp.target]
        timeout = float(timeout_sec or inp.timeout_sec or self.default_timeout_sec)
        return await self._spawn(cmd, timeout)
    
    def _create_error_output(self, error_context: ErrorContext, correlation_id: str) -> ToolOutput:
        """Create error output from error context."""
        log.error(
            "tool.error tool=%s error_type=%s target=%s message=%s correlation_id=%s",
            error_context.tool_name,
            error_context.error_type.value,
            error_context.target,
            error_context.message,
            correlation_id,
            extra={"error_context": error_context}
        )
        
        output = ToolOutput(
            stdout="",
            stderr=error_context.message,
            returncode=1,
            error=error_context.message,
            error_type=error_context.error_type.value,
            correlation_id=correlation_id,
            metadata={
                "recovery_suggestion": error_context.recovery_suggestion,
                "timestamp": error_context.timestamp.isoformat(),
                **error_context.metadata
            }
        )
        output.ensure_metadata()
        return output
    
    def _resolve_command(self) -> Optional[str]:
        """Resolve command path."""
        return shutil.which(self.command_name)
    
    def _parse_args(self, extra_args: str) -> Sequence[str]:
        """Parse and validate arguments."""
        try:
            tokens = shlex.split(extra_args) if extra_args else []
        except ValueError as e:
            raise ValueError(f"Failed to parse arguments: {str(e)}")
        return self._sanitize_tokens(tokens)

    def _sanitize_tokens(self, tokens: Sequence[str]) -> Sequence[str]:
        """Sanitize token list - block shell metacharacters"""
        safe = []
        flags_require_value = set(getattr(self, "_FLAGS_REQUIRE_VALUE", []))

        for t in tokens:
            t = t.strip()
            if not t:
                continue
            if not _TOKEN_ALLOWED.match(t):
                # Permit leading dash flags and pure numeric values even if the
                # strict regex rejects them (e.g., optimizer defaults like "-T4" or "10").
                if not (t.startswith("-") or t.isdigit()):
                    raise ValueError(f"Disallowed token in args: {t!r}")
            safe.append(t)

        if self.allowed_flags is not None:
            allowed = set(self.allowed_flags)
            # Allow subclasses to provide additional safe tokens (e.g., optimizer defaults)
            allowed.update(getattr(self, "_EXTRA_ALLOWED_TOKENS", []))
            expect_value_for: Optional[str] = None
            for token in safe:
                if expect_value_for is not None:
                    # Treat this token as the value for the preceding flag.
                    expect_value_for = None
                    continue
                base = token.split("=", 1)[0]
                if base not in allowed:
                    # Allow the token if it's the value for a prior flag requiring one.
                    if token not in flags_require_value and not token.isdigit():
                        raise ValueError(f"Flag not allowed: {token}")
                    continue
                if base in flags_require_value and "=" not in token:
                    expect_value_for = base
            if expect_value_for is not None:
                raise ValueError(f"{expect_value_for} requires a value")

        return safe
    
    def _set_resource_limits(self):
        """Set resource limits for subprocess (Unix/Linux only)."""
        if sys.platform == 'win32':
            return None
        
        def set_limits():
            # Limit CPU time (soft, hard)
            timeout_int = int(self.default_timeout_sec)
            resource.setrlimit(resource.RLIMIT_CPU, (timeout_int, timeout_int + 5))
            
            # Limit memory
            mem_bytes = _MAX_MEMORY_MB * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            
            # Limit file descriptors
            resource.setrlimit(resource.RLIMIT_NOFILE, (_MAX_FILE_DESCRIPTORS, _MAX_FILE_DESCRIPTORS))
            
            # Limit core dump size to 0
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        
        return set_limits
    
    async def _spawn(self, cmd: Sequence[str], timeout_sec: float) -> ToolOutput:
        """Spawn subprocess with enhanced resource limits and security."""
        env = {
            "PATH": os.getenv("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        
        # Set resource limits function
        preexec_fn = self._set_resource_limits() if sys.platform != 'win32' else None
        
        try:
            log.info("tool.start command=%s timeout=%.1f", " ".join(cmd), timeout_sec)
            
            # Create subprocess with resource limits
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                preexec_fn=preexec_fn,
                start_new_session=True,  # Isolate process group
            )
            
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
                rc = proc.returncode
            except asyncio.TimeoutError:
                # Kill process group
                with contextlib.suppress(ProcessLookupError):
                    if sys.platform != 'win32':
                        import signal
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    else:
                        proc.kill()
                    await proc.wait()
                
                output = ToolOutput(
                    stdout="",
                    stderr=f"Process timed out after {timeout_sec}s",
                    returncode=124,
                    timed_out=True,
                    error_type=ToolErrorType.TIMEOUT.value
                )
                output.ensure_metadata()
                return output
            
            truncated_stdout = False
            truncated_stderr = False
            
            if len(out) > _MAX_STDOUT_BYTES:
                out = out[:_MAX_STDOUT_BYTES]
                truncated_stdout = True
            
            if len(err) > _MAX_STDERR_BYTES:
                err = err[:_MAX_STDERR_BYTES]
                truncated_stderr = True
            
            output = ToolOutput(
                stdout=out.decode(errors="replace"),
                stderr=err.decode(errors="replace"),
                returncode=rc,
                truncated_stdout=truncated_stdout,
                truncated_stderr=truncated_stderr,
                timed_out=False
            )
            output.ensure_metadata()
            
            log.info("tool.end command=%s returncode=%s truncated_stdout=%s truncated_stderr=%s",
                    cmd[0] if cmd else "<cmd>", rc, truncated_stdout, truncated_stderr)
            
            return output
            
        except FileNotFoundError:
            msg = f"Command not found: {cmd[0] if cmd else '<cmd>'}"
            log.error("tool.error %s", msg)
            output = ToolOutput(
                stdout="",
                stderr=msg,
                returncode=127,
                error="not_found",
                error_type=ToolErrorType.NOT_FOUND.value
            )
            output.ensure_metadata()
            return output
            
        except Exception as e:
            msg = f"Execution failed: {e.__class__.__name__}: {e}"
            log.error("tool.error %s", msg)
            output = ToolOutput(
                stdout="",
                stderr=msg,
                returncode=1,
                error="execution_failed",
                error_type=ToolErrorType.EXECUTION_ERROR.value
            )
            output.ensure_metadata()
            return output
    
    def get_tool_info(self) -> Dict[str, Any]:
        """Get tool information."""
        return {
            "name": self.tool_name,
            "command": self.command_name,
            "concurrency": self.concurrency,
            "timeout": self.default_timeout_sec,
            "circuit_breaker": {
                "enabled": self._circuit_breaker is not None,
                "state": self._circuit_breaker.state.name if self._circuit_breaker else "N/A"
            },
            "metrics": {
                "available": self.metrics is not None
            }
        }
```

$ diff -u base_tool.py.old base_tool.py
```diff
--- base_tool.py.old    2025-10-03 18:47:45.412259185 +0800
+++ base_tool.py        2025-10-03 20:43:44.889323561 +0800
@@ -65,7 +65,7 @@
 log = logging.getLogger(__name__)
 
 _DENY_CHARS = re.compile(r"[;&|`$><\n\r]")
-_TOKEN_ALLOWED = re.compile(r"^[A-Za-z0-9.:/=+-,@%_]+$")
+_TOKEN_ALLOWED = re.compile(r"^[A-Za-z0-9.:/=+,\-@%_]+$")
 _HOSTNAME_PATTERN = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$')
 _MAX_ARGS_LEN = int(os.getenv("MCP_MAX_ARGS_LEN", "2048"))
 _MAX_STDOUT_BYTES = int(os.getenv("MCP_MAX_STDOUT_BYTES", "1048576"))
@@ -453,25 +453,49 @@
     
     def _parse_args(self, extra_args: str) -> Sequence[str]:
         """Parse and validate arguments."""
-        if not extra_args:
-            return []
-        
-        tokens = shlex.split(extra_args)
+        try:
+            tokens = shlex.split(extra_args) if extra_args else []
+        except ValueError as e:
+            raise ValueError(f"Failed to parse arguments: {str(e)}")
+        return self._sanitize_tokens(tokens)
+
+    def _sanitize_tokens(self, tokens: Sequence[str]) -> Sequence[str]:
+        """Sanitize token list - block shell metacharacters"""
         safe = []
-        
+        flags_require_value = set(getattr(self, "_FLAGS_REQUIRE_VALUE", []))
+
         for t in tokens:
+            t = t.strip()
             if not t:
                 continue
             if not _TOKEN_ALLOWED.match(t):
-                raise ValueError(f"Disallowed token in args: {t!r}")
+                # Permit leading dash flags and pure numeric values even if the
+                # strict regex rejects them (e.g., optimizer defaults like "-T4" or "10").
+                if not (t.startswith("-") or t.isdigit()):
+                    raise ValueError(f"Disallowed token in args: {t!r}")
             safe.append(t)
-        
+
         if self.allowed_flags is not None:
-            allowed = tuple(self.allowed_flags)
-            for t in safe:
-                if t.startswith("-") and not t.startswith(allowed):
-                    raise ValueError(f"Flag not allowed: {t!r}")
-        
+            allowed = set(self.allowed_flags)
+            # Allow subclasses to provide additional safe tokens (e.g., optimizer defaults)
+            allowed.update(getattr(self, "_EXTRA_ALLOWED_TOKENS", []))
+            expect_value_for: Optional[str] = None
+            for token in safe:
+                if expect_value_for is not None:
+                    # Treat this token as the value for the preceding flag.
+                    expect_value_for = None
+                    continue
+                base = token.split("=", 1)[0]
+                if base not in allowed:
+                    # Allow the token if it's the value for a prior flag requiring one.
+                    if token not in flags_require_value and not token.isdigit():
+                        raise ValueError(f"Flag not allowed: {token}")
+                    continue
+                if base in flags_require_value and "=" not in token:
+                    expect_value_for = base
+            if expect_value_for is not None:
+                raise ValueError(f"{expect_value_for} requires a value")
+
         return safe
     
     def _set_resource_limits(self):
```

# File: tools/nmap_tool.py
```python
"""
Enhanced Nmap tool with circuit breaker, metrics, and comprehensive security controls.
Production-ready implementation with strict safety enforcement.
"""
import logging
import shlex
import ipaddress
import math
from datetime import datetime, timezone
from typing import Sequence, Optional, Dict, Any, Set
import re

from mcp_server.base_tool import MCPBaseTool, ToolInput, ToolOutput, ToolErrorType, ErrorContext
from mcp_server.config import get_config

log = logging.getLogger(__name__)


class NmapTool(MCPBaseTool):
    """
    Enhanced Nmap network scanner tool with comprehensive security features.
    
    Features:
    - Circuit breaker protection for resilience
    - Network range validation and limits
    - Port specification safety
    - Script execution controls with policy enforcement
    - Performance optimizations
    - Comprehensive metrics
    - Intrusive operation control
    
    Safety considerations:
    - Targets restricted to RFC1918 or *.lab.internal
    - Script categories and specific scripts controlled by policy
    - -A flag controlled by intrusive policy
    - Non-flag tokens blocked for security
    - Network size limits enforced
    """
    
    command_name: str = "nmap"
    
    # Conservative, safe flags for nmap
    # -A flag controlled by policy
    BASE_ALLOWED_FLAGS: Sequence[str] = (
        "-sV", "-sC", "-p", "--top-ports", "-T", "-T4", "-Pn",
        "-O", "--script", "-oX", "-oN", "-oG", "--max-parallelism",
        "-sS", "-sT", "-sU", "-sn", "-PS", "-PA", "-PU", "-PY",
        "--open", "--reason", "-v", "-vv", "--version-intensity",
        "--min-rate", "--max-rate", "--max-retries", "--host-timeout",
        "-T0", "-T1", "-T2", "-T3", "-T4", "-T5",  # Timing templates
        "--scan-delay", "--max-scan-delay",
        "-f", "--mtu",  # Fragmentation options
        "-D", "--decoy",  # Decoy options (controlled)
        "--source-port", "-g",  # Source port
        "--data-length",  # Data length
        "--ttl",  # TTL
        "--randomize-hosts",  # Host randomization
        "--spoof-mac",  # MAC spoofing (controlled)
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
    
    # Safe script categories (always allowed)
    SAFE_SCRIPT_CATEGORIES: Set[str] = {"safe", "default", "discovery", "version"}
    
    # Specific safe scripts (always allowed)
    SAFE_SCRIPTS: Set[str] = {
        "http-headers", "ssl-cert", "ssh-hostkey", "smb-os-discovery",
        "dns-brute", "http-title", "ftp-anon", "smtp-commands",
        "pop3-capabilities", "imap-capabilities", "mongodb-info",
        "mysql-info", "ms-sql-info", "oracle-sid-brute",
        "rdp-enum-encryption", "vnc-info", "x11-access"
    }
    
    # Intrusive script categories (require policy)
    INTRUSIVE_SCRIPT_CATEGORIES: Set[str] = {"vuln", "exploit", "intrusive", "brute", "dos"}
    
    # Intrusive specific scripts (require policy)
    INTRUSIVE_SCRIPTS: Set[str] = {
        "http-vuln-*", "smb-vuln-*", "ssl-heartbleed", "ms-sql-brute",
        "mysql-brute", "ftp-brute", "ssh-brute", "rdp-brute",
        "dns-zone-transfer", "snmp-brute", "http-slowloris"
    }
    
    _EXTRA_ALLOWED_TOKENS = {"-T4", "--max-parallelism", "10", "-Pn", "--top-ports", "1000"}
    _FLAGS_REQUIRE_VALUE = {
        "-p", "--ports", "--max-parallelism", "--version-intensity",
        "--min-rate", "--max-rate", "--max-retries", "--host-timeout",
        "--top-ports", "--scan-delay", "--max-scan-delay", "--mtu",
        "--data-length", "--ttl", "--source-port", "-g"
    }

    def __init__(self):
        """Initialize Nmap tool with enhanced features."""
        super().__init__()
        self.config = get_config()
        self.allow_intrusive = False
        self.allowed_flags = list(self.BASE_ALLOWED_FLAGS)
        self._apply_config()
    
    def _apply_config(self):
        """Apply configuration settings safely with policy enforcement."""
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
                if hasattr(tool, 'default_concurrency'):
                    self.concurrency = max(1, min(5, int(tool.default_concurrency)))
            
            # Apply security config
            if hasattr(self.config, 'security') and self.config.security:
                sec = self.config.security
                if hasattr(sec, 'allow_intrusive'):
                    self.allow_intrusive = bool(sec.allow_intrusive)
                    
                    # Update allowed flags based on policy
                    if self.allow_intrusive:
                        # Add -A flag only if intrusive allowed
                        if "-A" not in self.allowed_flags:
                            self.allowed_flags.append("-A")
                        log.info("nmap.intrusive_enabled -A_flag_allowed")
                    else:
                        # Remove -A flag if not allowed
                        if "-A" in self.allowed_flags:
                            self.allowed_flags.remove("-A")
                        log.info("nmap.intrusive_disabled -A_flag_blocked")
            
            log.debug("nmap.config_applied intrusive=%s", self.allow_intrusive)
            
        except Exception as e:
            log.warning("nmap.config_apply_failed error=%s using_safe_defaults", str(e))
            # Reset to safe defaults on error
            self.circuit_breaker_failure_threshold = 5
            self.circuit_breaker_recovery_timeout = 120.0
            self.default_timeout_sec = 600.0
            self.concurrency = 1
            self.allow_intrusive = False
            # Ensure -A is not in allowed flags
            if "-A" in self.allowed_flags:
                self.allowed_flags.remove("-A")
    
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
        """Validate nmap-specific requirements with clear messaging."""
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
            
            # Check network size with clear messaging
            if network.num_addresses > self.MAX_NETWORK_SIZE:
                max_cidr = self._get_max_cidr_for_size(self.MAX_NETWORK_SIZE)
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Network range too large: {network.num_addresses} addresses (max: {self.MAX_NETWORK_SIZE})",
                    recovery_suggestion=f"Use /{max_cidr} or smaller (max {self.MAX_NETWORK_SIZE} hosts)",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                    metadata={
                        "network_size": network.num_addresses,
                        "max_allowed": self.MAX_NETWORK_SIZE,
                        "suggested_cidr": f"/{max_cidr}",
                        "example": f"{network.network_address}/{max_cidr}"
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
    
    def _get_max_cidr_for_size(self, max_hosts: int) -> int:
        """Calculate maximum CIDR prefix for given host count."""
        # For max_hosts=1024, we need /22 (which gives 1024 addresses)
        bits_needed = math.ceil(math.log2(max_hosts))
        return max(0, 32 - bits_needed)
    
    def _parse_and_validate_args(self, extra_args: str) -> str:
        """Parse and validate nmap arguments with strict security."""
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
            
            # Block non-flag tokens completely for security
            if not token.startswith("-"):
                raise ValueError(f"Unexpected non-flag token (potential injection): {token}")
            
            # Check -A flag (controlled by policy)
            if token == "-A":
                if not self.allow_intrusive:
                    raise ValueError("-A flag requires intrusive operations to be enabled")
                validated.append(token)
                i += 1
            
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
            
            # Check script specifications
            elif token == "--script":
                if i + 1 < len(tokens):
                    script_spec = tokens[i + 1]
                    validated_scripts = self._validate_and_filter_scripts(script_spec)
                    if not validated_scripts:
                        raise ValueError(f"No allowed scripts in specification: {script_spec}")
                    validated.extend([token, validated_scripts])
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
            else:
                flag_base, flag_value = (token.split("=", 1) + [None])[:2]
                if flag_base in self.allowed_flags:
                    expects_value = flag_base in {
                        "--max-parallelism", "--version-intensity", "--min-rate",
                        "--max-rate", "--max-retries", "--host-timeout", "--top-ports",
                        "--scan-delay", "--max-scan-delay", "--mtu", "--data-length",
                        "--ttl", "--source-port", "-g"
                    }

                    if flag_value is not None:
                        if not expects_value:
                            raise ValueError(f"Flag does not take inline value: {token}")
                        if not self._validate_numeric_value(flag_base, flag_value):
                            raise ValueError(f"Invalid value for {flag_base}: {flag_value}")
                        validated.extend([flag_base, flag_value])
                        i += 1
                        continue

                    if expects_value:
                        if i + 1 >= len(tokens):
                            raise ValueError(f"{flag_base} requires a value")
                        value = tokens[i + 1]
                        if not self._validate_numeric_value(flag_base, value):
                            raise ValueError(f"Invalid value for {flag_base}: {value}")
                        validated.extend([flag_base, value])
                        i += 2
                    else:
                        validated.append(flag_base)
                        i += 1
                else:
                    raise ValueError(f"Flag not allowed: {token}")
        
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
    
    def _validate_and_filter_scripts(self, script_spec: str) -> str:
        """Validate and filter script specification based on policy."""
        allowed_scripts = []
        scripts = script_spec.split(',')
        
        for script in scripts:
            script = script.strip()
            
            # Check if it's a category (exact match)
            if script in self.SAFE_SCRIPT_CATEGORIES:
                allowed_scripts.append(script)
            elif script in self.INTRUSIVE_SCRIPT_CATEGORIES:
                if self.allow_intrusive:
                    allowed_scripts.append(script)
                    log.info("nmap.intrusive_script_allowed script=%s", script)
                else:
                    log.warning("nmap.intrusive_script_blocked script=%s", script)
            
            # Check if it's a specific script (exact match)
            elif script in self.SAFE_SCRIPTS:
                allowed_scripts.append(script)
            elif script in self.INTRUSIVE_SCRIPTS:
                if self.allow_intrusive:
                    allowed_scripts.append(script)
                    log.info("nmap.intrusive_script_allowed script=%s", script)
                else:
                    log.warning("nmap.intrusive_script_blocked script=%s", script)
            
            # Check wildcard patterns for intrusive scripts
            elif any(script.startswith(pattern.replace('*', '')) for pattern in self.INTRUSIVE_SCRIPTS if '*' in pattern):
                if self.allow_intrusive:
                    allowed_scripts.append(script)
                    log.info("nmap.intrusive_script_allowed script=%s", script)
                else:
                    log.warning("nmap.intrusive_script_blocked script=%s", script)
            
            else:
                # Unknown script - block it
                log.warning("nmap.unknown_script_blocked script=%s", script)
        
        return ','.join(allowed_scripts) if allowed_scripts else ""
    
    def _validate_numeric_value(self, flag: str, value: str) -> bool:
        """Validate numeric-like values for flags that expect numbers or durations."""
        if flag in {"--host-timeout", "--scan-delay", "--max-scan-delay"}:
            return bool(re.match(r'^[0-9]+(ms|s|m)?$', value))
        if flag in {"--max-parallelism", "--version-intensity", "--min-rate",
                    "--max-rate", "--max-retries", "--top-ports", "--mtu",
                    "--data-length", "--ttl", "--source-port", "-g"}:
            return value.isdigit()
        return False

    def _optimize_nmap_args(self, extra_args: str) -> str:
        """Optimize nmap arguments for performance and safety."""
        if not extra_args:
            extra_args = ""

        try:
            tokens = shlex.split(extra_args) if extra_args else []
        except ValueError:
            tokens = extra_args.split() if extra_args else []

        optimized = []

        has_timing = any(t.startswith("-T") for t in tokens)
        has_parallelism = any(t in {"--max-parallelism", "--max-parallelism=10"} for t in tokens)
        has_host_discovery = any(t in ("-Pn", "-sn", "-PS", "-PA") for t in tokens)
        has_port_spec = any(t in ("-p", "--ports", "--top-ports") for t in tokens)

        if not has_timing:
            optimized.append("-T4")

        if not has_parallelism:
            optimized.extend(["--max-parallelism", "10"])

        if not has_host_discovery:
            optimized.append("-Pn")

        if not has_port_spec:
            optimized.extend(["--top-ports", "1000"])

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
            "intrusive_allowed": self.allow_intrusive,
            "circuit_breaker": {
                "enabled": self._circuit_breaker is not None,
                "failure_threshold": self.circuit_breaker_failure_threshold,
                "recovery_timeout": self.circuit_breaker_recovery_timeout,
                "state": self._circuit_breaker.state.name if self._circuit_breaker else "N/A"
            },
            "safety_limits": {
                "max_network_size": self.MAX_NETWORK_SIZE,
                "max_port_ranges": self.MAX_PORT_RANGES,
                "safe_script_categories": list(self.SAFE_SCRIPT_CATEGORIES),
                "safe_scripts": list(self.SAFE_SCRIPTS),
                "intrusive_categories": list(self.INTRUSIVE_SCRIPT_CATEGORIES) if self.allow_intrusive else [],
                "intrusive_scripts": list(self.INTRUSIVE_SCRIPTS) if self.allow_intrusive else [],
                "-A_flag": "allowed" if self.allow_intrusive else "blocked"
            },
            "optimizations": {
                "default_timing": "T4 (Aggressive)",
                "default_parallelism": 10,
                "default_ports": "top-1000",
                "host_discovery": "disabled (-Pn)"
            },
            "security": {
                "non_flag_tokens": "blocked",
                "script_filtering": "enforced",
                "private_targets_only": True
            },
            "metrics": {
                "available": self.metrics is not None,
                "prometheus": f'mcp_tool_execution_total{{tool="{self.tool_name}"}}' if self.metrics else None
            }
        }
```

$ diff -u tools/nmap_tool.py.old tools/nmap_tool.py
```diff
--- tools/nmap_tool.py.old      2025-10-03 18:47:45.413259205 +0800
+++ tools/nmap_tool.py  2025-10-03 20:43:44.890323637 +0800
@@ -95,6 +95,14 @@
         "dns-zone-transfer", "snmp-brute", "http-slowloris"
     }
     
+    _EXTRA_ALLOWED_TOKENS = {"-T4", "--max-parallelism", "10", "-Pn", "--top-ports", "1000"}
+    _FLAGS_REQUIRE_VALUE = {
+        "-p", "--ports", "--max-parallelism", "--version-intensity",
+        "--min-rate", "--max-rate", "--max-retries", "--host-timeout",
+        "--top-ports", "--scan-delay", "--max-scan-delay", "--mtu",
+        "--data-length", "--ttl", "--source-port", "-g"
+    }
+
     def __init__(self):
         """Initialize Nmap tool with enhanced features."""
         super().__init__()
@@ -337,24 +345,34 @@
             
             # Check other flags
             else:
-                flag_base = token.split("=")[0] if "=" in token else token
-                if any(flag_base.startswith(allowed) for allowed in self.allowed_flags):
-                    # Check if flag expects a value
-                    if flag_base in ("--max-parallelism", "--version-intensity", "--min-rate",
-                                    "--max-rate", "--max-retries", "--host-timeout", "--top-ports",
-                                    "--scan-delay", "--max-scan-delay", "--mtu", "--data-length",
-                                    "--ttl", "--source-port", "-g"):
-                        if i + 1 < len(tokens):
-                            value = tokens[i + 1]
-                            # Validate the value is numeric or simple
-                            if not re.match(r'^[0-9ms]+$', value):
-                                raise ValueError(f"Invalid value for {token}: {value}")
-                            validated.extend([token, value])
-                            i += 2
-                        else:
-                            raise ValueError(f"{token} requires a value")
+                flag_base, flag_value = (token.split("=", 1) + [None])[:2]
+                if flag_base in self.allowed_flags:
+                    expects_value = flag_base in {
+                        "--max-parallelism", "--version-intensity", "--min-rate",
+                        "--max-rate", "--max-retries", "--host-timeout", "--top-ports",
+                        "--scan-delay", "--max-scan-delay", "--mtu", "--data-length",
+                        "--ttl", "--source-port", "-g"
+                    }
+
+                    if flag_value is not None:
+                        if not expects_value:
+                            raise ValueError(f"Flag does not take inline value: {token}")
+                        if not self._validate_numeric_value(flag_base, flag_value):
+                            raise ValueError(f"Invalid value for {flag_base}: {flag_value}")
+                        validated.extend([flag_base, flag_value])
+                        i += 1
+                        continue
+
+                    if expects_value:
+                        if i + 1 >= len(tokens):
+                            raise ValueError(f"{flag_base} requires a value")
+                        value = tokens[i + 1]
+                        if not self._validate_numeric_value(flag_base, value):
+                            raise ValueError(f"Invalid value for {flag_base}: {value}")
+                        validated.extend([flag_base, value])
+                        i += 2
                     else:
-                        validated.append(token)
+                        validated.append(flag_base)
                         i += 1
                 else:
                     raise ValueError(f"Flag not allowed: {token}")
@@ -440,40 +458,47 @@
         
         return ','.join(allowed_scripts) if allowed_scripts else ""
     
+    def _validate_numeric_value(self, flag: str, value: str) -> bool:
+        """Validate numeric-like values for flags that expect numbers or durations."""
+        if flag in {"--host-timeout", "--scan-delay", "--max-scan-delay"}:
+            return bool(re.match(r'^[0-9]+(ms|s|m)?$', value))
+        if flag in {"--max-parallelism", "--version-intensity", "--min-rate",
+                    "--max-rate", "--max-retries", "--top-ports", "--mtu",
+                    "--data-length", "--ttl", "--source-port", "-g"}:
+            return value.isdigit()
+        return False
+
     def _optimize_nmap_args(self, extra_args: str) -> str:
         """Optimize nmap arguments for performance and safety."""
         if not extra_args:
             extra_args = ""
-        
+
         try:
             tokens = shlex.split(extra_args) if extra_args else []
         except ValueError:
             tokens = extra_args.split() if extra_args else []
-        
+
         optimized = []
-        
-        # Check what's already specified
+
         has_timing = any(t.startswith("-T") for t in tokens)
-        has_parallelism = any("--max-parallelism" in t for t in tokens)
+        has_parallelism = any(t in {"--max-parallelism", "--max-parallelism=10"} for t in tokens)
         has_host_discovery = any(t in ("-Pn", "-sn", "-PS", "-PA") for t in tokens)
         has_port_spec = any(t in ("-p", "--ports", "--top-ports") for t in tokens)
-        
-        # Add optimizations
+
         if not has_timing:
-            optimized.append("-T4")  # Aggressive timing
-        
+            optimized.append("-T4")
+
         if not has_parallelism:
-            optimized.append("--max-parallelism=10")  # Limit parallel probes
-        
+            optimized.extend(["--max-parallelism", "10"])
+
         if not has_host_discovery:
-            optimized.append("-Pn")  # Skip host discovery for speed
-        
+            optimized.append("-Pn")
+
         if not has_port_spec:
-            optimized.append("--top-ports=1000")  # Scan top 1000 ports by default
-        
-        # Add existing arguments
+            optimized.extend(["--top-ports", "1000"])
+
         optimized.extend(tokens)
-        
+
         return " ".join(optimized)
     
     def _get_timestamp(self) -> datetime:
```
