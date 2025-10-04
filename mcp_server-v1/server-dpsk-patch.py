"""
Enhanced MCP Server with comprehensive features and production-ready implementation.
Hardened HTTP dependency validation (runtime), explicit logging, and robust startup.
"""

import asyncio
import importlib
import inspect
import logging
import os
import pkgutil
import signal
import sys
from typing import Dict, List, Optional, Set, Any, Sequence
from datetime import datetime
import json
import contextlib

# Configure logging first to capture initialization issues
log = logging.getLogger(__name__)

# FastAPI stack (import guarded; validated at runtime)
try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks, Response
    from fastapi.middleware.cors import CORSMiddleware
    from starlette.responses import JSONResponse
    from starlette.requests import Request
    from sse_starlette.sse import EventSourceResponse
    from pydantic import BaseModel, Field
except Exception as e:
    log.debug("fastapi_import.failed error=%s", str(e))
    # Defer hard failure to runtime validation in run_http_enhanced()
    FastAPI = None
    HTTPException = None
    BackgroundTasks = None
    Response = None
    CORSMiddleware = None
    JSONResponse = None
    Request = None
    EventSourceResponse = None
    BaseModel = None
    Field = None

# Uvicorn (import guarded; validated at runtime)
try:
    import uvicorn
except Exception as e:
    log.debug("uvicorn_import.failed error=%s", str(e))
    uvicorn = None

# MCP (optional dependencies)
try:
    from mcp.server import Server as MCPServerBase
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except Exception as e:
    log.debug("mcp_import.failed error=%s", str(e))
    MCPServerBase = None
    stdio_server = None
    Tool = None
    TextContent = None

# Prometheus client (optional)
try:
    from prometheus_client import CONTENT_TYPE_LATEST
except Exception as e:
    log.debug("prometheus_import.failed error=%s", str(e))
    CONTENT_TYPE_LATEST = "text/plain"

# Local imports (maintain original structure)
from .config import get_config
from .health import HealthCheckManager, HealthStatus, ToolAvailabilityHealthCheck
from .metrics import MetricsManager
from .tool import MCPBaseTool, ToolInput, ToolOutput

