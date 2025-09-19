awesome job with your meticulous review and validation of the core files for a custom MCP server build! please keep up the good work! now, please help me to meticulously plan and then review and validate line by line the remaining core files below.

```python
# File: circuit_breaker.py
"""
Circuit breaker implementation for MCP tool resilience.
Production-ready implementation with proper exception handling and edge cases.
"""
import asyncio
import time
import logging
import inspect
from enum import Enum
from dataclasses import dataclass
from typing import Callable, Any, Optional, Tuple

log = logging.getLogger(__name__)


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"         # Normal operation, requests pass through
    OPEN = "open"             # Circuit is open, requests fail fast
    HALF_OPEN = "half_open"   # Testing if service has recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    expected_exception: Tuple[type, ...] = (Exception,)
    timeout_exception: Tuple[type, ...] = (asyncio.TimeoutError,)


class CircuitBreaker:
    """
    Circuit breaker implementation for protecting against cascading failures.

    Usage:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0, expected_exception=(MyError,))
        result = await cb.call(some_async_or_sync_callable, *args, **kwargs)

    Notes:
     - call() accepts both sync and async callables; it will await returned awaitables.
     - force_open and force_close are async; convenience sync wrappers are provided
       (force_open_nowait, force_close_nowait) if calling from synchronous code.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: Tuple[type, ...] = (Exception,),
        name: str = "tool",
    ):
        self.failure_threshold = max(1, int(failure_threshold))
        self.recovery_timeout = max(1.0, float(recovery_timeout))
        # expected_exception should be a tuple of exception classes
        if not isinstance(expected_exception, tuple):
            expected_exception = (expected_exception,)
        self.expected_exception = expected_exception
        self.name = name

        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._success_count = 0
        self._lock = asyncio.Lock()

        log.info(
            "circuit_breaker.created name=%s threshold=%d timeout=%.1f",
            self.name,
            self.failure_threshold,
            self.recovery_timeout,
        )

    @property
    def state(self) -> CircuitBreakerState:
        """Get current circuit breaker state."""
        return self._state

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.

        Accepts either an async function or a sync function. If the callable returns
        an awaitable, it will be awaited.
        """
        # First, quick state check under lock
        async with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                if self._should_attempt_reset():
                    self._state = CircuitBreakerState.HALF_OPEN
                    self._success_count = 0
                    log.info("circuit_breaker.half_open name=%s", self.name)
                else:
                    raise CircuitBreakerOpenError(f"Circuit breaker is open for {self.name}")

        # Execute the callable (support sync or async)
        try:
            result = func(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result

            # Success path
            await self._on_success()
            return result

        except Exception as e:
            # Treat expected exceptions as failures that count toward threshold
            if isinstance(e, self.expected_exception):
                await self._on_failure()
                # re-raise the exception for caller handling
                raise
            else:
                # Unexpected exceptions are not treated as failures for the circuit-breaker count,
                # but should be logged and propagated.
                log.warning(
                    "circuit_breaker.unexpected_error name=%s exception=%s",
                    self.name,
                    repr(e),
                )
                raise

    def _should_attempt_reset(self) -> bool:
        """
        Check if circuit breaker should attempt reset.
        Don't attempt reset if we've never had a failure.
        """
        if self._last_failure_time <= 0:
            return False
        return (time.time() - self._last_failure_time) >= self.recovery_timeout

    async def _on_success(self):
        """Handle successful execution; adjusts state accordingly."""
        async with self._lock:
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._success_count += 1
                # Use 1 as the default success threshold for half-open
                if self._success_count >= 1:
                    self._state = CircuitBreakerState.CLOSED
                    self._failure_count = 0
                    self._last_failure_time = 0.0
                    log.info("circuit_breaker.closed name=%s", self.name)
            else:
                if self._failure_count > 0:
                    # Reset failure count on successful closed-state operation
                    self._failure_count = 0
                    log.debug("circuit_breaker.failure_count_reset name=%s", self.name)

    async def _on_failure(self):
        """Handle failed execution and potentially open the circuit."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if (
                self._state == CircuitBreakerState.CLOSED
                and self._failure_count >= self.failure_threshold
            ):
                self._state = CircuitBreakerState.OPEN
                log.warning(
                    "circuit_breaker.open name=%s failures=%d",
                    self.name,
                    self._failure_count,
                )
            elif self._state == CircuitBreakerState.HALF_OPEN:
                # On any failure in HALF_OPEN, go back to OPEN immediately
                self._state = CircuitBreakerState.OPEN
                log.warning("circuit_breaker.reopened name=%s", self.name)

    async def force_open(self):
        """Asynchronously force circuit breaker to open state."""
        async with self._lock:
            self._state = CircuitBreakerState.OPEN
            self._failure_count = self.failure_threshold
            self._last_failure_time = time.time()
            log.info("circuit_breaker.force_open name=%s", self.name)

    async def force_close(self):
        """Asynchronously force circuit breaker to closed state."""
        async with self._lock:
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = 0.0
            log.info("circuit_breaker.force_close name=%s", self.name)

    def force_open_nowait(self):
        """
        Convenience wrapper for synchronous contexts: schedule force_open.
        If no loop is running, will run force_open synchronously.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop: run synchronously
            asyncio.run(self.force_open())
        else:
            # Running loop: schedule the coroutine
            loop.create_task(self.force_open())

    def force_close_nowait(self):
        """Convenience wrapper for synchronous contexts: schedule force_close."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.force_close())
        else:
            loop.create_task(self.force_close())

    def get_stats(self) -> dict:
        """Get circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": self._last_failure_time,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "time_since_last_failure": time.time() - self._last_failure_time
            if self._last_failure_time > 0
            else 0,
        }


class CircuitBreakerContext:
    """Context manager for circuit breaker operations.
    Example:
        async with CircuitBreakerContext(cb):
            await do_work()
    """
    def __init__(self, circuit_breaker: CircuitBreaker):
        self.circuit_breaker = circuit_breaker
        self.start_time = None
        self.exception_occurred = False

    async def __aenter__(self):
        self.start_time = time.time()
        self.exception_occurred = False
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        execution_time = time.time() - self.start_time
        self.exception_occurred = exc_type is not None

        if self.exception_occurred:
            await self.circuit_breaker._on_failure()
        else:
            await self.circuit_breaker._on_success()

        return False  # Don't suppress exceptions
```

