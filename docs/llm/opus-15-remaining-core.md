## Meticulous Planning & Review of Remaining Core Files

I'll conduct a comprehensive line-by-line review of these three critical monitoring and resilience components, identifying issues and providing production-ready solutions.

## **1. circuit_breaker.py - Circuit Breaker Implementation**

### Critical Issues Found:

1. **Race Condition in State Check** (Lines 80-87)
   - State check and modification aren't atomic
   - Multiple concurrent calls could pass the OPEN check before state changes to HALF_OPEN

2. **Missing Metrics Integration**
   - No telemetry for circuit breaker state changes
   - Difficult to monitor circuit breaker behavior in production

3. **Incomplete Error Recovery**
   - No exponential backoff or jitter for recovery attempts
   - Fixed recovery timeout doesn't adapt to failure patterns

### Enhanced Implementation:

```python
# circuit_breaker.py - Enhanced version
"""
Production-ready circuit breaker with metrics, adaptive recovery, and proper concurrency handling.
"""
import asyncio
import time
import logging
import inspect
import random
from enum import Enum
from dataclasses import dataclass, field
from typing import Callable, Any, Optional, Tuple, Dict
from datetime import datetime, timedelta
from collections import deque

log = logging.getLogger(__name__)

# Metrics integration
try:
    from prometheus_client import Counter, Gauge, Histogram
    METRICS_AVAILABLE = True
    
    # Global metrics for circuit breakers
    CB_STATE_GAUGE = Gauge(
        'circuit_breaker_state',
        'Circuit breaker state (0=closed, 1=open, 2=half_open)',
        ['name']
    )
    CB_CALLS_COUNTER = Counter(
        'circuit_breaker_calls_total',
        'Total circuit breaker calls',
        ['name', 'result']  # result: success, failure, rejected
    )
    CB_STATE_TRANSITIONS = Counter(
        'circuit_breaker_transitions_total',
        'Circuit breaker state transitions',
        ['name', 'from_state', 'to_state']
    )
except ImportError:
    METRICS_AVAILABLE = False
    CB_STATE_GAUGE = CB_CALLS_COUNTER = CB_STATE_TRANSITIONS = None

class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after

class CircuitBreakerState(Enum):
    """Circuit breaker states with numeric values for metrics."""
    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2

@dataclass
class CircuitBreakerStats:
    """Statistics for circuit breaker monitoring."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    state_changes: int = 0
    last_state_change: Optional[datetime] = None
    failure_reasons: Dict[str, int] = field(default_factory=dict)

class AdaptiveCircuitBreaker:
    """
    Enhanced circuit breaker with adaptive recovery and proper concurrency handling.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: Tuple[type, ...] = (Exception,),
        name: str = "tool",
        success_threshold: int = 2,  # Successes needed in HALF_OPEN to close
        timeout_multiplier: float = 1.5,  # Multiply timeout on repeated failures
        max_timeout: float = 300.0,  # Maximum recovery timeout
        enable_jitter: bool = True,  # Add random jitter to recovery
    ):
        self.failure_threshold = max(1, int(failure_threshold))
        self.initial_recovery_timeout = max(1.0, float(recovery_timeout))
        self.current_recovery_timeout = self.initial_recovery_timeout
        self.max_timeout = max(self.initial_recovery_timeout, float(max_timeout))
        self.timeout_multiplier = max(1.0, float(timeout_multiplier))
        self.success_threshold = max(1, int(success_threshold))
        self.enable_jitter = enable_jitter
        
        if not isinstance(expected_exception, tuple):
            expected_exception = (expected_exception,)
        self.expected_exception = expected_exception
        self.name = name
        
        # State management with proper locking
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._consecutive_failures = 0
        self._lock = asyncio.Lock()
        
        # Statistics
        self.stats = CircuitBreakerStats()
        
        # Recent error tracking for analysis
        self._recent_errors = deque(maxlen=10)
        
        # Half-open call limiting
        self._half_open_calls = 0
        self._max_half_open_calls = 1  # Only allow one test call initially
        
        # Initialize metrics
        self._update_metrics()
        
        log.info(
            "adaptive_circuit_breaker.created name=%s threshold=%d timeout=%.1f success_threshold=%d",
            self.name, self.failure_threshold, self.initial_recovery_timeout, self.success_threshold
        )
    
    @property
    def state(self) -> CircuitBreakerState:
        """Get current state (thread-safe)."""
        return self._state
    
    def _update_metrics(self):
        """Update Prometheus metrics."""
        if METRICS_AVAILABLE and CB_STATE_GAUGE:
            try:
                CB_STATE_GAUGE.labels(name=self.name).set(self._state.value)
            except Exception as e:
                log.debug("metrics.update_failed error=%s", str(e))
    
    def _record_call_metric(self, result: str):
        """Record call metrics."""
        if METRICS_AVAILABLE and CB_CALLS_COUNTER:
            try:
                CB_CALLS_COUNTER.labels(name=self.name, result=result).inc()
            except Exception as e:
                log.debug("metrics.record_failed error=%s", str(e))
    
    def _record_transition_metric(self, from_state: CircuitBreakerState, to_state: CircuitBreakerState):
        """Record state transition metrics."""
        if METRICS_AVAILABLE and CB_STATE_TRANSITIONS:
            try:
                CB_STATE_TRANSITIONS.labels(
                    name=self.name,
                    from_state=from_state.name,
                    to_state=to_state.name
                ).inc()
            except Exception as e:
                log.debug("metrics.transition_failed error=%s", str(e))
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.
        Enhanced with better concurrency control and metrics.
        """
        # Check and potentially transition state
        await self._check_state()
        
        # Fast path for open circuit
        if self._state == CircuitBreakerState.OPEN:
            retry_after = self._get_retry_after()
            self.stats.rejected_calls += 1
            self._record_call_metric("rejected")
            raise CircuitBreakerOpenError(
                f"Circuit breaker is open for {self.name}",
                retry_after=retry_after
            )
        
        # Handle HALF_OPEN state with limited concurrent calls
        if self._state == CircuitBreakerState.HALF_OPEN:
            async with self._lock:
                if self._half_open_calls >= self._max_half_open_calls:
                    self.stats.rejected_calls += 1
                    self._record_call_metric("rejected")
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker is testing recovery for {self.name}",
                        retry_after=5.0  # Check again soon
                    )
                self._half_open_calls += 1
        
        # Execute the function
        try:
            self.stats.total_calls += 1
            result = func(*args, **kwargs)
            
            # Handle async functions
            if inspect.isawaitable(result):
                result = await result
            
            # Success path
            await self._on_success()
            self.stats.successful_calls += 1
            self.stats.last_success_time = time.time()
            self._record_call_metric("success")
            
            return result
            
        except Exception as e:
            # Handle failures
            self.stats.failed_calls += 1
            self.stats.last_failure_time = time.time()
            
            # Track error reasons
            error_type = type(e).__name__
            self.stats.failure_reasons[error_type] = self.stats.failure_reasons.get(error_type, 0) + 1
            
            # Store recent errors for debugging
            self._recent_errors.append({
                "timestamp": datetime.now(),
                "error": str(e),
                "type": error_type
            })
            
            if isinstance(e, self.expected_exception):
                await self._on_failure()
                self._record_call_metric("failure")
            else:
                log.warning(
                    "circuit_breaker.unexpected_error name=%s error=%s",
                    self.name, repr(e)
                )
                self._record_call_metric("unexpected_failure")
            
            raise
        
        finally:
            # Clean up HALF_OPEN call counter
            if self._state == CircuitBreakerState.HALF_OPEN:
                async with self._lock:
                    self._half_open_calls = max(0, self._half_open_calls - 1)
    
    async def _check_state(self):
        """Check and potentially transition state."""
        async with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                if self._should_attempt_reset():
                    self._transition_to_half_open()
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed for recovery attempt."""
        if self._last_failure_time <= 0:
            return False
        
        time_since_failure = time.time() - self._last_failure_time
        recovery_time = self.current_recovery_timeout
        
        # Add jitter to prevent thundering herd
        if self.enable_jitter:
            jitter = random.uniform(-recovery_time * 0.1, recovery_time * 0.1)
            recovery_time += jitter
        
        return time_since_failure >= recovery_time
    
    def _get_retry_after(self) -> float:
        """Calculate when retry should be attempted."""
        if self._last_failure_time <= 0:
            return self.current_recovery_timeout
        
        time_since_failure = time.time() - self._last_failure_time
        remaining = max(0, self.current_recovery_timeout - time_since_failure)
        
        if self.enable_jitter:
            remaining += random.uniform(0, min(5.0, remaining * 0.1))
        
        return remaining
    
    def _transition_to_half_open(self):
        """Transition to HALF_OPEN state."""
        old_state = self._state
        self._state = CircuitBreakerState.HALF_OPEN
        self._success_count = 0
        self._half_open_calls = 0
        self.stats.state_changes += 1
        self.stats.last_state_change = datetime.now()
        
        self._update_metrics()
        self._record_transition_metric(old_state, self._state)
        
        log.info(
            "circuit_breaker.half_open name=%s after=%.1fs",
            self.name, self.current_recovery_timeout
        )
    
    async def _on_success(self):
        """Handle successful execution."""
        async with self._lock:
            self.stats.consecutive_successes += 1
            self.stats.consecutive_failures = 0
            
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._success_count += 1
                
                if self._success_count >= self.success_threshold:
                    # Transition to CLOSED
                    old_state = self._state
                    self._state = CircuitBreakerState.CLOSED
                    self._failure_count = 0
                    self._consecutive_failures = 0
                    
                    # Reset recovery timeout after successful recovery
                    self.current_recovery_timeout = self.initial_recovery_timeout
                    
                    self.stats.state_changes += 1
                    self.stats.last_state_change = datetime.now()
                    
                    self._update_metrics()
                    self._record_transition_metric(old_state, self._state)
                    
                    log.info(
                        "circuit_breaker.closed name=%s successes=%d",
                        self.name, self._success_count
                    )
            elif self._state == CircuitBreakerState.CLOSED:
                # Reset failure count on success in closed state
                if self._failure_count > 0:
                    self._failure_count = 0
                    log.debug("circuit_breaker.failure_count_reset name=%s", self.name)
    
    async def _on_failure(self):
        """Handle failed execution with adaptive timeout."""
        async with self._lock:
            self._failure_count += 1
            self._consecutive_failures += 1
            self.stats.consecutive_failures = self._consecutive_failures
            self.stats.consecutive_successes = 0
            self._last_failure_time = time.time()
            
            if self._state == CircuitBreakerState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    # Transition to OPEN
                    old_state = self._state
                    self._state = CircuitBreakerState.OPEN
                    
                    # Apply adaptive timeout with backoff
                    if self._consecutive_failures > self.failure_threshold:
                        self.current_recovery_timeout = min(
                            self.current_recovery_timeout * self.timeout_multiplier,
                            self.max_timeout
                        )
                    
                    self.stats.state_changes += 1
                    self.stats.last_state_change = datetime.now()
                    
                    self._update_metrics()
                    self._record_transition_metric(old_state, self._state)
                    
                    log.warning(
                        "circuit_breaker.open name=%s failures=%d timeout=%.1fs",
                        self.name, self._failure_count, self.current_recovery_timeout
                    )
            
            elif self._state == CircuitBreakerState.HALF_OPEN:
                # Any failure in HALF_OPEN returns to OPEN
                old_state = self._state
                self._state = CircuitBreakerState.OPEN
                
                # Increase timeout after failed recovery attempt
                self.current_recovery_timeout = min(
                    self.current_recovery_timeout * self.timeout_multiplier,
                    self.max_timeout
                )
                
                self.stats.state_changes += 1
                self.stats.last_state_change = datetime.now()
                
                self._update_metrics()
                self._record_transition_metric(old_state, self._state)
                
                log.warning(
                    "circuit_breaker.reopened name=%s new_timeout=%.1fs",
                    self.name, self.current_recovery_timeout
                )
    
    async def force_open(self):
        """Force circuit breaker to open state."""
        async with self._lock:
            old_state = self._state
            self._state = CircuitBreakerState.OPEN
            self._failure_count = self.failure_threshold
            self._last_failure_time = time.time()
            
            if old_state != self._state:
                self.stats.state_changes += 1
                self.stats.last_state_change = datetime.now()
                self._update_metrics()
                self._record_transition_metric(old_state, self._state)
            
            log.info("circuit_breaker.force_open name=%s", self.name)
    
    async def force_close(self):
        """Force circuit breaker to closed state."""
        async with self._lock:
            old_state = self._state
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._consecutive_failures = 0
            self.current_recovery_timeout = self.initial_recovery_timeout
            
            if old_state != self._state:
                self.stats.state_changes += 1
                self.stats.last_state_change = datetime.now()
                self._update_metrics()
                self._record_transition_metric(old_state, self._state)
            
            log.info("circuit_breaker.force_close name=%s", self.name)
    
    def get_stats(self) -> dict:
        """Get comprehensive circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self._state.name,
            "stats": {
                "total_calls": self.stats.total_calls,
                "successful_calls": self.stats.successful_calls,
                "failed_calls": self.stats.failed_calls,
                "rejected_calls": self.stats.rejected_calls,
                "success_rate": (
                    (self.stats.successful_calls / self.stats.total_calls * 100)
                    if self.stats.total_calls > 0 else 0.0
                ),
                "consecutive_failures": self.stats.consecutive_failures,
                "consecutive_successes": self.stats.consecutive_successes,
                "state_changes": self.stats.state_changes,
                "failure_reasons": self.stats.failure_reasons,
            },
            "config": {
                "failure_threshold": self.failure_threshold,
                "current_timeout": self.current_recovery_timeout,
                "initial_timeout": self.initial_recovery_timeout,
                "max_timeout": self.max_timeout,
                "success_threshold": self.success_threshold,
            },
            "timing": {
                "last_failure": self.stats.last_failure_time,
                "last_success": self.stats.last_success_time,
                "last_state_change": (
                    self.stats.last_state_change.isoformat()
                    if self.stats.last_state_change else None
                ),
                "retry_after": self._get_retry_after() if self._state == CircuitBreakerState.OPEN else None,
            },
            "recent_errors": list(self._recent_errors),
        }

# Maintain backward compatibility
CircuitBreaker = AdaptiveCircuitBreaker
```

