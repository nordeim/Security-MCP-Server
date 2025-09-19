"""
Enhanced MCP Server with comprehensive features and production-ready implementation.
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
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

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
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

from .config import get_config
from .health import HealthCheckManager, HealthStatus
from .base_tool import MCPBaseTool, ToolInput, ToolOutput
from .metrics import MetricsManager

log = logging.getLogger(__name__)


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
    Discover and instantiate concrete MCPBaseTool subclasses under package_path.
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
        for _, obj in inspect.getmembers(module, inspect.isclass):
            try:
                if not issubclass(obj, MCPBaseTool) or obj is MCPBaseTool:
                    continue
            except Exception:
                continue

            name = obj.__name__
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
    """Enhanced MCP Server with complete integration."""
    
    def __init__(self, tools: List[MCPBaseTool], transport: str = "stdio", config=None):
        self.tools = tools
        self.transport = transport
        self.config = config or get_config()
        
        self.tool_registry = ToolRegistry(self.config, tools)
        self.health_manager = HealthCheckManager(config=self.config)
        self.metrics_manager = MetricsManager()
        
        self.shutdown_event = asyncio.Event()
        
        if MCP_AVAILABLE and MCPServerBase:
            try:
                self.server = MCPServerBase("enhanced-mcp-server")
                self._register_tools_mcp()
            except Exception as e:
                log.error("mcp_server.initialization_failed error=%s", str(e))
                self.server = None
        else:
            self.server = None
        
        self._initialize_monitoring()
        self._setup_enhanced_signal_handlers()
        
        log.info("enhanced_server.initialized transport=%s tools=%d", 
                self.transport, len(self.tools))
    
    def _register_tools_mcp(self):
        """Register tools with MCP server."""
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
                handler=self._create_mcp_tool_handler(tool)
            )
    
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
                
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(result.dict() if hasattr(result, 'dict') else str(result), indent=2)
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
        """Initialize health and metrics monitoring."""
        for tool_name, tool in self.tool_registry.tools.items():
            self.health_manager.register_check(
                name=f"tool_{tool_name}",
                check_func=self._create_tool_health_check(tool),
                priority=2
            )
        
        asyncio.create_task(self.health_manager.start_monitoring())
    
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
        """Set up signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            log.info("enhanced_server.shutdown_signal signal=%s", signum)
            try:
                self.shutdown_event.set()
            except Exception:
                pass
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def run_stdio_original(self):
        """Run server with stdio transport."""
        log.info("enhanced_server.start_stdio_original")
        if not MCP_AVAILABLE or stdio_server is None:
            raise RuntimeError("stdio server transport is not available")
        
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.shutdown_event
            )
    
    async def run_http_enhanced(self):
        """Run server with HTTP transport."""
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
        
        @app.post("/tools/{tool_name}/execute")
        async def execute_tool(
            tool_name: str,
            request: dict,
            background_tasks: BackgroundTasks
        ):
            """Execute a tool."""
            tool = self.tool_registry.get_tool(tool_name)
            if not tool:
                raise HTTPException(status_code=404, detail=f"Tool {tool_name} not found")
            
            if tool_name not in self.tool_registry.enabled_tools:
                raise HTTPException(status_code=403, detail=f"Tool {tool_name} is disabled")
            
            try:
                tool_input = ToolInput(
                    target=request.get("target"),
                    extra_args=request.get("extra_args", ""),
                    timeout_sec=request.get("timeout_sec"),
                    correlation_id=request.get("correlation_id")
                )
                
                result = await tool.run(tool_input)
                
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
        
        port = int(os.getenv("MCP_SERVER_PORT", self.config.server.port))
        host = os.getenv("MCP_SERVER_HOST", self.config.server.host)
        
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
            self.metrics_manager.record_tool_execution(
                tool_name=tool_name,
                success=(result.returncode == 0),
                execution_time=result.execution_time or 0.0,
                timed_out=result.timed_out,
                error_type=result.error_type
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
    
    log.info("server.shutting_down")
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
    log.info("enhanced_main.starting transport=%s tools_pkg=%s tools_count=%d include=%s exclude=%s shutdown_grace=%.1fs",
             transport, tools_pkg, len(tools), include, exclude, shutdown_grace)
    
    config = get_config()
    server = EnhancedMCPServer(tools=tools, transport=transport, config=config)
    
    tool_names = [tool.__class__.__name__ for tool in tools]
    log.info("enhanced_main.tools_loaded tools=%s", tool_names)
    
    if transport == "stdio" and server.server:
        await _serve(server.server, shutdown_grace=shutdown_grace)
    else:
        await server.run()


if __name__ == "__main__":
    with contextlib.suppress(ImportError):
        pass
    asyncio.run(main_enhanced())
