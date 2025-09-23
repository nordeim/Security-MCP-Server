"""
Enhanced MCP Server with comprehensive features and production-ready implementation.
All security and reliability fixes applied.
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
from typing import Dict, List, Optional, Set, Any, Sequence
from datetime import datetime
import json
import contextlib

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks, Response
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from starlette.requests import Request
    from sse_starlette.sse import EventSourceResponse
    from pydantic import BaseModel, Field
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    BaseModel = None

try:
    import uvicorn
    UVICORN_AVAILABLE = True
except ImportError:
    UVICORN_AVAILABLE = False

try:
    from mcp.server import Server as MCPServerBase
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    MCPServerBase = None
    stdio_server = None
    Tool = None
    TextContent = None

try:
    from prometheus_client import CONTENT_TYPE_LATEST
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain"

from .config import get_config
from .health import HealthCheckManager, HealthStatus, ToolAvailabilityHealthCheck
from .base_tool import MCPBaseTool, ToolInput, ToolOutput
from .metrics import MetricsManager

log = logging.getLogger(__name__)

# Patterns to exclude from tool discovery
EXCLUDED_PATTERNS = {'Test', 'Mock', 'Base', 'Abstract', '_', 'Example'}


def _maybe_setup_uvloop() -> None:
    """Optional uvloop installation for better performance."""
    try:
        import uvloop
        uvloop.install()
        log.info("uvloop.installed")
    except ImportError:
        log.debug("uvloop.not_available")
    except Exception as e:
        log.debug("uvloop.setup_failed error=%s", str(e))


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
    Discover and instantiate concrete MCPBaseTool subclasses with enhanced filtering.
    """
    tools: List[MCPBaseTool] = []
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
        for name, obj in inspect.getmembers(module, inspect.isclass):
            # Skip if name suggests it's not a real tool
            if any(pattern in name for pattern in EXCLUDED_PATTERNS):
                log.debug("tool_discovery.class_excluded name=%s pattern_match", name)
                continue

            # Check for explicit tool marker
            if hasattr(obj, '_is_tool') and not obj._is_tool:
                log.debug("tool_discovery.class_excluded name=%s is_tool=False", name)
                continue

            try:
                if not issubclass(obj, MCPBaseTool) or obj is MCPBaseTool:
                    continue
            except Exception:
                continue

            if include and name not in include:
                log.debug("tool_discovery.tool_skipped name=%s reason=include_filter", name)
                continue
            if exclude and name in exclude:
                log.debug("tool_discovery.tool_skipped name=%s reason=exclude_filter", name)
                continue

            try:
                inst = obj()
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


# Pydantic models for HTTP API validation
if FASTAPI_AVAILABLE and BaseModel:
    class ToolExecutionRequest(BaseModel):
        """Validated tool execution request."""
        target: str = Field(..., min_length=1, max_length=255)
        extra_args: str = Field(default="", max_length=2048)
        timeout_sec: Optional[float] = Field(None, ge=1, le=3600)
        correlation_id: Optional[str] = Field(None, max_length=64)


class ToolRegistry:
    """Tool Registry that holds tools and enabled set."""
    def __init__(self, config, tools: List[MCPBaseTool]):
        self.config = config
        self.tools: Dict[str, MCPBaseTool] = {}
        self.enabled_tools: Set[str] = set()
        self._register_tools_from_list(tools)

    def _register_tools_from_list(self, tools: List[MCPBaseTool]):
        """Register tools and initialize their components."""
        for tool in tools:
            tool_name = tool.__class__.__name__
            self.tools[tool_name] = tool

            if self._is_tool_enabled(tool_name):
                self.enabled_tools.add(tool_name)

            if hasattr(tool, '_initialize_metrics'):
                tool._initialize_metrics()
            if hasattr(tool, '_initialize_circuit_breaker'):
                tool._initialize_circuit_breaker()

            log.info("tool_registry.tool_registered name=%s", tool_name)

    def _is_tool_enabled(self, tool_name: str) -> bool:
        """Check if tool is enabled based on include/exclude filters."""
        include = _parse_csv_env("TOOL_INCLUDE")
        exclude = _parse_csv_env("TOOL_EXCLUDE")
        if include and tool_name not in include:
            return False
        if exclude and tool_name in exclude:
            return False
        return True

    def get_tool(self, tool_name: str) -> Optional[MCPBaseTool]:
        """Get a tool by name."""
        return self.tools.get(tool_name)

    def get_enabled_tools(self) -> Dict[str, MCPBaseTool]:
        """Get all enabled tools."""
        return {name: tool for name, tool in self.tools.items() if name in self.enabled_tools}

    def enable_tool(self, tool_name: str):
        """Enable a tool."""
        if tool_name in self.tools:
            self.enabled_tools.add(tool_name)
            log.info("tool_registry.enabled name=%s", tool_name)

    def disable_tool(self, tool_name: str):
        """Disable a tool."""
        self.enabled_tools.discard(tool_name)
        log.info("tool_registry.disabled name=%s", tool_name)

    def get_tool_info(self) -> List[Dict[str, Any]]:
        """Get information about all tools."""
        info = []
        for name, tool in self.tools.items():
            tool_info = {
                "name": name,
                "enabled": name in self.enabled_tools,
                "command": getattr(tool, "command_name", None),
                "description": tool.__doc__ or "No description",
                "concurrency": getattr(tool, "concurrency", None),
                "timeout": getattr(tool, "default_timeout_sec", None),
                "has_metrics": hasattr(tool, 'metrics') and tool.metrics is not None,
                "has_circuit_breaker": hasattr(tool, '_circuit_breaker') and tool._circuit_breaker is not None
            }
            # Add tool-specific info if available
            if hasattr(tool, 'get_tool_info'):
                try:
                    tool_info.update(tool.get_tool_info())
                except Exception as e:
                    log.warning("tool_info.failed name=%s error=%s", name, str(e))
            info.append(tool_info)
        return info