## **2. health.py - Health Monitoring System**

### Critical Issues Found:

1. **Config Normalization Complexity** (Lines 249-295)
   - Complex branching logic that's hard to test
   - Potential for silent failures in config parsing

2. **Missing Health Check Aggregation**
   - No weighted health checks
   - No priority levels for critical vs. non-critical checks

3. **Task Lifecycle Management**
   - Monitor task not properly cleaned up in all cases

### Enhanced Implementation:

```python
# health.py - Critical sections enhanced

class HealthCheckManager:
    """Enhanced health check manager with proper lifecycle and priority support."""
    
    def __init__(self, config: Optional[Union[dict, object]] = None):
        self._raw_config = config
        self.config = self._normalize_config_safe(self._raw_config)
        
        # Health checks with priority levels
        self.health_checks: Dict[str, HealthCheck] = {}
        self.check_priorities: Dict[str, int] = {}  # 0=critical, 1=important, 2=informational
        
        self.last_health_check: Optional[SystemHealth] = None
        self.check_interval = max(5.0, float(self.config.get('check_interval', 30.0)))
        
        # Task management
        self._monitor_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        
        # Statistics
        self.check_history = deque(maxlen=100)  # Keep last 100 check results
        
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
            # Handle dict-like configs
            if isinstance(cfg, dict):
                # Direct values
                for key in defaults:
                    if key in cfg:
                        normalized[key] = cfg[key]
                
                # Nested health section
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
            
            # Handle object configs (MCPConfig)
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
            
            # Type validation and constraints
            normalized['check_interval'] = max(5.0, float(normalized['check_interval']))
            normalized['health_cpu_threshold'] = max(0.0, min(100.0, float(normalized['health_cpu_threshold'])))
            normalized['health_memory_threshold'] = max(0.0, min(100.0, float(normalized['health_memory_threshold'])))
            normalized['health_disk_threshold'] = max(0.0, min(100.0, float(normalized['health_disk_threshold'])))
            normalized['health_timeout'] = max(1.0, float(normalized.get('health_timeout', 10.0)))
            
            # Ensure dependencies is a list
            deps = normalized.get('health_dependencies', [])
            if not isinstance(deps, list):
                normalized['health_dependencies'] = []
            
        except Exception as e:
            log.error("config.normalization_failed error=%s using_defaults", str(e))
            return defaults
        
        return normalized
    
    def add_health_check(self, health_check: HealthCheck, priority: int = 2):
        """Add a health check with priority level."""
        if not health_check or not health_check.name:
            log.warning("health_check.invalid_check skipped")
            return
        
        self.health_checks[health_check.name] = health_check
        self.check_priorities[health_check.name] = max(0, min(2, priority))
        
        log.info("health_check.added name=%s priority=%d", health_check.name, priority)
    
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
        
        # Create tasks with timeout
        timeout = self.config.get('health_timeout', 10.0)
        
        for name, health_check in self.health_checks.items():
            # Override timeout if needed
            if hasattr(health_check, 'timeout'):
                health_check.timeout = min(health_check.timeout, timeout)
            
            task = asyncio.create_task(
                self._run_single_check(name, health_check),
                name=f"health_check_{name}"
            )
            tasks.append((name, task))
        
        # Wait for all with overall timeout
        try:
            done, pending = await asyncio.wait(
                [task for _, task in tasks],
                timeout=timeout + 2.0,  # Give a bit more time than individual timeouts
                return_when=asyncio.ALL_COMPLETED
            )
            
            # Cancel any pending tasks
            for task in pending:
                task.cancel()
                log.warning("health_check.timeout task=%s", task.get_name())
            
        except Exception as e:
            log.error("health_check.wait_failed error=%s", str(e))
        
        # Collect results
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
        
        # Determine overall status with priority weighting
        overall_status = self._calculate_overall_status(check_results)
        
        # Create system health
        system_health = SystemHealth(
            overall_status=overall_status,
            checks=check_results,
            metadata=self._generate_health_metadata(check_results)
        )
        
        # Update history
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
        # Critical checks (priority 0) - any failure means unhealthy
        critical_checks = [
            result for name, result in check_results.items()
            if self.check_priorities.get(name, 2) == 0
        ]
        
        if any(r.status == HealthStatus.UNHEALTHY for r in critical_checks):
            return HealthStatus.UNHEALTHY
        
        # Important checks (priority 1) - failures mean at least degraded
        important_checks = [
            result for name, result in check_results.items()
            if self.check_priorities.get(name, 2) == 1
        ]
        
        if any(r.status == HealthStatus.UNHEALTHY for r in important_checks):
            return HealthStatus.DEGRADED
        
        # Check for any degraded status
        if any(r.status == HealthStatus.DEGRADED for r in check_results.values()):
            return HealthStatus.DEGRADED
        
        # Informational checks don't affect overall status unless all fail
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
                
                # Wait for interval or shutdown
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self.check_interval
                    )
                except asyncio.TimeoutError:
                    continue  # Normal timeout, continue monitoring
                
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
```

