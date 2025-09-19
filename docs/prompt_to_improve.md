You are an elite AI coding assistant and a helpful partner. You always think deeper and harder to explore all possible solutions, approaches, and options before choosing the most suitable and optimal option to formulate your answer. Please carefully process and internalize this comprehensive framework for how you should operate. Your role and responsibilities are as follows:

## Your Core Operating Framework

### 1. **Deep Analysis & Deliberation**
- You will thoroughly explore the problem space before proposing solutions
- Use comprehensive chain-of-thought reasoning to uncover true intent behind requests
- Consider multiple approaches, weighing trade-offs and long-term implications
- Never rush to the first viable solution; always seek the optimal one

### 2. **Systematic Planning & Execution**
- Break down complex tasks into logical, independent phases
- Create detailed execution plans with integrated checklists
- Ensure each step is verifiable and has clear success criteria
- Design for modularity and maintainability from the start

### 3. **Technical Excellence Standards**
- Deliver production-ready, clean, well-documented code
- Prioritize scalability and future extensibility
- Consider performance, security, and edge cases
- Write code that other developers would be proud to maintain

### 4. **Partnership Approach**
- Act as a strategic technical partner, not just a code generator
- Provide clear rationale for all decisions and recommendations
- Anticipate potential challenges and address them proactively
- Focus on creating solutions with genuine "wow" factor in UX/UI

### 5. **Communication & Process**
- Use `<think>` tags for internal deliberation when needed
- Provide clear, structured responses with reasoning
- Maintain transparency about trade-offs and alternatives considered
- Ensure non-disruptive implementation strategies

### Your Commitment

You will apply this framework consistently, taking the time needed to deliver thoughtful, comprehensive solutions rather than quick fixes. Each response will reflect careful consideration of immediate needs, long-term sustainability, and the broader context of my projects.

You will take the above as your meta-instruction going forward. You will apply this framework to all future requests.

Please acknowledge that you are ready to operate at this elevated standard.

Now, help me to validate the core files below for a custom MCP server project.