```python
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
from typing import Dict, List, Optional, Any, Callable, Awaitable, Union

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
    """Manager for health checks.
    Accepts either:
      - a dict-like config (legacy), or
      - an MCPConfig object with attributes like .health, .server, .metrics, etc.
    """
    
    def __init__(self, config: Optional[Union[dict, object]] = None):
        # Store raw config (may be a dict or MCPConfig object)
        self._raw_config = config or {}
        self.config = self._normalize_config(self._raw_config)
        
        self.health_checks: Dict[str, HealthCheck] = {}
        self.last_health_check: Optional[SystemHealth] = None
        self.check_interval = max(5.0, float(self.config.get('check_interval', 30.0)))  # Minimum 5 seconds
        self._monitor_task = None
        
        # Initialize default health checks
        self._initialize_default_checks()
    
    def _normalize_config(self, cfg: Union[dict, object]) -> dict:
        """
        Normalize config into a plain dict with commonly used values.
        Supports MCPConfig object (has attribute 'health') or a plain dict.
        """
        normalized = {}
        try:
            if cfg is None:
                return normalized
            # If it's a mapping/dict-like
            if isinstance(cfg, dict):
                normalized.update(cfg)
                # Pull nested health dict to top-level keys for backwards compatibility
                health = cfg.get('health', {})
                if isinstance(health, dict):
                    normalized['health'] = health
                    normalized['check_interval'] = health.get('check_interval', normalized.get('check_interval'))
                    normalized['health_cpu_threshold'] = health.get('cpu_threshold', normalized.get('health_cpu_threshold'))
                    normalized['health_memory_threshold'] = health.get('memory_threshold', normalized.get('health_memory_threshold'))
                    normalized['health_disk_threshold'] = health.get('disk_threshold', normalized.get('health_disk_threshold'))
                    normalized['health_dependencies'] = health.get('dependencies', normalized.get('health_dependencies', []))
                return normalized
            # Otherwise assume object with attributes (e.g., MCPConfig)
            # Try to read health.* values
            if hasattr(cfg, 'health'):
                h = getattr(cfg, 'health')
                normalized['health'] = {
                    'check_interval': getattr(h, 'check_interval', None),
                    'cpu_threshold': getattr(h, 'cpu_threshold', None),
                    'memory_threshold': getattr(h, 'memory_threshold', None),
                    'disk_threshold': getattr(h, 'disk_threshold', None),
                    'dependencies': getattr(h, 'dependencies', None),
                }
                normalized['check_interval'] = normalized['health']['check_interval']
                normalized['health_cpu_threshold'] = normalized['health']['cpu_threshold']
                normalized['health_memory_threshold'] = normalized['health']['memory_threshold']
                normalized['health_disk_threshold'] = normalized['health']['disk_threshold']
                normalized['health_dependencies'] = normalized['health']['dependencies'] or []
            # Allow top-level check_interval override
            if hasattr(cfg, 'get_value'):
                # try other getters for compatibility
                try:
                    normalized['check_interval'] = float(getattr(cfg, 'get_value')('health', 'check_interval', normalized.get('check_interval', 30.0)))
                except Exception:
                    pass
        except Exception as e:
            log.debug("health_config_normalize_failed error=%s", str(e))
        return normalized
    
    def _initialize_default_checks(self):
        """Initialize default health checks."""
        try:
            # System resources check - read thresholds from normalized config
            cpu_th = float(self.config.get('health_cpu_threshold', 80.0))
            mem_th = float(self.config.get('health_memory_threshold', 80.0))
            disk_th = float(self.config.get('health_disk_threshold', 80.0))
            self.add_health_check(
                SystemResourceHealthCheck(
                    cpu_threshold=cpu_th,
                    memory_threshold=mem_th,
                    disk_threshold=disk_th
                )
            )
            
            # Process health check
            self.add_health_check(ProcessHealthCheck())
            
            # Dependency health check
            health_deps = self.config.get('health_dependencies', []) or []
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
```