class EnhancedMCPServer:
    """Enhanced MCP Server with complete integration and all fixes."""
    def __init__(self, tools: List[MCPBaseTool], transport: str = "stdio", config=None):
        self.tools = tools
        self.transport = transport
        self.config = config or get_config()
        self.tool_registry = ToolRegistry(self.config, tools)
        self.health_manager = HealthCheckManager(config=self.config)
        self.metrics_manager = MetricsManager()
        self.shutdown_event = asyncio.Event()
        self._background_tasks: Set[asyncio.Task] = set()

        # Initialize MCP server and register tools
        if MCP_AVAILABLE and MCPServerBase:
            try:
                self.server = MCPServerBase("enhanced-mcp-server")
                self._register_tools_mcp()
            except Exception as e:
                log.error("mcp_server.initialization_failed error=%s", str(e))
                self.server = None
        else:
            self.server = None

        # Configure health checks only; defer monitoring task start
        self._initialize_health_checks()

        # Consolidated signal handlers
        self._setup_enhanced_signal_handlers()

        log.info("enhanced_server.initialized transport=%s tools=%d", self.transport, len(self.tools))

    def _register_tools_mcp(self):
        """Register tools with MCP server."""
        if not self.server:
            return

        registered_names: List[str] = []
        for tool in self.tools:
            name = tool.__class__.__name__
            self.server.register_tool(
                name=name,
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
                handler=self._create_mcp_tool_handler(tool)
            )
            registered_names.append(name)
            log.debug("mcp_tool.registered name=%s", name)

        log.info("mcp_tools.registration_complete count=%d names=%s", len(registered_names), registered_names)

    def _create_mcp_tool_handler(self, tool: MCPBaseTool):
        """Create MCP tool handler."""
        async def handler(target: str, extra_args: str = "", timeout_sec: Optional[float] = None):
            try:
                input_data = ToolInput(
                    target=target,
                    extra_args=extra_args,
                    timeout_sec=timeout_sec
                )
                result = await tool.run(input_data)
                payload = result.dict() if hasattr(result, 'dict') else str(result)
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(payload, indent=2)
                    )
                ]
            except Exception as e:
                log.error("mcp_tool_handler.error tool=%s target=%s error=%s",
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
        return handler

    def _initialize_health_checks(self):
        """Configure health checks; defer monitoring task start to explicit method."""
        # Add tool availability check
        self.health_manager.add_health_check(
            ToolAvailabilityHealthCheck(self.tool_registry),
            priority=2
        )
        # Add tool-specific health checks
        for tool_name, tool in self.tool_registry.tools.items():
            self.health_manager.register_check(
                name=f"tool_{tool_name}",
                check_func=self._create_tool_health_check(tool),
                priority=2
            )

    def start_background_tasks(self):
        """Start background monitoring after event loop is ready."""
        task = asyncio.create_task(self.health_manager.start_monitoring(), name="health_monitoring")
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        log.info("background_tasks.started count=%d", len(self._background_tasks))

    def _create_tool_health_check(self, tool: MCPBaseTool):
        """Create health check function for a tool."""
        async def check_tool_health() -> HealthStatus:
            try:
                if not tool._resolve_command():
                    return HealthStatus.UNHEALTHY

                if hasattr(tool, '_circuit_breaker') and tool._circuit_breaker:
                    from .circuit_breaker import CircuitBreakerState
                    if tool._circuit_breaker.state == CircuitBreakerState.OPEN:
                        return HealthStatus.DEGRADED

                return HealthStatus.HEALTHY
            except Exception:
                return HealthStatus.UNHEALTHY
        return check_tool_health

    def _setup_enhanced_signal_handlers(self):
        """Set up thread-safe signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            """Thread-safe signal handler."""
            log.info("enhanced_server.shutdown_signal signal=%s", signum)
            try:
                loop = asyncio.get_event_loop()
                loop.call_soon_threadsafe(self.shutdown_event.set)
            except Exception:
                self.shutdown_event.set()

        with contextlib.suppress(Exception):
            signal.signal(signal.SIGINT, signal_handler)
        with contextlib.suppress(Exception):
            signal.signal(signal.SIGTERM, signal_handler)

    async def run_stdio_original(self):
        """Run server with stdio transport."""
        log.info("enhanced_server.start_stdio_original")
        if not MCP_AVAILABLE or stdio_server is None or self.server is None:
            raise RuntimeError("stdio transport is not available; MCP stdio support missing")
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.shutdown_event
            )

    async def run_http_enhanced(self):
        """Run server with HTTP transport and validated inputs."""
        if not FASTAPI_AVAILABLE or not UVICORN_AVAILABLE:
            log.error("enhanced_server.http_missing_deps")
            raise RuntimeError("FastAPI and Uvicorn are required for HTTP transport")

        log.info("enhanced_server.start_http_enhanced")

        app = FastAPI(title="Enhanced MCP Server", version="2.0.0")
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"]
        )

        @app.get("/health")
        async def health_check():
            """Health check endpoint."""
            status = await self.health_manager.get_overall_health()
            checks = await self.health_manager.get_all_check_results()
            response_status_code = 200
            if status == HealthStatus.UNHEALTHY:
                response_status_code = 503
            elif status == HealthStatus.DEGRADED:
                response_status_code = 207
            return JSONResponse(
                status_code=response_status_code,
                content={
                    "status": status.value,
                    "timestamp": datetime.utcnow().isoformat(),
                    "transport": self.transport,
                    "checks": checks
                }
            )

        @app.get("/tools")
        async def get_tools():
            """Get list of available tools."""
            return {"tools": self.tool_registry.get_tool_info()}

        if FASTAPI_AVAILABLE and BaseModel:
            @app.post("/tools/{tool_name}/execute")
            async def execute_tool(
                tool_name: str,
                request: ToolExecutionRequest,
                background_tasks: BackgroundTasks
            ):
                """Execute a tool with validated input."""
                tool = self.tool_registry.get_tool(tool_name)
                if not tool:
                    raise HTTPException(status_code=404, detail=f"Tool {tool_name} not found")

                if tool_name not in self.tool_registry.enabled_tools:
                    raise HTTPException(status_code=403, detail=f"Tool {tool_name} is disabled")

                try:
                    tool_input = ToolInput(
                        target=request.target,
                        extra_args=request.extra_args,
                        timeout_sec=request.timeout_sec,
                        correlation_id=request.correlation_id
                    )
                    result = await tool.run(tool_input)

                    # Record metrics in background
                    if hasattr(tool, 'metrics') and tool.metrics:
                        background_tasks.add_task(self._record_tool_metrics, tool_name, result)

                    return result.dict() if hasattr(result, 'dict') else result.__dict__
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=str(e))
                except Exception as e:
                    log.error("tool_execution_failed tool=%s error=%s", tool_name, str(e))
                    raise HTTPException(status_code=500, detail="Tool execution failed")

        @app.get("/events")
        async def events(request: Request):
            """SSE endpoint for real-time updates."""
            async def event_generator():
                while not await request.is_disconnected():
                    health_status = await self.health_manager.get_overall_health()
                    health_data = {
                        "type": "health",
                        "data": {
                            "status": health_status.value,
                            "timestamp": datetime.utcnow().isoformat()
                        }
                    }
                    yield json.dumps(health_data)
                    await asyncio.sleep(5)
            return EventSourceResponse(event_generator())

        @app.get("/metrics")
        async def metrics():
            """Prometheus metrics endpoint."""
            if PROMETHEUS_AVAILABLE:
                metrics_text = self.metrics_manager.get_prometheus_metrics()
                if metrics_text:
                    return Response(content=metrics_text, media_type=CONTENT_TYPE_LATEST)
            return JSONResponse(content=self.metrics_manager.get_all_stats())

        @app.post("/tools/{tool_name}/enable")
        async def enable_tool(tool_name: str):
            """Enable a tool."""
            if tool_name not in self.tool_registry.tools:
                raise HTTPException(status_code=404, detail=f"Tool {tool_name} not found")
            self.tool_registry.enable_tool(tool_name)
            return {"message": f"Tool {tool_name} enabled"}

        @app.post("/tools/{tool_name}/disable")
        async def disable_tool(tool_name: str):
            """Disable a tool."""
            if tool_name not in self.tool_registry.tools:
                raise HTTPException(status_code=404, detail=f"Tool {tool_name} not found")
            self.tool_registry.disable_tool(tool_name)
            return {"message": f"Tool {tool_name} disabled"}

        port = int(os.getenv("MCP_SERVER_PORT", self.config.server.port))
        host = os.getenv("MCP_SERVER_HOST", self.config.server.host)
        config = uvicorn.Config(app, host=host, port=port, log_level="info", access_log=True)
        server = uvicorn.Server(config)
        await server.serve()

    async def _record_tool_metrics(self, tool_name: str, result: ToolOutput):
        """Record tool execution metrics."""
        try:
            self.metrics_manager.record_tool_execution(
                tool_name=tool_name,
                success=(getattr(result, "returncode", 0) == 0),
                execution_time=getattr(result, "execution_time", 0.0) or 0.0,
                timed_out=bool(getattr(result, "timed_out", False)),
                error_type=getattr(result, "error_type", None)
            )
        except Exception as e:
            log.warning("metrics.record_failed tool=%s error=%s", tool_name, str(e))

    async def run(self):
        """Run the server with configured transport."""
        # Start background monitoring once the loop is ready
        self.start_background_tasks()

        if self.transport == "http":
            if not FASTAPI_AVAILABLE or not UVICORN_AVAILABLE:
                log.warning("transport.http_deps_missing falling_back=stdio hint='pip install fastapi uvicorn sse-starlette prometheus-client'")
                if MCP_AVAILABLE and self.server is not None and stdio_server is not None:
                    await self.run_stdio_original()
                    return
                raise RuntimeError("HTTP transport requested but FastAPI/Uvicorn are missing, and stdio fallback is unavailable")
            await self.run_http_enhanced()
            return

        if self.transport == "stdio":
            if MCP_AVAILABLE and self.server is not None and stdio_server is not None:
                await self.run_stdio_original()
                return
            raise RuntimeError("stdio transport requested but MCP stdio support is unavailable")

        log.error("enhanced_server.invalid_transport transport=%s", self.transport)
        raise ValueError(f"Invalid transport: {self.transport}")

    async def cleanup(self):
        """Clean up background tasks."""
        # Cancel all background tasks
        for task in self._background_tasks:
            if not task.done():
                task.cancel()
        # Wait for cancellation
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)


async def main_enhanced() -> None:
    """Main entry point for enhanced MCP server."""
    _maybe_setup_uvloop()
    _setup_logging()

    transport = os.getenv("MCP_SERVER_TRANSPORT", "stdio").lower()
    tools_pkg = os.getenv("TOOLS_PACKAGE", "mcp_server.tools")
    include = _parse_csv_env("TOOL_INCLUDE")
    exclude = _parse_csv_env("TOOL_EXCLUDE")
    shutdown_grace = float(os.getenv("MCP_SERVER_SHUTDOWN_GRACE_PERIOD", "30"))

    tools = _load_tools_from_package(tools_pkg, include=include, exclude=exclude)
    log.info(
        "enhanced_main.starting transport=%s tools_pkg=%s tools_count=%d include=%s exclude=%s shutdown_grace=%.1fs",
        transport, tools_pkg, len(tools), include, exclude, shutdown_grace
    )

    config = get_config()
    server = EnhancedMCPServer(tools=tools, transport=transport, config=config)
    tool_names = [tool.__class__.__name__ for tool in tools]
    log.info("enhanced_main.tools_loaded tools=%s", tool_names)

    try:
        # Use the unified run path; stdio uses stdio_server() via run()
        await server.run()
    finally:
        await server.cleanup()


if __name__ == "__main__":
    with contextlib.suppress(ImportError):
        pass
    asyncio.run(main_enhanced())
