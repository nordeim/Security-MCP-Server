# File: base_tool.py
"""
Enhanced MCP Base Tool with circuit breaker, metrics, and advanced error handling.
Added robust fallback when pydantic is not installed and fixed mutable default metadata.
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

# Pydantic v1/v2 compatibility shim with graceful fallback
try:
    from pydantic import BaseModel, field_validator, Field
    _PD_V2 = True
except Exception:
    try:
        from pydantic import BaseModel, validator as field_validator, Field  # type: ignore
        _PD_V2 = False
    except Exception:
        # Fallback minimal BaseModel and no-op validator decorator if pydantic isn't available.
        class BaseModel:
            def __init__(self, **data):
                for k, v in data.items():
                    setattr(self, k, v)

            def dict(self):
                return {k: v for k, v in self.__dict__.items()}

        def field_validator(*args, **kwargs):
            def _decorator(func):
                return func
            return _decorator

        try:
            # Provide a Field fallback to support default_factory pattern usage below.
            def Field(default=None, **kwargs):
                return default
        except Exception:
            Field = lambda default=None, **kwargs: default

        _PD_V2 = False

# Metrics integration with graceful handling
try:
    from prometheus_client import Counter, Histogram, Gauge, Info
    PROMETHEUS_AVAILABLE = True
except Exception:
    PROMETHEUS_AVAILABLE = False

# Circuit breaker import (presumes a local module exists)
try:
    from .circuit_breaker import CircuitBreaker, CircuitBreakerState
except Exception:
    try:
        from circuit_breaker import CircuitBreaker, CircuitBreakerState
    except Exception:
        CircuitBreaker = None
        CircuitBreakerState = None

# Tool metrics local import (metrics module in repo)
try:
    from .metrics import ToolMetrics
except Exception:
    ToolMetrics = None

log = logging.getLogger(__name__)

# Conservative denylist for arg tokens we never want to see (even though shell=False)
_DENY_CHARS = re.compile(r"[;&|`$><\n\r]")  # control/meta chars
_TOKEN_ALLOWED = re.compile(r"^[A-Za-z0-9.:/=+-,@%]+$")  # reasonably safe superset
_MAX_ARGS_LEN = int(os.getenv("MCP_MAX_ARGS_LEN", "2048"))
_MAX_STDOUT_BYTES = int(os.getenv("MCP_MAX_STDOUT_BYTES", "1048576"))  # 1 MiB
_MAX_STDERR_BYTES = int(os.getenv("MCP_MAX_STDERR_BYTES", "262144"))  # 256 KiB
_DEFAULT_TIMEOUT_SEC = float(os.getenv("MCP_DEFAULT_TIMEOUT_SEC", "300"))  # 5 minutes
_DEFAULT_CONCURRENCY = int(os.getenv("MCP_DEFAULT_CONCURRENCY", "2"))

def _is_private_or_lab(value: str) -> bool:
    import ipaddress
    v = value.strip()
    if v.endswith(".lab.internal"):
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
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"
    VALIDATION_ERROR = "validation_error"
    EXECUTION_ERROR = "execution_error"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"
    UNKNOWN = "unknown"

@dataclass
class ErrorContext:
    error_type: ToolErrorType
    message: str
    recovery_suggestion: str
    timestamp: datetime
    tool_name: str
    target: str
    metadata: Dict[str, Any]

# Define ToolInput and ToolOutput using BaseModel (or fallback)
class ToolInput(BaseModel):
    target: str
    extra_args: str = ""
    timeout_sec: Optional[float] = None
    correlation_id: Optional[str] = None

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
        try:
            @field_validator("target")
            def _validate_target(cls, v: str) -> str:  # type: ignore
                if not _is_private_or_lab(v):
                    raise ValueError("Target must be RFC1918 IPv4 or a .lab.internal hostname (CIDR allowed).")
                return v

            @field_validator("extra_args")
            def _validate_extra_args(cls, v: str) -> str:  # type: ignore
                v = v or ""
                if len(v) > _MAX_ARGS_LEN:
                    raise ValueError(f"extra_args too long (> {_MAX_ARGS_LEN} bytes)")
                if _DENY_CHARS.search(v):
                    raise ValueError("extra_args contains forbidden metacharacters")
                return v
        except Exception:
            # If validator decorator is a no-op (fallback), we skip runtime validation.
            pass

class ToolOutput(BaseModel):
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
    # Use Field(default_factory=dict) when available; fallback to None and normalize usage.
    try:
        metadata: Dict[str, Any] = Field(default_factory=dict)
    except Exception:
        metadata: Dict[str, Any] = None

    def ensure_metadata(self):
        if getattr(self, "metadata", None) is None:
            self.metadata = {}

class MCPBaseTool(ABC):
    command_name: ClassVar[str]
    allowed_flags: ClassVar[Optional[Sequence[str]]] = None
    concurrency: ClassVar[int] = _DEFAULT_CONCURRENCY
    default_timeout_sec: ClassVar[float] = _DEFAULT_TIMEOUT_SEC
    circuit_breaker_failure_threshold: ClassVar[int] = 5
    circuit_breaker_recovery_timeout: ClassVar[float] = 60.0
    circuit_breaker_expected_exception: ClassVar[tuple] = (Exception,)
    _semaphore: ClassVar[Optional[asyncio.Semaphore]] = None
    _circuit_breaker: ClassVar[Optional[Any]] = None  # CircuitBreaker may be None if import failed

    def __init__(self):
        self.tool_name = self.__class__.__name__
        self._initialize_metrics()
        self._initialize_circuit_breaker()

    def _initialize_metrics(self):
        if ToolMetrics is not None:
            try:
                # ToolMetrics may be implemented to be safe for multiple instantiations
                self.metrics = ToolMetrics(self.tool_name)
            except Exception as e:
                log.warning("metrics.initialization_failed tool=%s error=%s", self.tool_name, str(e))
                self.metrics = None
        else:
            self.metrics = None

    def _initialize_circuit_breaker(self):
        if CircuitBreaker is None:
            self.__class__._circuit_breaker = None
            return
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
        if self.__class__._semaphore is None:
            self.__class__._semaphore = asyncio.Semaphore(self.concurrency)
        return self.__class__._semaphore

    async def run(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
        start_time = time.time()
        correlation_id = getattr(inp, "correlation_id", None) or str(int(start_time * 1000))
        try:
            if self._circuit_breaker and getattr(self._circuit_breaker, "state", None) == getattr(CircuitBreakerState, "OPEN", "OPEN"):
                error_context = ErrorContext(
                    error_type=ToolErrorType.CIRCUIT_BREAKER_OPEN,
                    message=f"Circuit breaker is open for {self.tool_name}",
                    recovery_suggestion="Wait for recovery timeout or check service health",
                    timestamp=datetime.now(),
                    tool_name=self.tool_name,
                    target=getattr(inp, "target", "<unknown>"),
                    metadata={"state": str(getattr(self._circuit_breaker, "state", None))}
                )
                out = self._create_error_output(error_context, correlation_id)
                out.ensure_metadata()
                return out

            async with self._ensure_semaphore():
                if self._circuit_breaker:
                    try:
                        # circuit_breaker.call may be sync/async depending on implementation
                        result = await self._circuit_breaker.call(self._execute_tool, inp, timeout_sec)
                    except Exception as circuit_error:
                        error_context = ErrorContext(
                            error_type=ToolErrorType.CIRCUIT_BREAKER_OPEN,
                            message=f"Circuit breaker error: {str(circuit_error)}",
                            recovery_suggestion="Wait for recovery timeout or check service health",
                            timestamp=datetime.now(),
                            tool_name=self.tool_name,
                            target=getattr(inp, "target", "<unknown>"),
                            metadata={"circuit_error": str(circuit_error)}
                        )
                        out = self._create_error_output(error_context, correlation_id)
                        out.ensure_metadata()
                        return out
                else:
                    result = await self._execute_tool(inp, timeout_sec)

                if hasattr(self, "metrics") and self.metrics:
                    execution_time = max(0.001, time.time() - start_time)
                    try:
                        self.metrics.record_execution(
                            success=(getattr(result, "returncode", 0) == 0),
                            execution_time=execution_time,
                            timed_out=getattr(result, "timed_out", False)
                        )
                    except Exception as e:
                        log.warning("metrics.recording_failed tool=%s error=%s", self.tool_name, str(e))

                result.correlation_id = correlation_id
                result.execution_time = max(0.001, time.time() - start_time)
                if hasattr(result, "ensure_metadata"):
                    result.ensure_metadata()
                return result

        except Exception as e:
            execution_time = max(0.001, time.time() - start_time)
            error_context = ErrorContext(
                error_type=ToolErrorType.EXECUTION_ERROR,
                message=f"Tool execution failed: {str(e)}",
                recovery_suggestion="Check tool logs and system resources",
                timestamp=datetime.now(),
                tool_name=self.tool_name,
                target=getattr(inp, "target", "<unknown>"),
                metadata={"exception": str(e), "execution_time": execution_time}
            )
            if hasattr(self, "metrics") and self.metrics:
                try:
                    self.metrics.record_execution(success=False, execution_time=execution_time,
                                                  error_type=ToolErrorType.EXECUTION_ERROR.value)
                except Exception as metrics_error:
                    log.warning("metrics.failure_recording_failed tool=%s error=%s", self.tool_name, str(metrics_error))
            out = self._create_error_output(error_context, correlation_id)
            out.ensure_metadata()
            return out

    async def _execute_tool(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
        resolved_cmd = self._resolve_command()
        if not resolved_cmd:
            error_context = ErrorContext(
                error_type=ToolErrorType.NOT_FOUND,
                message=f"Command not found: {getattr(self, 'command_name', '<unknown>')}",
                recovery_suggestion="Install the required tool or check PATH",
                timestamp=datetime.now(),
                tool_name=self.tool_name,
                target=getattr(inp, "target", "<unknown>"),
                metadata={"command": getattr(self, "command_name", None)}
            )
            out = self._create_error_output(error_context, getattr(inp, "correlation_id", None) or "")
            out.ensure_metadata()
            return out

        try:
            args = self._parse_args(getattr(inp, "extra_args", "") or "")
        except ValueError as e:
            error_context = ErrorContext(
                error_type=ToolErrorType.VALIDATION_ERROR,
                message=f"Argument validation failed: {str(e)}",
                recovery_suggestion="Check arguments and try again",
                timestamp=datetime.now(),
                tool_name=self.tool_name,
                target=getattr(inp, "target", "<unknown>"),
                metadata={"validation_error": str(e)}
            )
            out = self._create_error_output(error_context, getattr(inp, "correlation_id", None) or "")
            out.ensure_metadata()
            return out

        cmd = [resolved_cmd] + list(args) + [getattr(inp, "target", "")]
        timeout = float(timeout_sec or self.default_timeout_sec)
        return await self._spawn(cmd, timeout)

    def _create_error_output(self, error_context: ErrorContext, correlation_id: str) -> ToolOutput:
        log.error(
            "tool.error tool=%s error_type=%s target=%s message=%s correlation_id=%s",
            error_context.tool_name,
            error_context.error_type.value,
            error_context.target,
            error_context.message,
            correlation_id,
            extra={"error_context": error_context}
        )
        out = ToolOutput(
            stdout="",
            stderr=error_context.message,
            returncode=1,
            error=error_context.message,
            error_type=error_context.error_type.value,
            correlation_id=correlation_id,
            metadata={"recovery_suggestion": error_context.recovery_suggestion, "timestamp": error_context.timestamp.isoformat()}
        )
        try:
            out.ensure_metadata()
        except Exception:
            pass
        return out

    def _resolve_command(self) -> Optional[str]:
        return shutil.which(getattr(self, "command_name", ""))

    def _parse_args(self, extra_args: str) -> Sequence[str]:
        if not extra_args:
            return []
        tokens = shlex.split(extra_args)
        safe: list[str] = []
        for t in tokens:
            if not t:
                continue
            if not _TOKEN_ALLOWED.match(t):
                raise ValueError(f"Disallowed token in args: {t!r}")
            safe.append(t)
        if self.allowed_flags is not None:
            allowed = tuple(self.allowed_flags)
            for t in safe:
                if t.startswith("-") and not t.startswith(allowed):
                    raise ValueError(f"Flag not allowed: {t!r}")
        return safe

    async def _spawn(self, cmd: Sequence[str], timeout_sec: Optional[float] = None) -> ToolOutput:
        timeout = float(timeout_sec or self.default_timeout_sec)
        env = {
            "PATH": os.getenv("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        try:
            log.info("tool.start command=%s timeout=%.1f", " ".join(cmd), timeout)
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
                return ToolOutput(stdout="", stderr="process timed out", returncode=124, timed_out=True)
            t_stdout = False
            t_stderr = False
            if len(out) > _MAX_STDOUT_BYTES:
                out = out[:_MAX_STDOUT_BYTES]
                t_stdout = True
            if len(err) > _MAX_STDERR_BYTES:
                err = err[:_MAX_STDERR_BYTES]
                t_stderr = True
            res = ToolOutput(
                stdout=out.decode(errors="replace"),
                stderr=err.decode(errors="replace"),
                returncode=rc,
                truncated_stdout=t_stdout,
                truncated_stderr=t_stderr,
                timed_out=False
            )
            try:
                res.ensure_metadata()
            except Exception:
                pass
            log.info("tool.end command=%s returncode=%s truncated_stdout=%s truncated_stderr=%s",
                     cmd[0] if cmd else "<cmd>", rc, t_stdout, t_stderr)
            return res
        except FileNotFoundError:
            msg = f"Command not found: {cmd[0] if cmd else '<cmd>'}"
            log.error("tool.error %s", msg)
            return ToolOutput(stdout="", stderr=msg, returncode=127, error="not_found")
        except Exception as e:
            msg = f"execution failed: {e.__class__.__name__}: {e}"
            log.error("tool.error %s", msg)
            return ToolOutput(stdout="", stderr=msg, returncode=1, error="execution_failed")