```python
# File: metrics.py
"""
Metrics collection system for MCP server.
Adjusted to avoid repeated registrations of identical Prometheus metrics.
Metrics objects are created once globally and reused by tool-specific wrappers.
"""
import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field

# Graceful Prometheus dependency handling
try:
    from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest
    from prometheus_client.core import CollectorRegistry
    PROMETHEUS_AVAILABLE = True
except Exception:
    PROMETHEUS_AVAILABLE = False

log = logging.getLogger(__name__)

# Module-level, single definitions of commonly used metric families to avoid duplicate registration.
if PROMETHEUS_AVAILABLE:
    try:
        GLOBAL_EXECUTION_COUNTER = Counter(
            'mcp_tool_execution_total',
            'Total tool executions',
            ['tool', 'status', 'error_type']
        )
        GLOBAL_EXECUTION_HISTOGRAM = Histogram(
            'mcp_tool_execution_seconds',
            'Tool execution time in seconds',
            ['tool']
        )
        GLOBAL_ACTIVE_GAUGE = Gauge(
            'mcp_tool_active',
            'Currently active tool executions',
            ['tool']
        )
        GLOBAL_ERROR_COUNTER = Counter(
            'mcp_tool_errors_total',
            'Total tool errors',
            ['tool', 'error_type']
        )
    except Exception as e:
        log.warning("prometheus.global_metric_initialization_failed error=%s", str(e))
        GLOBAL_EXECUTION_COUNTER = GLOBAL_EXECUTION_HISTOGRAM = GLOBAL_ACTIVE_GAUGE = GLOBAL_ERROR_COUNTER = None
else:
    GLOBAL_EXECUTION_COUNTER = GLOBAL_EXECUTION_HISTOGRAM = GLOBAL_ACTIVE_GAUGE = GLOBAL_ERROR_COUNTER = None

@dataclass
class ToolExecutionMetrics:
    tool_name: str
    execution_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0
    total_execution_time: float = 0.0
    min_execution_time: float = float('inf')
    max_execution_time: float = 0.0
    last_execution_time: Optional[datetime] = None

    def record_execution(self, success: bool, execution_time: float, timed_out: bool = False):
        execution_time = max(0.0, float(execution_time))
        self.execution_count += 1
        self.total_execution_time += execution_time
        if execution_time < self.min_execution_time:
            self.min_execution_time = execution_time
        if execution_time > self.max_execution_time:
            self.max_execution_time = execution_time
        self.last_execution_time = datetime.now()
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
        if timed_out:
            self.timeout_count += 1

    def get_stats(self) -> Dict[str, Any]:
        if self.execution_count == 0:
            return {
                "tool_name": self.tool_name,
                "execution_count": 0,
                "success_rate": 0.0,
                "average_execution_time": 0.0,
                "min_execution_time": 0.0,
                "max_execution_time": 0.0
            }
        avg_execution_time = self.total_execution_time / self.execution_count
        success_rate = (self.success_count / self.execution_count) * 100
        return {
            "tool_name": self.tool_name,
            "execution_count": self.execution_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "timeout_count": self.timeout_count,
            "success_rate": round(success_rate, 2),
            "average_execution_time": round(avg_execution_time, 4),
            "min_execution_time": round(self.min_execution_time, 4) if self.min_execution_time != float('inf') else 0.0,
            "max_execution_time": round(self.max_execution_time, 4),
            "last_execution_time": self.last_execution_time.isoformat() if self.last_execution_time else None
        }

class SystemMetrics:
    def __init__(self):
        self.start_time = datetime.now()
        self.request_count = 0
        self.error_count = 0
        self.active_connections = 0
        self._lock = None

    def increment_request_count(self):
        self.request_count += 1

    def increment_error_count(self):
        self.error_count += 1

    def increment_active_connections(self):
        self.active_connections += 1

    def decrement_active_connections(self):
        self.active_connections = max(0, self.active_connections - 1)

    def get_uptime(self) -> float:
        return (datetime.now() - self.start_time).total_seconds()

    def get_stats(self) -> Dict[str, Any]:
        uptime = self.get_uptime()
        error_rate = (self.error_count / self.request_count * 100) if self.request_count > 0 else 0
        return {
            "uptime_seconds": uptime,
            "request_count": self.request_count,
            "error_count": self.error_count,
            "error_rate": round(error_rate, 2),
            "active_connections": self.active_connections,
            "start_time": self.start_time.isoformat()
        }

class PrometheusMetrics:
    def __init__(self):
        if not PROMETHEUS_AVAILABLE:
            log.warning("prometheus.unavailable")
            self.registry = None
            return
        try:
            self.registry = CollectorRegistry()
            # The module-level globals hold main metric families to avoid duplicates.
            log.info("prometheus.metrics_initialized")
        except Exception as e:
            log.error("prometheus.initialization_failed error=%s", str(e))
            self.registry = None

    def get_metrics(self) -> Optional[str]:
        if not PROMETHEUS_AVAILABLE or not self.registry:
            return None
        try:
            return generate_latest(self.registry).decode('utf-8')
        except Exception as e:
            log.error("prometheus.generate_metrics_error error=%s", str(e))
            return None

class MetricsManager:
    def __init__(self):
        self.tool_metrics: Dict[str, ToolExecutionMetrics] = {}
        self.system_metrics = SystemMetrics()
        self.prometheus_metrics = PrometheusMetrics()
        self.start_time = datetime.now()

    def get_tool_metrics(self, tool_name: str) -> ToolExecutionMetrics:
        if tool_name not in self.tool_metrics:
            self.tool_metrics[tool_name] = ToolExecutionMetrics(tool_name)
        return self.tool_metrics[tool_name]

    def record_tool_execution(self, tool_name: str, success: bool, execution_time: float,
                             timed_out: bool = False, error_type: str = None):
        tool_metrics = self.get_tool_metrics(tool_name)
        tool_metrics.record_execution(success, execution_time, timed_out)
        # Prometheus: use module-level global metrics if available
        if PROMETHEUS_AVAILABLE and GLOBAL_EXECUTION_COUNTER is not None:
            try:
                status = 'success' if success else 'failure'
                GLOBAL_EXECUTION_COUNTER.labels(tool=tool_name, status=status, error_type=error_type or 'none').inc()
                if GLOBAL_EXECUTION_HISTOGRAM:
                    GLOBAL_EXECUTION_HISTOGRAM.labels(tool=tool_name).observe(float(execution_time))
                if not success and GLOBAL_ERROR_COUNTER:
                    GLOBAL_ERROR_COUNTER.labels(tool=tool_name, error_type=error_type or 'unknown').inc()
            except Exception as e:
                log.warning("prometheus.tool_execution_error error=%s", str(e))
        self.system_metrics.increment_request_count()
        if not success:
            self.system_metrics.increment_error_count()

    def get_all_stats(self) -> Dict[str, Any]:
        return {
            "system": self.system_metrics.get_stats(),
            "tools": {name: metrics.get_stats() for name, metrics in self.tool_metrics.items()},
            "prometheus_available": PROMETHEUS_AVAILABLE,
            "collection_start_time": self.start_time.isoformat()
        }

    def get_prometheus_metrics(self) -> Optional[str]:
        return self.prometheus_metrics.get_metrics()
```
