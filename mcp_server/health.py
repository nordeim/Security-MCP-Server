# File: health.py
"""
Health monitoring system for MCP server.
Production-ready implementation with graceful dependency handling and validation.
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Awaitable

# Graceful psutil dependency handling
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None

log = logging.getLogger(__name__)

class HealthStatus(Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"

@dataclass
class HealthCheckResult:
    """Result of a health check."""
    name: str
    status: HealthStatus
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    duration: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SystemHealth:
    """Overall system health status."""
    overall_status: HealthStatus
    checks: Dict[str, HealthCheckResult]
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

class HealthCheck:
    """Base class for health checks."""
    
    def __init__(self, name: str, timeout: float = 10.0):
        self.name = name
        self.timeout = max(1.0, timeout)  # Ensure minimum timeout
    
    async def check(self) -> HealthCheckResult:
        """Execute the health check."""
        start_time = time.time()
        try:
            result = await asyncio.wait_for(self._execute_check(), timeout=self.timeout)
            duration = time.time() - start_time
            return HealthCheckResult(
                name=self.name,
                status=result.status,
                message=result.message,
                duration=duration,
                metadata=result.metadata
            )
        except asyncio.TimeoutError:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Health check timed out after {self.timeout}s",
                duration=self.timeout
            )
        except Exception as e:
            duration = time.time() - start_time
            log.error("health_check.failed name=%s error=%s duration=%.2f", self.name, str(e), duration)
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {str(e)}",
                duration=duration
            )
    
    async def _execute_check(self) -> HealthCheckResult:
        """Override this method to implement specific health check logic."""
        raise NotImplementedError

class SystemResourceHealthCheck(HealthCheck):
    """Check system resources (CPU, memory, disk)."""
    
    def __init__(self, name: str = "system_resources", 
                 cpu_threshold: float = 80.0,
                 memory_threshold: float = 80.0,
                 disk_threshold: float = 80.0):
        super().__init__(name)
        self.cpu_threshold = max(0.0, min(100.0, cpu_threshold))
        self.memory_threshold = max(0.0, min(100.0, memory_threshold))
        self.disk_threshold = max(0.0, min(100.0, disk_threshold))
    
    async def _execute_check(self) -> HealthCheckResult:
        """Check system resources."""
        if not PSUTIL_AVAILABLE:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.DEGRADED,
                message="psutil not available for system resource monitoring",
                metadata={"psutil_available": False}
            )
        
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # Memory usage
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            
            # Disk usage
            try:
                disk = psutil.disk_usage('/')
                disk_percent = (disk.used / disk.total) * 100
            except Exception as disk_error:
                log.warning("health_check.disk_usage_failed error=%s", str(disk_error))
                disk_percent = 0.0
            
            # Determine overall status
            status = HealthStatus.HEALTHY
            messages = []
            
            if cpu_percent > self.cpu_threshold:
                status = HealthStatus.UNHEALTHY
                messages.append(f"CPU usage high: {cpu_percent:.1f}%")
            
            if memory_percent > self.memory_threshold:
                if status == HealthStatus.HEALTHY:
                    status = HealthStatus.DEGRADED
                messages.append(f"Memory usage high: {memory_percent:.1f}%")
            
            if disk_percent > self.disk_threshold:
                if status == HealthStatus.HEALTHY:
                    status = HealthStatus.DEGRADED
                messages.append(f"Disk usage high: {disk_percent:.1f}%")
            
            message = ", ".join(messages) if messages else "System resources healthy"
            
            return HealthCheckResult(
                name=self.name,
                status=status,
                message=message,
                metadata={
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory_percent,
                    "disk_percent": disk_percent,
                    "cpu_threshold": self.cpu_threshold,
                    "memory_threshold": self.memory_threshold,
                    "disk_threshold": self.disk_threshold,
                    "psutil_available": True
                }
            )
        
        except Exception as e:
            log.error("health_check.system_resources_failed error=%s", str(e))
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Failed to check system resources: {str(e)}",
                metadata={"psutil_available": PSUTIL_AVAILABLE}
            )

class ToolAvailabilityHealthCheck(HealthCheck):
    """Check availability of MCP tools."""
    
    def __init__(self, tool_registry, name: str = "tool_availability"):
        super().__init__(name)
        self.tool_registry = tool_registry
    
    async def _execute_check(self) -> HealthCheckResult:
        """Check tool availability."""
        try:
            # Validate tool registry interface
            if not hasattr(self.tool_registry, 'get_enabled_tools'):
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message="Tool registry does not support get_enabled_tools method",
                    metadata={"registry_type": type(self.tool_registry).__name__}
                )
            
            tools = self.tool_registry.get_enabled_tools()
            unavailable_tools = []
            
            for tool_name, tool in tools.items():
                try:
                    if not hasattr(tool, '_resolve_command'):
                        unavailable_tools.append(f"{tool_name} (missing _resolve_command)")
                    elif not tool._resolve_command():
                        unavailable_tools.append(tool_name)
                except Exception as tool_error:
                    unavailable_tools.append(f"{tool_name} (error: {str(tool_error)})")
            
            if unavailable_tools:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.DEGRADED,
                    message=f"Unavailable tools: {', '.join(unavailable_tools)}",
                    metadata={
                        "total_tools": len(tools),
                        "unavailable_tools": unavailable_tools,
                        "available_tools": len(tools) - len(unavailable_tools)
                    }
                )
            else:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.HEALTHY,
                    message=f"All {len(tools)} tools available",
                    metadata={
                        "total_tools": len(tools),
                        "available_tools": len(tools)
                    }
                )
        
        except Exception as e:
            log.error("health_check.tool_availability_failed error=%s", str(e))
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Failed to check tool availability: {str(e)}",
                metadata={"registry_type": type(self.tool_registry).__name__ if self.tool_registry else None}
            )

class ProcessHealthCheck(HealthCheck):
    """Check if the process is running properly."""
    
    def __init__(self, name: str = "process_health"):
        super().__init__(name)
    
    async def _execute_check(self) -> HealthCheckResult:
        """Check process health."""
        if not PSUTIL_AVAILABLE:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.DEGRADED,
                message="psutil not available for process health monitoring",
                metadata={"psutil_available": False}
            )
        
        try:
            process = psutil.Process()
            
            # Check if process is running
            if not process.is_running():
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message="Process is not running",
                    metadata={"pid": process.pid}
                )
            
            # Check process age
            create_time = datetime.fromtimestamp(process.create_time())
            age = datetime.now() - create_time
            
            # Check memory usage
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            
            # Check CPU usage
            cpu_percent = process.cpu_percent()
            
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message="Process is running",
                metadata={
                    "pid": process.pid,
                    "age_seconds": age.total_seconds(),
                    "memory_mb": round(memory_mb, 2),
                    "cpu_percent": cpu_percent,
                    "create_time": create_time.isoformat(),
                    "psutil_available": True
                }
            )
        
        except Exception as e:
            log.error("health_check.process_health_failed error=%s", str(e))
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Failed to check process health: {str(e)}",
                metadata={"psutil_available": PSUTIL_AVAILABLE}
            )

class DependencyHealthCheck(HealthCheck):
    """Check external dependencies."""
    
    def __init__(self, dependencies: List[str], name: str = "dependencies"):
        super().__init__(name)
        self.dependencies = dependencies or []
    
    async def _execute_check(self) -> HealthCheckResult:
        """Check dependency availability."""
        try:
            import importlib
            
            missing_deps = []
            available_deps = []
            
            for dep in self.dependencies:
                try:
                    importlib.import_module(dep)
                    available_deps.append(dep)
                except ImportError:
                    missing_deps.append(dep)
                except Exception as dep_error:
                    missing_deps.append(f"{dep} (error: {str(dep_error)})")
            
            if missing_deps:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Missing dependencies: {', '.join(missing_deps)}",
                    metadata={
                        "total_dependencies": len(self.dependencies),
                        "missing_dependencies": missing_deps,
                        "available_dependencies": available_deps
                    }
                )
            else:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.HEALTHY,
                    message=f"All {len(self.dependencies)} dependencies available",
                    metadata={
                        "total_dependencies": len(self.dependencies),
                        "available_dependencies": available_deps
                    }
                )
        
        except Exception as e:
            log.error("health_check.dependency_failed error=%s", str(e))
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Failed to check dependencies: {str(e)}",
                metadata={"dependencies": self.dependencies}
            )

class HealthCheckManager:
    """Manager for health checks."""
    
    def __init__(self, config=None):
        self.config = config or {}
        self.health_checks: Dict[str, HealthCheck] = {}
        self.last_health_check: Optional[SystemHealth] = None
        self.check_interval = max(5.0, float(self.config.get('check_interval', 30.0)))  # Minimum 5 seconds
        self._monitor_task = None
        
        # Initialize default health checks
        self._initialize_default_checks()
    
    def _initialize_default_checks(self):
        """Initialize default health checks."""
        try:
            # System resources check
            self.add_health_check(
                SystemResourceHealthCheck(
                    cpu_threshold=float(getattr(self.config, 'health_cpu_threshold', 80.0)),
                    memory_threshold=float(getattr(self.config, 'health_memory_threshold', 80.0)),
                    disk_threshold=float(getattr(self.config, 'health_disk_threshold', 80.0))
                )
            )
            
            # Process health check
            self.add_health_check(ProcessHealthCheck())
            
            # Dependency health check
            health_deps = getattr(self.config, 'health_dependencies', [])
            if health_deps:
                self.add_health_check(DependencyHealthCheck(health_deps))
            
            log.info("health_check_manager.initialized checks=%d interval=%.1f", 
                    len(self.health_checks), self.check_interval)
        
        except Exception as e:
            log.error("health_check_manager.initialization_failed error=%s", str(e))
    
    def add_health_check(self, health_check: HealthCheck):
        """Add a health check."""
        if health_check and health_check.name:
            self.health_checks[health_check.name] = health_check
            log.info("health_check.added name=%s", health_check.name)
        else:
            log.warning("health_check.invalid_check skipped")
    
    def remove_health_check(self, name: str):
        """Remove a health check."""
        if name in self.health_checks:
            del self.health_checks[name]
            log.info("health_check.removed name=%s", name)
    
    async def run_health_checks(self) -> SystemHealth:
        """Run all health checks and return overall health status."""
        if not self.health_checks:
            return SystemHealth(
                overall_status=HealthStatus.HEALTHY,
                checks={},
                metadata={"message": "No health checks configured"}
            )
        
        check_results = {}
        
        # Run all health checks concurrently
        tasks = []
        for name, health_check in self.health_checks.items():
            task = asyncio.create_task(health_check.check())
            tasks.append((name, task))
        
        # Wait for all checks to complete
        for name, task in tasks:
            try:
                result = await task
                check_results[name] = result
                log.debug("health_check.completed name=%s status=%s duration=%.2f",
                         name, result.status.value, result.duration)
            except Exception as e:
                log.error("health_check.failed name=%s error=%s", name, str(e))
                check_results[name] = HealthCheckResult(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Health check failed: {str(e)}"
                )
        
        # Determine overall status
        overall_status = HealthStatus.HEALTHY
        for result in check_results.values():
            if result.status == HealthStatus.UNHEALTHY:
                overall_status = HealthStatus.UNHEALTHY
                break
            elif result.status == HealthStatus.DEGRADED and overall_status == HealthStatus.HEALTHY:
                overall_status = HealthStatus.DEGRADED
        
        # Create system health
        system_health = SystemHealth(
            overall_status=overall_status,
            checks=check_results,
            metadata={
                "total_checks": len(check_results),
                "healthy_checks": sum(1 for r in check_results.values() if r.status == HealthStatus.HEALTHY),
                "degraded_checks": sum(1 for r in check_results.values() if r.status == HealthStatus.DEGRADED),
                "unhealthy_checks": sum(1 for r in check_results.values() if r.status == HealthStatus.UNHEALTHY)
            }
        )
        
        self.last_health_check = system_health
        
        log.info("health_check.completed overall_status=%s checks=%d duration=%.2f",
                overall_status.value, len(check_results), 
                sum(r.duration for r in check_results.values()))
        
        return system_health
    
    async def get_health_status(self) -> SystemHealth:
        """Get current health status, using cached result if available."""
        if (self.last_health_check and 
            (datetime.now() - self.last_health_check.timestamp).total_seconds() < self.check_interval):
            return self.last_health_check
        
        return await self.run_health_checks()
    
    async def start_health_monitor(self):
        """Start continuous health monitoring."""
        log.info("health_monitor.started interval=%.1f", self.check_interval)
        
        while True:
            try:
                await self.run_health_checks()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                log.info("health_monitor.stopped")
                break
            except Exception as e:
                log.error("health_monitor.error error=%s", str(e))
                await asyncio.sleep(self.check_interval)
    
    def get_health_summary(self) -> Dict[str, Any]:
        """Get a summary of health status."""
        if not self.last_health_check:
            return {"status": "unknown", "message": "No health check data available"}
        
        return {
            "overall_status": self.last_health_check.overall_status.value,
            "timestamp": self.last_health_check.timestamp.isoformat(),
            "checks": {
                name: {
                    "status": result.status.value,
                    "message": result.message,
                    "duration": round(result.duration, 2)
                }
                for name, result in self.last_health_check.checks.items()
            },
            "metadata": self.last_health_check.metadata
        }
    
    async def __aenter__(self):
        """Start health monitoring when used as context manager."""
        self._monitor_task = asyncio.create_task(self.start_health_monitor())
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Stop health monitoring when exiting context."""
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
