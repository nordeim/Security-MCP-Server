"""
Health monitoring system for MCP server.
Production-ready implementation with priority-based checks and robust error handling.
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Awaitable, Union
from collections import deque

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
        self.timeout = max(1.0, timeout)
    
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
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            
            try:
                disk = psutil.disk_usage('/')
                disk_percent = disk.percent
            except Exception as disk_error:
                log.warning("health_check.disk_usage_failed error=%s", str(disk_error))
                disk_percent = 0.0
            
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
            
            if not process.is_running():
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message="Process is not running",
                    metadata={"pid": process.pid}
                )
            
            create_time = datetime.fromtimestamp(process.create_time())
            age = datetime.now() - create_time
            
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            
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


class CustomHealthCheck(HealthCheck):
    """Custom health check with user-provided function."""
    
    def __init__(self, name: str, check_func: Callable[[], Awaitable[HealthStatus]], 
                 timeout: float = 10.0):
        super().__init__(name, timeout)
        self.check_func = check_func
    
    async def _execute_check(self) -> HealthCheckResult:
        """Execute custom health check."""
        try:
            status = await self.check_func()
            message = f"{self.name} check {'passed' if status == HealthStatus.HEALTHY else 'failed'}"
            return HealthCheckResult(
                name=self.name,
                status=status,
                message=message
            )
        except Exception as e:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Custom check failed: {str(e)}"
            )


class HealthCheckManager:
    """Manager for health checks with priority support."""
    
    def __init__(self, config: Optional[Union[dict, object]] = None):
        self._raw_config = config
        self.config = self._normalize_config_safe(self._raw_config)
        
        self.health_checks: Dict[str, HealthCheck] = {}
        self.check_priorities: Dict[str, int] = {}
        
        self.last_health_check: Optional[SystemHealth] = None
        self.check_interval = max(5.0, float(self.config.get('check_interval', 30.0)))
        
        self._monitor_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        
        self.check_history = deque(maxlen=100)
        
        self._initialize_default_checks()
    
    def _normalize_config_safe(self, cfg: Union[dict, object]) -> dict:
        """Safer config normalization with better error handling."""
        defaults = {
            'check_interval': 30.0,
            'health_cpu_threshold': 80.0,
            'health_memory_threshold': 80.0,
            'health_disk_threshold': 80.0,
            'health_dependencies': [],
            'health_timeout': 10.0,
        }
        
        if cfg is None:
            return defaults
        
        normalized = defaults.copy()
        
        try:
            if isinstance(cfg, dict):
                for key in defaults:
                    if key in cfg:
                        normalized[key] = cfg[key]
                
                if 'health' in cfg and isinstance(cfg['health'], dict):
                    health = cfg['health']
                    normalized.update({
                        'check_interval': health.get('check_interval', normalized['check_interval']),
                        'health_cpu_threshold': health.get('cpu_threshold', normalized['health_cpu_threshold']),
                        'health_memory_threshold': health.get('memory_threshold', normalized['health_memory_threshold']),
                        'health_disk_threshold': health.get('disk_threshold', normalized['health_disk_threshold']),
                        'health_dependencies': health.get('dependencies', normalized['health_dependencies']),
                        'health_timeout': health.get('timeout', normalized['health_timeout']),
                    })
            
            elif hasattr(cfg, 'health'):
                health = getattr(cfg, 'health')
                if health:
                    for attr, key in [
                        ('check_interval', 'check_interval'),
                        ('cpu_threshold', 'health_cpu_threshold'),
                        ('memory_threshold', 'health_memory_threshold'),
                        ('disk_threshold', 'health_disk_threshold'),
                        ('dependencies', 'health_dependencies'),
                        ('timeout', 'health_timeout'),
                    ]:
                        if hasattr(health, attr):
                            value = getattr(health, attr, None)
                            if value is not None:
                                normalized[key] = value
            
            normalized['check_interval'] = max(5.0, float(normalized['check_interval']))
            normalized['health_cpu_threshold'] = max(0.0, min(100.0, float(normalized['health_cpu_threshold'])))
            normalized['health_memory_threshold'] = max(0.0, min(100.0, float(normalized['health_memory_threshold'])))
            normalized['health_disk_threshold'] = max(0.0, min(100.0, float(normalized['health_disk_threshold'])))
            normalized['health_timeout'] = max(1.0, float(normalized.get('health_timeout', 10.0)))
            
            deps = normalized.get('health_dependencies', [])
            if not isinstance(deps, list):
                normalized['health_dependencies'] = []
            
        except Exception as e:
            log.error("config.normalization_failed error=%s using_defaults", str(e))
            return defaults
        
        return normalized
    
    def _initialize_default_checks(self):
        """Initialize default health checks."""
        try:
            cpu_th = float(self.config.get('health_cpu_threshold', 80.0))
            mem_th = float(self.config.get('health_memory_threshold', 80.0))
            disk_th = float(self.config.get('health_disk_threshold', 80.0))
            
            self.add_health_check(
                SystemResourceHealthCheck(
                    cpu_threshold=cpu_th,
                    memory_threshold=mem_th,
                    disk_threshold=disk_th
                ),
                priority=0
            )
            
            self.add_health_check(ProcessHealthCheck(), priority=1)
            
            health_deps = self.config.get('health_dependencies', []) or []
            if health_deps:
                self.add_health_check(DependencyHealthCheck(health_deps), priority=2)
            
            log.info("health_check_manager.initialized checks=%d interval=%.1f", 
                    len(self.health_checks), self.check_interval)
        
        except Exception as e:
            log.error("health_check_manager.initialization_failed error=%s", str(e))
    
    def add_health_check(self, health_check: HealthCheck, priority: int = 2):
        """Add a health check with priority level (0=critical, 1=important, 2=informational)."""
        if not health_check or not health_check.name:
            log.warning("health_check.invalid_check skipped")
            return
        
        self.health_checks[health_check.name] = health_check
        self.check_priorities[health_check.name] = max(0, min(2, priority))
        
        log.info("health_check.added name=%s priority=%d", health_check.name, priority)
    
    def remove_health_check(self, name: str):
        """Remove a health check."""
        if name in self.health_checks:
            del self.health_checks[name]
            if name in self.check_priorities:
                del self.check_priorities[name]
            log.info("health_check.removed name=%s", name)
    
    def register_check(self, name: str, check_func: Callable[[], Awaitable[HealthStatus]], 
                      priority: int = 2, timeout: float = 10.0):
        """Register a custom health check function."""
        health_check = CustomHealthCheck(name, check_func, timeout)
        self.add_health_check(health_check, priority)
    
    async def run_health_checks(self) -> SystemHealth:
        """Run health checks with proper timeout and error handling."""
        if not self.health_checks:
            return SystemHealth(
                overall_status=HealthStatus.HEALTHY,
                checks={},
                metadata={"message": "No health checks configured"}
            )
        
        check_results = {}
        tasks = []
        
        timeout = self.config.get('health_timeout', 10.0)
        
        for name, health_check in self.health_checks.items():
            if hasattr(health_check, 'timeout'):
                health_check.timeout = min(health_check.timeout, timeout)
            
            task = asyncio.create_task(
                self._run_single_check(name, health_check),
                name=f"health_check_{name}"
            )
            tasks.append((name, task))
        
        try:
            done, pending = await asyncio.wait(
                [task for _, task in tasks],
                timeout=timeout + 2.0,
                return_when=asyncio.ALL_COMPLETED
            )
            
            for task in pending:
                task.cancel()
                log.warning("health_check.timeout task=%s", task.get_name())
            
        except Exception as e:
            log.error("health_check.wait_failed error=%s", str(e))
        
        for name, task in tasks:
            try:
                if task.done() and not task.cancelled():
                    result = task.result()
                else:
                    result = HealthCheckResult(
                        name=name,
                        status=HealthStatus.UNHEALTHY,
                        message="Health check timed out or was cancelled"
                    )
                check_results[name] = result
            except Exception as e:
                log.error("health_check.result_failed name=%s error=%s", name, str(e))
                check_results[name] = HealthCheckResult(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Health check failed: {str(e)}"
                )
        
        overall_status = self._calculate_overall_status(check_results)
        
        system_health = SystemHealth(
            overall_status=overall_status,
            checks=check_results,
            metadata=self._generate_health_metadata(check_results)
        )
        
        self.check_history.append({
            "timestamp": system_health.timestamp,
            "status": overall_status,
            "check_count": len(check_results)
        })
        
        self.last_health_check = system_health
        
        log.info(
            "health_check.completed overall=%s checks=%d duration=%.2f",
            overall_status.value,
            len(check_results),
            sum(r.duration for r in check_results.values())
        )
        
        return system_health
    
    async def _run_single_check(self, name: str, health_check: HealthCheck) -> HealthCheckResult:
        """Run a single health check with error handling."""
        try:
            return await health_check.check()
        except Exception as e:
            log.error("health_check.execution_failed name=%s error=%s", name, str(e))
            return HealthCheckResult(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=f"Check failed: {str(e)}"
            )
    
    def _calculate_overall_status(self, check_results: Dict[str, HealthCheckResult]) -> HealthStatus:
        """Calculate overall status with priority weighting."""
        critical_checks = [
            result for name, result in check_results.items()
            if self.check_priorities.get(name, 2) == 0
        ]
        
        if any(r.status == HealthStatus.UNHEALTHY for r in critical_checks):
            return HealthStatus.UNHEALTHY
        
        important_checks = [
            result for name, result in check_results.items()
            if self.check_priorities.get(name, 2) == 1
        ]
        
        if any(r.status == HealthStatus.UNHEALTHY for r in important_checks):
            return HealthStatus.DEGRADED
        
        if any(r.status == HealthStatus.DEGRADED for r in check_results.values()):
            return HealthStatus.DEGRADED
        
        info_checks = [
            result for name, result in check_results.items()
            if self.check_priorities.get(name, 2) == 2
        ]
        
        if info_checks and all(r.status == HealthStatus.UNHEALTHY for r in info_checks):
            return HealthStatus.DEGRADED
        
        return HealthStatus.HEALTHY
    
    def _generate_health_metadata(self, check_results: Dict[str, HealthCheckResult]) -> Dict[str, Any]:
        """Generate comprehensive health metadata."""
        return {
            "total_checks": len(check_results),
            "healthy_checks": sum(1 for r in check_results.values() if r.status == HealthStatus.HEALTHY),
            "degraded_checks": sum(1 for r in check_results.values() if r.status == HealthStatus.DEGRADED),
            "unhealthy_checks": sum(1 for r in check_results.values() if r.status == HealthStatus.UNHEALTHY),
            "critical_failures": sum(
                1 for name, r in check_results.items()
                if self.check_priorities.get(name, 2) == 0 and r.status == HealthStatus.UNHEALTHY
            ),
            "average_duration": (
                sum(r.duration for r in check_results.values()) / len(check_results)
                if check_results else 0.0
            ),
            "check_priorities": self.check_priorities,
        }
    
    async def start_monitoring(self):
        """Start health monitoring with proper lifecycle management."""
        if self._monitor_task and not self._monitor_task.done():
            log.warning("health_monitor.already_running")
            return
        
        self._shutdown_event.clear()
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(),
            name="health_monitor"
        )
        log.info("health_monitor.started interval=%.1f", self.check_interval)
    
    async def _monitor_loop(self):
        """Health monitoring loop with graceful shutdown."""
        try:
            while not self._shutdown_event.is_set():
                try:
                    await self.run_health_checks()
                except Exception as e:
                    log.error("health_monitor.check_failed error=%s", str(e))
                
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self.check_interval
                    )
                except asyncio.TimeoutError:
                    continue
                
        except asyncio.CancelledError:
            log.info("health_monitor.cancelled")
            raise
        finally:
            log.info("health_monitor.stopped")
    
    async def stop_monitoring(self):
        """Stop health monitoring gracefully."""
        self._shutdown_event.set()
        
        if self._monitor_task and not self._monitor_task.done():
            try:
                await asyncio.wait_for(self._monitor_task, timeout=5.0)
            except asyncio.TimeoutError:
                log.warning("health_monitor.stop_timeout")
                self._monitor_task.cancel()
                try:
                    await self._monitor_task
                except asyncio.CancelledError:
                    pass
    
    async def get_overall_health(self) -> HealthStatus:
        """Get current overall health status."""
        if self.last_health_check:
            return self.last_health_check.overall_status
        
        system_health = await self.run_health_checks()
        return system_health.overall_status
    
    async def get_all_check_results(self) -> Dict[str, Any]:
        """Get all health check results."""
        if not self.last_health_check:
            await self.run_health_checks()
        
        if self.last_health_check:
            return {
                name: {
                    "status": result.status.value,
                    "message": result.message,
                    "duration": result.duration,
                    "metadata": result.metadata
                }
                for name, result in self.last_health_check.checks.items()
            }
        return {}
    
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
                    "duration": round(result.duration, 2),
                    "priority": self.check_priorities.get(name, 2)
                }
                for name, result in self.last_health_check.checks.items()
            },
            "metadata": self.last_health_check.metadata,
            "history": list(self.check_history)[-10:]
        }
    
    async def __aenter__(self):
        """Start health monitoring when used as context manager."""
        await self.start_monitoring()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Stop health monitoring when exiting context."""
        await self.stop_monitoring()