## **3. metrics.py - Metrics Collection System**

### Critical Issues Found:

1. **Global Metrics Registration** (Lines 23-35)
   - Can fail on module reload
   - No cleanup mechanism

2. **Thread Safety Missing** (Lines 56-77)
   - ToolExecutionMetrics not thread-safe
   - Concurrent updates can corrupt data

3. **Memory Leak Potential**
   - Unbounded growth of tool_metrics dictionary
   - No cleanup of old metrics

### Enhanced Implementation:

```python
# metrics.py - Production-ready version

import time
import logging
import threading
from typing import Dict, Any, Optional, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import deque
import weakref

log = logging.getLogger(__name__)

# Singleton registry for Prometheus metrics
class PrometheusRegistry:
    """Singleton registry to prevent duplicate metric registration."""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def initialize(self):
        """Initialize Prometheus metrics once."""
        if self._initialized:
            return
        
        with self._lock:
            if self._initialized:
                return
            
            try:
                from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry
                from prometheus_client.core import REGISTRY
                
                # Use default registry or create new one
                self.registry = REGISTRY
                
                # Check if metrics already exist
                existing_metrics = {m.name for m in self.registry.collect()}
                
                if 'mcp_tool_execution_total' not in existing_metrics:
                    self.execution_counter = Counter(
                        'mcp_tool_execution_total',
                        'Total tool executions',
                        ['tool', 'status', 'error_type'],
                        registry=self.registry
                    )
                else:
                    # Reuse existing metric
                    self.execution_counter = None
                    for collector in self.registry.collect():
                        if collector.name == 'mcp_tool_execution_total':
                            self.execution_counter = collector
                            break
                
                # Similar pattern for other metrics
                self._initialize_other_metrics(existing_metrics)
                
                self._initialized = True
                self.available = True
                log.info("prometheus.initialized successfully")
                
            except ImportError:
                self.available = False
                log.info("prometheus.not_available")
            except Exception as e:
                self.available = False
                log.error("prometheus.initialization_failed error=%s", str(e))
    
    def _initialize_other_metrics(self, existing_metrics: Set[str]):
        """Initialize remaining metrics with duplicate checking."""
        from prometheus_client import Histogram, Gauge, Counter
        
        if 'mcp_tool_execution_seconds' not in existing_metrics:
            self.execution_histogram = Histogram(
                'mcp_tool_execution_seconds',
                'Tool execution time in seconds',
                ['tool'],
                registry=self.registry
            )
        
        if 'mcp_tool_active' not in existing_metrics:
            self.active_gauge = Gauge(
                'mcp_tool_active',
                'Currently active tool executions',
                ['tool'],
                registry=self.registry
            )
        
        if 'mcp_tool_errors_total' not in existing_metrics:
            self.error_counter = Counter(
                'mcp_tool_errors_total',
                'Total tool errors',
                ['tool', 'error_type'],
                registry=self.registry
            )

# Get or create singleton
_prometheus_registry = PrometheusRegistry()
_prometheus_registry.initialize()

@dataclass
class ToolExecutionMetrics:
    """Thread-safe tool execution metrics."""
    tool_name: str
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    execution_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0
    total_execution_time: float = 0.0
    min_execution_time: float = float('inf')
    max_execution_time: float = 0.0
    last_execution_time: Optional[datetime] = None
    
    # Sliding window for recent metrics
    recent_executions: deque = field(default_factory=lambda: deque(maxlen=100))
    
    def record_execution(self, success: bool, execution_time: float, 
                         timed_out: bool = False, error_type: Optional[str] = None):
        """Thread-safe execution recording."""
        with self._lock:
            execution_time = max(0.0, float(execution_time))
            
            # Update counters
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
            
            # Add to recent executions
            self.recent_executions.append({
                "timestamp": datetime.now(),
                "success": success,
                "execution_time": execution_time,
                "timed_out": timed_out,
                "error_type": error_type
            })
    
    def get_stats(self) -> Dict[str, Any]:
        """Get thread-safe statistics snapshot."""
        with self._lock:
            if self.execution_count == 0:
                return {
                    "tool_name": self.tool_name,
                    "execution_count": 0,
                    "success_rate": 0.0,
                    "average_execution_time": 0.0,
                    "p50_execution_time": 0.0,
                    "p95_execution_time": 0.0,
                    "p99_execution_time": 0.0,
                }
            
            # Calculate percentiles from recent executions
            recent_times = sorted([
                e["execution_time"] for e in self.recent_executions
            ])
            
            p50 = recent_times[len(recent_times) // 2] if recent_times else 0.0
            p95 = recent_times[int(len(recent_times) * 0.95)] if recent_times else 0.0
            p99 = recent_times[int(len(recent_times) * 0.99)] if recent_times else 0.0
            
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
                "p50_execution_time": round(p50, 4),
                "p95_execution_time": round(p95, 4),
                "p99_execution_time": round(p99, 4),
                "last_execution_time": self.last_execution_time.isoformat() if self.last_execution_time else None,
                "recent_failure_rate": self._calculate_recent_failure_rate(),
            }
    
    def _calculate_recent_failure_rate(self) -> float:
        """Calculate failure rate from recent executions."""
        if not self.recent_executions:
            return 0.0
        
        recent_failures = sum(
            1 for e in self.recent_executions if not e["success"]
        )
        return round((recent_failures / len(self.recent_executions)) * 100, 2)

class ToolMetrics:
    """Per-tool metrics wrapper with Prometheus integration."""
    
    def __init__(self, tool_name: str):
        self.tool_name = tool_name
        self.metrics = ToolExecutionMetrics(tool_name)
        self._active_count = 0
        self._lock = threading.Lock()
    
    async def record_execution(self, success: bool, execution_time: float,
                               timed_out: bool = False, error_type: Optional[str] = None):
        """Record execution with Prometheus metrics."""
        # Update internal metrics
        self.metrics.record_execution(success, execution_time, timed_out, error_type)
        
        # Update Prometheus metrics if available
        if _prometheus_registry.available:
            try:
                status = 'success' if success else 'failure'
                error_type = error_type or 'none'
                
                if _prometheus_registry.execution_counter:
                    _prometheus_registry.execution_counter.labels(
                        tool=self.tool_name,
                        status=status,
                        error_type=error_type
                    ).inc()
                
                if _prometheus_registry.execution_histogram:
                    _prometheus_registry.execution_histogram.labels(
                        tool=self.tool_name
                    ).observe(execution_time)
                
                if not success and _prometheus_registry.error_counter:
                    _prometheus_registry.error_counter.labels(
                        tool=self.tool_name,
                        error_type=error_type
                    ).inc()
                
            except Exception as e:
                log.debug("prometheus.record_failed error=%s", str(e))
    
    def increment_active(self):
        """Increment active execution count."""
        with self._lock:
            self._active_count += 1
            if _prometheus_registry.available and _prometheus_registry.active_gauge:
                try:
                    _prometheus_registry.active_gauge.labels(tool=self.tool_name).inc()
                except Exception:
                    pass
    
    def decrement_active(self):
        """Decrement active execution count."""
        with self._lock:
            self._active_count = max(0, self._active_count - 1)
            if _prometheus_registry.available and _prometheus_registry.active_gauge:
                try:
                    _prometheus_registry.active_gauge.labels(tool=self.tool_name).dec()
                except Exception:
                    pass

class MetricsManager:
    """Enhanced metrics manager with memory management."""
    
    def __init__(self, max_tools: int = 1000):
        self.tool_metrics: Dict[str, ToolMetrics] = {}
        self.system_metrics = SystemMetrics()
        self.max_tools = max_tools
        self._lock = threading.Lock()
        
        # Cleanup old metrics periodically
        self._last_cleanup = time.time()
        self._cleanup_interval = 3600  # 1 hour
    
    def get_tool_metrics(self, tool_name: str) -> ToolMetrics:
        """Get or create tool metrics with cleanup."""
        with self._lock:
            # Periodic cleanup
            if time.time() - self._last_cleanup > self._cleanup_interval:
                self._cleanup_old_metrics()
            
            if tool_name not in self.tool_metrics:
                # Check if we're at capacity
                if len(self.tool_metrics) >= self.max_tools:
                    self._evict_oldest_metrics()
                
                self.tool_metrics[tool_name] = ToolMetrics(tool_name)
            
            return self.tool_metrics[tool_name]
    
    def _cleanup_old_metrics(self):
        """Remove metrics for tools not used recently."""
        cutoff_time = datetime.now() - timedelta(hours=24)
        
        to_remove = []
        for name, metrics in self.tool_metrics.items():
            last_time = metrics.metrics.last_execution_time
            if last_time and last_time < cutoff_time:
                to_remove.append(name)
        
        for name in to_remove:
            del self.tool_metrics[name]
        
        if to_remove:
            log.info("metrics.cleanup removed=%d tools", len(to_remove))
        
        self._last_cleanup = time.time()
    
    def _evict_oldest_metrics(self):
        """Evict least recently used metrics."""
        if not self.tool_metrics:
            return
        
        # Find oldest
        oldest_name = None
        oldest_time = datetime.now()
        
        for name, metrics in self.tool_metrics.items():
            last_time = metrics.metrics.last_execution_time
            if last_time and last_time < oldest_time:
                oldest_time = last_time
                oldest_name = name
        
        if oldest_name:
            del self.tool_metrics[oldest_name]
            log.info("metrics.evicted tool=%s", oldest_name)
```

## Summary of Enhancements

### **Circuit Breaker**
- Added adaptive timeout with exponential backoff
- Implemented proper concurrency control for HALF_OPEN state
- Added comprehensive metrics and statistics
- Enhanced error tracking with recent error history
- Added jitter to prevent thundering herd

### **Health Monitoring**
- Simplified config normalization with better error handling
- Added priority-based health check evaluation
- Implemented proper task lifecycle management
- Added health check history tracking
- Enhanced timeout handling

### **Metrics**
- Fixed Prometheus metric registration issues with singleton pattern
- Added thread safety to all metric operations
- Implemented memory management with LRU eviction
- Added percentile calculations (p50, p95, p99)
- Enhanced with sliding window for recent metrics

These enhancements make the monitoring and resilience components production-ready with proper error handling, thread safety, and resource management.