```python
# File: server.py
"""
Enhanced MCP Server with ALL original features preserved + comprehensive enhancements.
Adjusted to use the repository's configuration API (get_config) and aligned env names.
"""
import asyncio
import importlib
import inspect
import logging
import os
import pkgutil
import signal
import sys
import time
from typing import Dict, List, Optional, Set, Any, Iterable, Sequence, Type
from datetime import datetime
import json
import contextlib

# FastAPI for HTTP transport
try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from starlette.requests import Request
    from sse_starlette.sse import EventSourceResponse
    FASTAPI_AVAILABLE = True
except Exception:
    FASTAPI_AVAILABLE = False

# Uvicorn for HTTP server
try:
    import uvicorn
    UVICORN_AVAILABLE = True
except Exception:
    UVICORN_AVAILABLE = False

# MCP imports (external dependency)
try:
    from mcp.server import Server as MCPServerBase
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except Exception:
    # We keep import errors non-fatal here so the module can be imported for unit tests
    MCPServerBase = None
    stdio_server = None
    Tool = None
    TextContent = None

# Local imports - use the real config API
from .config import get_config
from .health import HealthCheckManager, HealthStatus
from .base_tool import MCPBaseTool, ToolInput, ToolOutput
# Removed unused import: from .metrics import MetricsManager

log = logging.getLogger(__name__)

def _maybe_setup_uvloop() -> None:
    """Optional uvloop installation for better performance."""
    try:
        import uvloop  # type: ignore
        uvloop.install()
        log.info("uvloop.installed")
    except Exception as e:
        log.debug("uvloop.not_available error=%s", str(e))

def _setup_logging() -> None:
    """Environment-based logging configuration."""
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    fmt = os.getenv(
        "LOG_FORMAT",
        "%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.basicConfig(level=getattr(logging, level, logging.INFO), format=fmt)
    log.info("logging.configured level=%s", level)

def _parse_csv_env(name: str) -> Optional[List[str]]:
    """Parse CSV environment variables."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    return [x.strip() for x in raw.split(",") if x.strip()]

def _load_tools_from_package(
    package_path: str,
    include: Optional[Sequence[str]] = None,
    exclude: Optional[Sequence[str]] = None,
) -> List[MCPBaseTool]:
    """
    Discover and instantiate concrete MCPBaseTool subclasses under package_path.
    include/exclude: class names (e.g., ["NmapTool"]) to filter.
    """
    tools: list[MCPBaseTool] = []
    log.info("tool_discovery.starting package=%s include=%s exclude=%s",
             package_path, include, exclude)

    try:
        pkg = importlib.import_module(package_path)
        log.debug("tool_discovery.package_imported path=%s", package_path)
    except Exception as e:
        log.error("tool_discovery.package_failed path=%s error=%s", package_path, e)
        return tools

    module_count = 0
    for modinfo in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
        module_count += 1
        try:
            module = importlib.import_module(modinfo.name)
            log.debug("tool_discovery.module_imported name=%s", modinfo.name)
        except Exception as e:
            log.warning("tool_discovery.module_skipped name=%s error=%s", modinfo.name, e)
            continue

        tool_count_in_module = 0
        for _, obj in inspect.getmembers(module, inspect.isclass):
            try:
                if not issubclass(obj, MCPBaseTool) or obj is MCPBaseTool:
                    continue
            except Exception:
                continue  # skip objects that raise on issubclass check

            name = obj.__name__
            if include and name not in include:
                log.debug("tool_discovery.tool_skipped name=%s reason=include_filter", name)
                continue
            if exclude and name in exclude:
                log.debug("tool_discovery.tool_skipped name=%s reason=exclude_filter", name)
                continue

            try:
                inst = obj()  # assume no-arg constructor
                tools.append(inst)
                tool_count_in_module += 1
                log.info("tool_discovery.tool_loaded name=%s", name)
            except Exception as e:
                log.warning("tool_discovery.tool_instantiation_failed name=%s error=%s", name, e)

        if tool_count_in_module == 0:
            log.debug("tool_discovery.no_tools_in_module module=%s", modinfo.name)

    log.info("tool_discovery.completed package=%s modules=%d tools=%d",
             package_path, module_count, len(tools))
    return tools

async def _serve(server: MCPServerBase, shutdown_grace: float) -> None:
    """
    Handle server lifecycle with signal handling and graceful shutdown.
    Maintains compatibility with the expected MCP server serve() interface.
    """
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _signal_handler(sig: int) -> None:
        log.info("server.signal_received signal=%s initiating_shutdown", sig)
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler, sig)
            log.debug("server.signal_handler_registered signal=%s", sig)
        except NotImplementedError:
            log.warning("server.signal_handler_not_supported signal=%s platform=%s", sig, sys.platform)
        except Exception as e:
            log.error("server.signal_handler_failed signal=%s error=%s", sig, str(e))

    serve_task = asyncio.create_task(server.serve(), name="mcp_serve")
    log.info("server.started grace_period=%.1fs", shutdown_grace)

    try:
        await stop.wait()
        log.info("server.shutdown_initiated")
    except asyncio.CancelledError:
        log.info("server.shutdown_cancelled")
        return

    log.info("server.shutting_down... ")
    serve_task.cancel()

    try:
        await asyncio.wait_for(serve_task, timeout=shutdown_grace)
        log.info("server.shutdown_completed")
    except asyncio.TimeoutError:
        log.warning("server.shutdown_forced timeout=%.1fs", shutdown_grace)
    except asyncio.CancelledError:
        log.info("server.shutdown_cancelled_during_cleanup")
    except Exception as e:
        log.error("server.shutdown_error error=%s", str(e))

class ToolRegistry:
    """Tool Registry that holds tools and enabled set."""
    def __init__(self, config, tools: List[MCPBaseTool]):
        self.config = config
        self.tools: Dict[str, MCPBaseTool] = {}
        self.enabled_tools: Set[str] = set()
        self._register_tools_from_list(tools)

    def _register_tools_from_list(self, tools: List[MCPBaseTool]):
        for tool in tools:
            tool_name = tool.__class__.__name__
            self.tools[tool_name] = tool
            if self._is_tool_enabled(tool_name):
                self.enabled_tools.add(tool_name)
                if hasattr(tool, '_initialize_metrics'):
                    tool._initialize_metrics()
                if hasattr(tool, '_initialize_circuit_breaker'):
                    tool._initialize_circuit_breaker()
                log.info("tool_registry.enhanced_tool_registered name=%s", tool_name)

    def _is_tool_enabled(self, tool_name: str) -> bool:
        include = _parse_csv_env("TOOL_INCLUDE")
        exclude = _parse_csv_env("TOOL_EXCLUDE")
        if include and tool_name not in include:
            return False
        if exclude and tool_name in exclude:
            return False
        return True

    def get_tool(self, tool_name: str) -> Optional[MCPBaseTool]:
        return self.tools.get(tool_name)

    def get_enabled_tools(self) -> Dict[str, MCPBaseTool]:
        return {name: tool for name, tool in self.tools.items() if name in self.enabled_tools}

    def enable_tool(self, tool_name: str):
        if tool_name in self.tools:
            self.enabled_tools.add(tool_name)
            log.info("tool_registry.enabled name=%s", tool_name)

    def disable_tool(self, tool_name: str):
        self.enabled_tools.discard(tool_name)
        log.info("tool_registry.disabled name=%s", tool_name)

    def get_tool_info(self) -> List[Dict[str, Any]]:
        info = []
        for name, tool in self.tools.items():
            info.append({
                "name": name,
                "enabled": name in self.enabled_tools,
                "command": getattr(tool, "command_name", None),
                "description": tool.__doc__ or "No description",
                "concurrency": getattr(tool, "concurrency", None),
                "timeout": getattr(tool, "default_timeout_sec", None),
                "has_metrics": hasattr(tool, 'metrics') and tool.metrics is not None,
                "has_circuit_breaker": hasattr(tool, '_circuit_breaker') and tool._circuit_breaker is not None
            })
        return info

class EnhancedMCPServer:
    """Enhanced MCP Server (keeps simple interface)."""
    def __init__(self, tools: List[MCPBaseTool], transport: str = "stdio", config=None):
        self.tools = tools
        self.transport = transport
        self.config = config or get_config()
        # Create underlying MCP server only if available
        if MCPServerBase:
            try:
                self.server = MCPServerBase("enhanced-mcp-server")
            except Exception:
                self.server = None
        else:
            self.server = None

        self.tool_registry = ToolRegistry(self.config, tools)
        self.shutdown_event = asyncio.Event()
        self._register_tools_enhanced()
        self._setup_enhanced_signal_handlers()
        log.info("enhanced_server.initialized transport=%s tools=%d", self.transport, len(self.tools))

    def _register_tools_enhanced(self):
        if not self.server:
            return
        for tool in self.tools:
            self.server.register_tool(
                name=tool.__class__.__name__,
                description=tool.__doc__ or f"Execute {getattr(tool, 'command_name', 'tool')}",
                input_schema={
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                            "description": "Target host or network"
                        },
                        "extra_args": {
                            "type": "string",
                            "description": "Additional arguments for the tool"
                        },
                        "timeout_sec": {
                            "type": "number",
                            "description": "Timeout in seconds"
                        }
                    },
                    "required": ["target"]
                },
                handler=self._create_enhanced_tool_handler(tool)
            )

    def _create_enhanced_tool_handler(self, tool: MCPBaseTool):
        async def enhanced_handler(target: str, extra_args: str = "", timeout_sec: Optional[float] = None):
            try:
                if hasattr(tool, 'run'):
                    input_data = ToolInput(
                        target=target,
                        extra_args=extra_args,
                        timeout_sec=timeout_sec
                    )
                    result = await tool.run(input_data)
                else:
                    result = await self._execute_original_tool(tool, target, extra_args, timeout_sec)
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(result.dict() if hasattr(result, 'dict') else str(result), indent=2)
                    )
                ]
            except Exception as e:
                log.error("enhanced_tool_handler.error tool=%s target=%s error=%s",
                         tool.__class__.__name__, target, str(e))
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({
                            "error": str(e),
                            "tool": tool.__class__.__name__,
                            "target": target
                        }, indent=2)
                    )
                ]
        return enhanced_handler

    async def _execute_original_tool(self, tool: MCPBaseTool, target: str, extra_args: str, timeout_sec: Optional[float]):
        if hasattr(tool, '_spawn'):
            cmd = [getattr(tool, "command_name", "<cmd>")] + (extra_args.split() if extra_args else []) + [target]
            return await tool._spawn(cmd, timeout_sec)
        else:
            return {
                "stdout": f"Executed {getattr(tool, 'command_name', 'tool')} on {target}",
                "stderr": "",
                "returncode": 0
            }

    def _setup_enhanced_signal_handlers(self):
        def signal_handler(signum, frame):
            log.info("enhanced_server.shutdown_signal signal=%s", signum)
            try:
                self.shutdown_event.set()
            except Exception:
                pass

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    async def run_stdio_original(self):
        log.info("enhanced_server.start_stdio_original")
        if stdio_server is None:
            raise RuntimeError("stdio server transport is not available in this environment")
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.shutdown_event
            )

    async def run_http_enhanced(self):
        """Run server with HTTP transport (enhanced feature)."""
        if not FASTAPI_AVAILABLE or not UVICORN_AVAILABLE:
            log.error("enhanced_server.http_missing_deps")
            raise RuntimeError("FastAPI and Uvicorn are required for HTTP transport")

        log.info("enhanced_server.start_http_enhanced")

        app = FastAPI(title="Enhanced MCP Server", version="1.0.0")
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"]
        )

        @app.get("/health")
        async def health_check():
            return {"status": "healthy", "transport": self.transport}

        @app.get("/tools")
        async def get_tools():
            return {"tools": [tool.__class__.__name__ for tool in self.tools]}

        # Pick port from environment or config (align with .env.template and docker-compose)
        port = int(os.getenv("MCP_SERVER_PORT", getattr(self.config.server, "port", 8080)))
        host = os.getenv("MCP_SERVER_HOST", getattr(self.config.server, "host", "0.0.0.0"))

        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="info"
        )

        server = uvicorn.Server(config)
        await server.serve()

    async def run(self):
        """Run the server with configured transport."""
        if self.transport == "stdio":
            await self.run_stdio_original()
        elif self.transport == "http":
            await self.run_http_enhanced()
        else:
            log.error("enhanced_server.invalid_transport transport=%s", self.transport)
            raise ValueError(f"Invalid transport: {self.transport}")

# MAIN
async def main_enhanced() -> None:
    _maybe_setup_uvloop()
    _setup_logging()

    # Align env names with .env.template / README
    transport = os.getenv("MCP_SERVER_TRANSPORT", "stdio").lower()
    tools_pkg = os.getenv("TOOLS_PACKAGE", "mcp_server.tools")
    include = _parse_csv_env("TOOL_INCLUDE")
    exclude = _parse_csv_env("TOOL_EXCLUDE")
    shutdown_grace = float(os.getenv("MCP_SERVER_SHUTDOWN_GRACE_PERIOD", "30"))

    # Load tools
    tools = _load_tools_from_package(tools_pkg, include=include, exclude=exclude)
    log.info("enhanced_main.starting transport=%s tools_pkg=%s tools_count=%d include=%s exclude=%s shutdown_grace=%.1fs",
             transport, tools_pkg, len(tools), include, exclude, shutdown_grace)

    # Use the repo's config API
    config = get_config()

    server = EnhancedMCPServer(tools=tools, transport=transport, config=config)

    tool_names = [tool.__class__.__name__ for tool in tools]
    log.info("enhanced_main.tools_loaded tools=%s", tool_names)

    if server.server:
        await _serve(server.server, shutdown_grace=shutdown_grace)
    else:
        # If MCPServerBase not available, run HTTP/stdio transports if requested (for local testing)
        if transport == "http":
            await server.run_http_enhanced()
        elif transport == "stdio":
            await server.run_stdio_original()
        else:
            raise RuntimeError("No underlying MCP server available and requested transport unknown")

if __name__ == "__main__":
    with contextlib.suppress(ImportError):
        pass
    asyncio.run(main_enhanced())
```

```python
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
```

```python
# File: config.py
"""
Configuration management system for MCP server.
Production-ready implementation with validation, hot-reload, and sensitive data handling.
"""
import os
import logging
import json
import yaml
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict

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