def _setup_logging():
    """Initialize logging with enhanced configuration."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

def _maybe_setup_uvloop():
    """Setup uvloop if available for better performance."""
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        log.debug("uvloop.activated")
    except ImportError:
        log.debug("uvloop.not_available")
        pass

def _parse_csv_env(env_var: str) -> Optional[Set[str]]:
    """Parse CSV environment variable into a set."""
    value = os.getenv(env_var)
    if not value:
        return None
    return {item.strip() for item in value.split(",") if item.strip()}

# Tool discovery patterns to exclude
EXCLUDED_PATTERNS = {"test_", "base", "abstract", "mock"}

def _load_tools_from_package(
    package_path: str,
    include: Optional[Sequence[str]] = None,
    exclude: Optional[Sequence[str]] = None,
) -> List[MCPBaseTool]:
    """Discover and instantiate concrete MCPBaseTool subclasses with enhanced filtering."""
    tools: List[MCPBaseTool] = []
    log.info("tool_discovery.starting package=%s include=%s exclude=%s",
             package_path, include, exclude)
    
    try:
        pkg = importlib.import_module(package_path)
        log.debug("tool_discovery.package_imported path=%s", package_path)
    except ImportError as e:
        log.error("tool_discovery.package_import_failed path=%s error=%s", package_path, str(e))
        return tools

    package_dir = os.path.dirname(pkg.__file__) if hasattr(pkg, '__file__') else None

    for importer, modname, ispkg in pkgutil.iter_modules([package_dir] if package_dir else None):
        if ispkg:
            continue

        full_modname = f"{package_path}.{modname}"
        try:
            module = importlib.import_module(full_modname)
            log.debug("tool_discovery.module_loaded module=%s", full_modname)
        except ImportError as e:
            log.warning("tool_discovery.module_load_failed module=%s error=%s", full_modname, str(e))
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

                # Apply include/exclude filters
                if include and name not in include:
                    log.debug("tool_discovery.class_excluded name=%s not_in_include", name)
                    continue
                if exclude and name in exclude:
                    log.debug("tool_discovery.class_excluded name=%s in_exclude", name)
                    continue

                # Instantiate tool
                tool_instance = obj()
                tools.append(tool_instance)
                tool_count_in_module += 1
                log.debug("tool_discovery.tool_instantiated name=%s", name)

            except Exception as e:
                log.warning("tool_discovery.instantiation_failed name=%s error=%s", name, str(e))
                continue

        if tool_count_in_module > 0:
            log.info("tool_discovery.module_complete module=%s tools=%d", full_modname, tool_count_in_module)

    log.info("tool_discovery.complete total_tools=%d", len(tools))
    return tools

# Pydantic models for HTTP API validation (guarded by import availability)
if BaseModel is not None:
    class ToolExecutionRequest(BaseModel):
        """Validated tool execution request."""
        target: str = Field(..., min_length=1, max_length=255)
        extra_args: str = Field(default="", max_length=2048)
        timeout_sec: Optional[float] = Field(None, ge=1, le=3600)
        correlation_id: Optional[str] = Field(None, max_length=64)
else:
    # Fallback for when Pydantic is not available
    ToolExecutionRequest = None

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
            
            # Initialize tool components regardless of enabled status
            if hasattr(tool, '_initialize_metrics'):
                tool._initialize_metrics()
            if hasattr(tool, '_initialize_circuit_breaker'):
                tool._initialize_circuit_breaker()

            # Check if tool should be enabled
            if self._is_tool_enabled(tool_name):
                self.enabled_tools.add(tool_name)
                log.info("tool_registry.tool_enabled name=%s", tool_name)
            else:
                log.info("tool_registry.tool_disabled name=%s", tool_name)

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
            log.info("tool_registry.tool_enabled name=%s", tool_name)

    def disable_tool(self, tool_name: str):
        """Disable a tool."""
        self.enabled_tools.discard(tool_name)
        log.info("tool_registry.tool_disabled name=%s", tool_name)

    def get_tool_info(self) -> List[Dict[str, Any]]:
        """Get information about all tools."""
        info: List[Dict[str, Any]] = []
        for name, tool in self.tools.items():
            tool_info: Dict[str, Any] = {
                "name": name,
                "enabled": name in self.enabled_tools,
                "command": getattr(tool, "command_name", None),
                "description": getattr(tool, "description", ""),
                "concurrency": getattr(tool, "concurrency", None),
                "timeout": getattr(tool, "default_timeout_sec", None),
                "has_metrics": hasattr(tool, 'metrics') and tool.metrics is not None,
                "has_circuit_breaker": hasattr(tool, '_circuit_breaker') and tool._circuit_breaker is not None,
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

        # Initialize MCP server if available
        if MCPServerBase is not None:
            try:
                self.server = MCPServerBase("enhanced-mcp-server")
                self._register_tools_mcp()
                log.info("mcp_server.initialized")
            except Exception as e:
                log.error("mcp_server.initialization_failed error=%s", str(e))
                self.server = None
        else:
            self.server = None
            log.warning("mcp_server.dependencies_missing")

        self._initialize_monitoring()
        self._setup_enhanced_signal_handlers()
        
        log.info("enhanced_server.initialized transport=%s tools=%d enabled_tools=%d", 
                self.transport, len(self.tools), len(self.tool_registry.enabled_tools))

    def _register_tools_mcp(self):
        """Register tools with MCP server."""
        if not self.server:
            return
        
        for tool in self.tools:
            # Only register enabled tools with MCP
            if tool.__class__.__name__ not in self.tool_registry.enabled_tools:
                log.debug("mcp_tool_registration.skipped name=%s disabled", tool.__class__.__name__)
                continue
                
            self.server.register_tool(
                name=tool.__class__.__name__,
                description=getattr(tool, "description", "MCP tool"),
                parameters={
                    "target": {
                        "type": "string",
                        "description": "Target for tool execution"
                    },
                    "extra_args": {
                        "type": "string",
                        "description": "Additional arguments",
                        "default": ""
                    },
                    "timeout_sec": {
                        "type": "number",
                        "description": "Timeout in seconds",
                        "optional": True
                    }
                },
                handler=self._create_mcp_tool_handler(tool)
            )
            log.debug("mcp_tool_registered name=%s", tool.__class__.__name__)

    def _create_mcp_tool_handler(self, tool: MCPBaseTool):
        """Create MCP tool handler with robust error handling."""
        async def handler(target: str, extra_args: str = "", timeout_sec: Optional[float] = None):
            try:
                tool_input = ToolInput(
                    target=target,
                    extra_args=extra_args,
                    timeout_sec=timeout_sec
                )
                result = await tool.run(tool_input)
                
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            result.dict() if hasattr(result, 'dict') else str(result),
                            indent=2
                        )
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

    def _initialize_monitoring(self):
        """Initialize health and metrics monitoring with proper task storage."""
        # Add tool availability check
        self.health_manager.add_health_check(
            ToolAvailabilityHealthCheck(self.tool_registry),
            priority=2
        )
        
        # Add tool-specific health checks
        for tool_name, tool in self.tool_registry.tools.items():
            self.health_manager.register_check(
                f"tool_{tool_name}",
                check_func=self._create_tool_health_check(tool),
                priority=2
            )
        
        # Start monitoring with proper task storage
        task = asyncio.create_task(self.health_manager.start_monitoring(), name="health_monitoring")
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

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
            except Exception as e:
                log.warning("tool_health_check.failed tool=%s error=%s", tool.__class__.__name__, str(e))
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
            except RuntimeError:
                # Fallback if no loop in current thread
                self.shutdown_event.set()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    async def run_stdio_original(self):
        """Run server with stdio transport."""
        log.info("enhanced_server.starting_stdio")
        if MCPServerBase is None or stdio_server is None:
            raise RuntimeError("MCP dependencies not available for stdio transport")
        
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.shutdown_event
            )

    # ---------- Hardened HTTP dependency validation ----------

    @staticmethod
    def _validate_http_deps(require: bool = True) -> bool:
        """
        Validate HTTP transport dependencies at runtime, with explicit logging.
        
        Returns True if all deps present; False if missing and require=False.
        Raises RuntimeError if missing and require=True.
        """
        missing = []
        details = []

        def _try_import(mod: str):
            try:
                m = importlib.import_module(mod)
                version = getattr(m, '__version__', 'unknown')
                details.append(f"{mod}={version}")
                return True
            except Exception as e:
                log.error("enhanced_server.http_dep_error mod=%s err=%s", mod, e)
                return False

        # Core HTTP dependencies
        core_deps = ["fastapi", "uvicorn", "starlette"]
        for mod in core_deps:
            if not _try_import(mod):
                missing.append(mod)

        # Optional performance dependencies
        optional_deps = ["orjson", "python_multipart", "jinja2", "uvloop", "httptools"]
        for mod in optional_deps:
            if not _try_import(mod):
                log.debug("enhanced_server.http_optional_missing mod=%s", mod)

        if missing:
            msg = f"HTTP transport missing dependencies: {missing}. Details: {details}"
            if require:
                raise RuntimeError(msg)
            else:
                log.warning("enhanced_server.http_missing_deps %s", msg)
                return False

        log.info("enhanced_server.http_deps_ok details=%s", details)
        return True

    async def run_http_enhanced(self):
        """Run server with HTTP transport and validated inputs."""
        # Validate deps at runtime using the active interpreter
        self._validate_http_deps(require=True)

        log.info("enhanced_server.starting_http")
        
        # Build FastAPI app
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
                    "version": "2.0.0",
                    "checks": checks
                }
            )

        @app.get("/tools")
        async def get_tools():
            """Get list of available tools."""
            return {"tools": self.tool_registry.get_tool_info()}

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
                    background_tasks.add_task(
                        self._record_tool_metrics,
                        tool_name,
                        result
                    )
                
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
                        "status": health_status.value,
                        "timestamp": datetime.utcnow().isoformat(),
                        "tools_enabled": len(self.tool_registry.enabled_tools),
                        "tools_total": len(self.tool_registry.tools)
                    }
                    yield json.dumps(health_data)
                    await asyncio.sleep(5)
            
            return EventSourceResponse(event_generator())

        @app.get("/metrics")
        async def metrics():
            """Prometheus metrics endpoint."""
            metrics_text = self.metrics_manager.get_prometheus_metrics()
            if metrics_text:
                return Response(content=metrics_text, media_type=CONTENT_TYPE_LATEST)
            
            return JSONResponse(
                content=self.metrics_manager.get_all_stats()
            )

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

        # Server configuration
        port = int(os.getenv("MCP_SERVER_PORT", self.config.server.port))
        host = os.getenv("MCP_SERVER_HOST", self.config.server.host)

        if uvicorn is None:
            raise RuntimeError("Uvicorn not available for HTTP transport")

        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="info",
            access_log=True
        )
        
        server = uvicorn.Server(config)
        await server.serve()

    async def _record_tool_metrics(self, tool_name: str, result: ToolOutput):
        """Record tool execution metrics."""
        try:
            execution_time = getattr(result, 'execution_time', 0)
            success = getattr(result, 'success', False)
            
            self.metrics_manager.record_tool_execution(
                tool_name,
                execution_time,
                success
            )
        except Exception as e:
            log.warning("metrics.record_failed tool=%s error=%s", tool_name, str(e))

    async def run(self):
        """Run the server with configured transport."""
        if self.transport == "stdio":
            await self.run_stdio_original()
        elif self.transport == "http":
            await self.run_http_enhanced()
        else:
            log.error("enhanced_server.invalid_transport transport=%s", self.transport)
            raise ValueError(f"Invalid transport: {self.transport}")

    async def cleanup(self):
        """Clean up background tasks gracefully."""
        if not self._background_tasks:
            return

        # Cancel all background tasks
        for task in self._background_tasks:
            if not task.done():
                task.cancel()
        
        # Wait for cancellation with timeout
        if self._background_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._background_tasks, return_exceptions=True),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                log.warning("cleanup.tasks_timeout remaining_tasks=%d", len(self._background_tasks))
        
        self._background_tasks.clear()
        log.info("enhanced_server.cleanup_complete")

async def _serve(server: MCPServerBase, shutdown_grace: float) -> None:
    """Handle server lifecycle with signal handling and graceful shutdown."""
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    
    def _signal_handler(sig: int) -> None:
        log.info("server.signal_received signal=%s initiating_shutdown", sig)
        stop.set()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler, sig)
        except NotImplementedError:
            # Signal handlers are only supported on UNIX
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
    
    log.info("server.shutting_down")
    serve_task.cancel()
    
    try:
        await asyncio.wait_for(serve_task, timeout=shutdown_grace)
        log.info("server.shutdown_completed")
    except asyncio.TimeoutError:
        log.error("server.shutdown_timeout grace_period=%.1fs", shutdown_grace)
    except Exception as e:
        log.error("server.shutdown_error error=%s", str(e))

async def main_enhanced():
    """Main entry point for enhanced MCP server."""
    _maybe_setup_uvloop()
    _setup_logging()
    
    transport = os.getenv("MCP_SERVER_TRANSPORT", "stdio").lower()
    tools_pkg = os.getenv("TOOLS_PACKAGE", "mcp_server.tools")
    include = _parse_csv_env("TOOL_INCLUDE")
    exclude = _parse_csv_env("TOOL_EXCLUDE")
    shutdown_grace = float(os.getenv("MCP_SERVER_SHUTDOWN_GRACE_PERIOD", "30"))
    
    tools = _load_tools_from_package(tools_pkg, include=include, exclude=exclude)
    
    log.info("enhanced_main.starting transport=%s tools_pkg=%s tools_count=%d include=%s exclude=%s shutdown_grace=%.1fs",
             transport, tools_pkg, len(tools), include, exclude, shutdown_grace)
    
    config = get_config()
    server = EnhancedMCPServer(tools=tools, transport=transport, config=config)
    
    tool_names = [tool.__class__.__name__ for tool in tools]
    enabled_tool_names = list(server.tool_registry.enabled_tools)
    log.info("enhanced_main.tools_loaded tools=%s enabled_tools=%s", tool_names, enabled_tool_names)
    
    try:
        if transport == "stdio" and server.server:
            await _serve(server.server, shutdown_grace=shutdown_grace)
        else:
            await server.run()
    except Exception as e:
        log.error("enhanced_main.runtime_error error=%s", str(e))
        raise
    finally:
        await server.cleanup()
        log.info("enhanced_main.shutdown_complete")

if __name__ == "__main__":
    # Suppress import errors for clean startup
    with contextlib.suppress(ImportError):
        pass
    asyncio.run(main_enhanced())
