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
