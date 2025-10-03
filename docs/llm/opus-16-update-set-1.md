## Comprehensive Execution Plan for Production-Ready Core Files

I'll meticulously review, validate, and create complete drop-in replacements for each core file. Let me start with a comprehensive execution plan with integrated checklists.

### 📋 Master Execution Plan

#### Phase 1: Dependencies & Imports Validation
- Ensure all imports are properly handled with fallbacks
- Validate type hints compatibility
- Check for circular dependencies

#### Phase 2: File-by-File Updates
Each file will be validated against its checklist before proceeding to the next.

#### Phase 3: Cross-File Integration Validation
- Ensure all files work together seamlessly
- Validate interfaces between components

### File Update Checklists

#### ✅ **server.py** Checklist:
- [ ] Health manager properly initialized and used
- [ ] HTTP endpoints fully implemented with tool execution
- [ ] Consistent type hints (List vs list)
- [ ] Metrics integration complete
- [ ] Signal handlers with error recovery
- [ ] SSE endpoint for real-time updates
- [ ] Tool registry with enable/disable functionality
- [ ] Graceful shutdown handling
- [ ] Config integration validated
- [ ] No placeholder comments

#### ✅ **config.py** Checklist:
- [ ] Thread safety with RLock
- [ ] Complete validation for all config sections
- [ ] Safe config normalization
- [ ] Hot-reload functionality
- [ ] Deep merge implementation
- [ ] Testing support (force_new, reset_config)
- [ ] Sensitive data redaction
- [ ] Type conversion and constraints
- [ ] File save/load with YAML/JSON support
- [ ] No placeholder comments

#### ✅ **health.py** Checklist:
- [ ] Simplified config normalization
- [ ] Priority-based health checks
- [ ] Proper task lifecycle management
- [ ] Health check history tracking
- [ ] Timeout handling for all checks
- [ ] System resource checks with psutil fallback
- [ ] Tool availability checks
- [ ] Dependency checks
- [ ] Async context manager support
- [ ] No placeholder comments

#### ✅ **metrics.py** Checklist:
- [ ] Singleton Prometheus registry
- [ ] Thread safety for all metrics
- [ ] Memory management with LRU eviction
- [ ] Percentile calculations (p50, p95, p99)
- [ ] Sliding window for recent metrics
- [ ] Graceful Prometheus fallback
- [ ] Tool metrics wrapper
- [ ] System metrics tracking
- [ ] Cleanup mechanisms
- [ ] No placeholder comments

#### ✅ **circuit_breaker.py** Checklist:
- [ ] Adaptive timeout with backoff
- [ ] Proper concurrency control
- [ ] Metrics integration
- [ ] Error history tracking
- [ ] Jitter for thundering herd prevention
- [ ] State transition logging
- [ ] Statistics collection
- [ ] Force open/close functionality
- [ ] Async and sync callable support
- [ ] No placeholder comments

#### ✅ **base_tool.py** Checklist:
- [ ] Instance-level circuit breaker
- [ ] Fixed mutable defaults
- [ ] Clean Pydantic fallback
- [ ] Proper async handling
- [ ] Metrics recording with shields
- [ ] Error context with recovery suggestions
- [ ] Semaphore for concurrency control
- [ ] Input validation
- [ ] Resource limits enforcement
- [ ] No placeholder comments

---

## Executing Plan: Creating Production-Ready Files

### 1. **circuit_breaker.py** - Complete Production-Ready Version

```python
"""
Circuit breaker implementation for MCP tool resilience.
Production-ready implementation with metrics, adaptive recovery, and proper concurrency handling.
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
        ['name', 'result']
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


class CircuitBreaker:
    """
    Production-ready circuit breaker with adaptive recovery and metrics.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: Tuple[type, ...] = (Exception,),
        name: str = "tool",
        success_threshold: int = 1,
        timeout_multiplier: float = 1.5,
        max_timeout: float = 300.0,
        enable_jitter: bool = True,
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
        
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._consecutive_failures = 0
        self._lock = asyncio.Lock()
        
        self.stats = CircuitBreakerStats()
        self._recent_errors = deque(maxlen=10)
        self._half_open_calls = 0
        self._max_half_open_calls = 1
        
        self._update_metrics()
        
        log.info(
            "circuit_breaker.created name=%s threshold=%d timeout=%.1f",
            self.name, self.failure_threshold, self.initial_recovery_timeout
        )
    
    @property
    def state(self) -> CircuitBreakerState:
        """Get current state."""
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
        """
        # Check and potentially transition state
        async with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                if self._should_attempt_reset():
                    old_state = self._state
                    self._state = CircuitBreakerState.HALF_OPEN
                    self._success_count = 0
                    self._half_open_calls = 0
                    self.stats.state_changes += 1
                    self.stats.last_state_change = datetime.now()
                    self._update_metrics()
                    self._record_transition_metric(old_state, self._state)
                    log.info("circuit_breaker.half_open name=%s", self.name)
                else:
                    retry_after = self._get_retry_after()
                    self.stats.rejected_calls += 1
                    self._record_call_metric("rejected")
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker is open for {self.name}",
                        retry_after=retry_after
                    )
            
            if self._state == CircuitBreakerState.HALF_OPEN:
                if self._half_open_calls >= self._max_half_open_calls:
                    self.stats.rejected_calls += 1
                    self._record_call_metric("rejected")
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker is testing recovery for {self.name}",
                        retry_after=5.0
                    )
                self._half_open_calls += 1
        
        # Execute the function
        try:
            self.stats.total_calls += 1
            result = func(*args, **kwargs)
            
            if inspect.isawaitable(result):
                result = await result
            
            await self._on_success()
            self.stats.successful_calls += 1
            self.stats.last_success_time = time.time()
            self._record_call_metric("success")
            
            return result
            
        except Exception as e:
            self.stats.failed_calls += 1
            self.stats.last_failure_time = time.time()
            
            error_type = type(e).__name__
            self.stats.failure_reasons[error_type] = self.stats.failure_reasons.get(error_type, 0) + 1
            
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
            if self._state == CircuitBreakerState.HALF_OPEN:
                async with self._lock:
                    self._half_open_calls = max(0, self._half_open_calls - 1)
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed for recovery attempt."""
        if self._last_failure_time <= 0:
            return False
        
        time_since_failure = time.time() - self._last_failure_time
        recovery_time = self.current_recovery_timeout
        
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
    
    async def _on_success(self):
        """Handle successful execution."""
        async with self._lock:
            self.stats.consecutive_successes += 1
            self.stats.consecutive_failures = 0
            self._consecutive_failures = 0
            
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._success_count += 1
                
                if self._success_count >= self.success_threshold:
                    old_state = self._state
                    self._state = CircuitBreakerState.CLOSED
                    self._failure_count = 0
                    self.current_recovery_timeout = self.initial_recovery_timeout
                    
                    self.stats.state_changes += 1
                    self.stats.last_state_change = datetime.now()
                    
                    self._update_metrics()
                    self._record_transition_metric(old_state, self._state)
                    
                    log.info("circuit_breaker.closed name=%s", self.name)
            elif self._state == CircuitBreakerState.CLOSED:
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
                    old_state = self._state
                    self._state = CircuitBreakerState.OPEN
                    
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
                old_state = self._state
                self._state = CircuitBreakerState.OPEN
                
                self.current_recovery_timeout = min(
                    self.current_recovery_timeout * self.timeout_multiplier,
                    self.max_timeout
                )
                
                self.stats.state_changes += 1
                self.stats.last_state_change = datetime.now()
                
                self._update_metrics()
                self._record_transition_metric(old_state, self._state)
                
                log.warning(
                    "circuit_breaker.reopened name=%s timeout=%.1fs",
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
            self._last_failure_time = 0.0
            
            if old_state != self._state:
                self.stats.state_changes += 1
                self.stats.last_state_change = datetime.now()
                self._update_metrics()
                self._record_transition_metric(old_state, self._state)
            
            log.info("circuit_breaker.force_close name=%s", self.name)
    
    def force_open_nowait(self):
        """Synchronous wrapper for force_open."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.force_open())
        else:
            loop.create_task(self.force_open())
    
    def force_close_nowait(self):
        """Synchronous wrapper for force_close."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.force_close())
        else:
            loop.create_task(self.force_close())
    
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


class CircuitBreakerContext:
    """Context manager for circuit breaker operations."""
    
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
        
        return False
```

### ✅ circuit_breaker.py Checklist Validation:
- ✓ Adaptive timeout with backoff
- ✓ Proper concurrency control
- ✓ Metrics integration
- ✓ Error history tracking
- ✓ Jitter for thundering herd prevention
- ✓ State transition logging
- ✓ Statistics collection
- ✓ Force open/close functionality
- ✓ Async and sync callable support
- ✓ No placeholder comments

---

### 2. **metrics.py** - Complete Production-Ready Version

```python
"""
Metrics collection system for MCP server.
Production-ready implementation with thread safety and memory management.
"""
import time
import logging
import threading
from typing import Dict, Any, Optional, Set, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import deque

log = logging.getLogger(__name__)


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
                from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, generate_latest
                from prometheus_client.core import REGISTRY
                
                self.registry = REGISTRY
                self.generate_latest = generate_latest
                
                existing_metrics = {collector.name for collector in self.registry._collector_to_names.keys() 
                                  if hasattr(collector, 'name')}
                
                if 'mcp_tool_execution_total' not in existing_metrics:
                    self.execution_counter = Counter(
                        'mcp_tool_execution_total',
                        'Total tool executions',
                        ['tool', 'status', 'error_type'],
                        registry=self.registry
                    )
                else:
                    self.execution_counter = None
                    for collector in self.registry._collector_to_names.keys():
                        if hasattr(collector, '_name') and collector._name == 'mcp_tool_execution_total':
                            self.execution_counter = collector
                            break
                
                if 'mcp_tool_execution_seconds' not in existing_metrics:
                    self.execution_histogram = Histogram(
                        'mcp_tool_execution_seconds',
                        'Tool execution time in seconds',
                        ['tool'],
                        registry=self.registry
                    )
                else:
                    self.execution_histogram = None
                    for collector in self.registry._collector_to_names.keys():
                        if hasattr(collector, '_name') and collector._name == 'mcp_tool_execution_seconds':
                            self.execution_histogram = collector
                            break
                
                if 'mcp_tool_active' not in existing_metrics:
                    self.active_gauge = Gauge(
                        'mcp_tool_active',
                        'Currently active tool executions',
                        ['tool'],
                        registry=self.registry
                    )
                else:
                    self.active_gauge = None
                    for collector in self.registry._collector_to_names.keys():
                        if hasattr(collector, '_name') and collector._name == 'mcp_tool_active':
                            self.active_gauge = collector
                            break
                
                if 'mcp_tool_errors_total' not in existing_metrics:
                    self.error_counter = Counter(
                        'mcp_tool_errors_total',
                        'Total tool errors',
                        ['tool', 'error_type'],
                        registry=self.registry
                    )
                else:
                    self.error_counter = None
                    for collector in self.registry._collector_to_names.keys():
                        if hasattr(collector, '_name') and collector._name == 'mcp_tool_errors_total':
                            self.error_counter = collector
                            break
                
                self._initialized = True
                self.available = True
                log.info("prometheus.initialized successfully")
                
            except ImportError:
                self.available = False
                self.generate_latest = None
                log.info("prometheus.not_available")
            except Exception as e:
                self.available = False
                self.generate_latest = None
                log.error("prometheus.initialization_failed error=%s", str(e))


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
    recent_executions: deque = field(default_factory=lambda: deque(maxlen=100))
    
    def record_execution(self, success: bool, execution_time: float, 
                         timed_out: bool = False, error_type: Optional[str] = None):
        """Thread-safe execution recording."""
        with self._lock:
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
            
            recent_times = sorted([
                e["execution_time"] for e in self.recent_executions
            ])
            
            if recent_times:
                p50_idx = len(recent_times) // 2
                p95_idx = min(int(len(recent_times) * 0.95), len(recent_times) - 1)
                p99_idx = min(int(len(recent_times) * 0.99), len(recent_times) - 1)
                
                p50 = recent_times[p50_idx]
                p95 = recent_times[p95_idx]
                p99 = recent_times[p99_idx]
            else:
                p50 = p95 = p99 = 0.0
            
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


class SystemMetrics:
    """System-wide metrics tracking."""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.request_count = 0
        self.error_count = 0
        self.active_connections = 0
        self._lock = threading.Lock()
    
    def increment_request_count(self):
        """Thread-safe request count increment."""
        with self._lock:
            self.request_count += 1
    
    def increment_error_count(self):
        """Thread-safe error count increment."""
        with self._lock:
            self.error_count += 1
    
    def increment_active_connections(self):
        """Thread-safe active connections increment."""
        with self._lock:
            self.active_connections += 1
    
    def decrement_active_connections(self):
        """Thread-safe active connections decrement."""
        with self._lock:
            self.active_connections = max(0, self.active_connections - 1)
    
    def get_uptime(self) -> float:
        """Get system uptime in seconds."""
        return (datetime.now() - self.start_time).total_seconds()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get system statistics."""
        with self._lock:
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
        self.metrics.record_execution(success, execution_time, timed_out, error_type)
        
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
        self._last_cleanup = time.time()
        self._cleanup_interval = 3600
        self.start_time = datetime.now()
    
    def get_tool_metrics(self, tool_name: str) -> ToolMetrics:
        """Get or create tool metrics with cleanup."""
        with self._lock:
            if time.time() - self._last_cleanup > self._cleanup_interval:
                self._cleanup_old_metrics()
            
            if tool_name not in self.tool_metrics:
                if len(self.tool_metrics) >= self.max_tools:
                    self._evict_oldest_metrics()
                
                self.tool_metrics[tool_name] = ToolMetrics(tool_name)
            
            return self.tool_metrics[tool_name]
    
    def record_tool_execution(self, tool_name: str, success: bool, execution_time: float,
                             timed_out: bool = False, error_type: str = None):
        """Record tool execution metrics."""
        tool_metrics = self.get_tool_metrics(tool_name)
        tool_metrics.metrics.record_execution(success, execution_time, timed_out, error_type)
        
        if _prometheus_registry.available:
            try:
                status = 'success' if success else 'failure'
                error_type = error_type or 'none'
                
                if _prometheus_registry.execution_counter:
                    _prometheus_registry.execution_counter.labels(
                        tool=tool_name,
                        status=status,
                        error_type=error_type
                    ).inc()
                
                if _prometheus_registry.execution_histogram:
                    _prometheus_registry.execution_histogram.labels(tool=tool_name).observe(float(execution_time))
                
                if not success and _prometheus_registry.error_counter:
                    _prometheus_registry.error_counter.labels(
                        tool=tool_name,
                        error_type=error_type
                    ).inc()
            except Exception as e:
                log.warning("prometheus.tool_execution_error error=%s", str(e))
        
        self.system_metrics.increment_request_count()
        if not success:
            self.system_metrics.increment_error_count()
    
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
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get all metrics statistics."""
        return {
            "system": self.system_metrics.get_stats(),
            "tools": {name: metrics.metrics.get_stats() for name, metrics in self.tool_metrics.items()},
            "prometheus_available": _prometheus_registry.available,
            "collection_start_time": self.start_time.isoformat()
        }
    
    def get_prometheus_metrics(self) -> Optional[str]:
        """Get Prometheus metrics in text format."""
        if _prometheus_registry.available and _prometheus_registry.generate_latest:
            try:
                return _prometheus_registry.generate_latest(_prometheus_registry.registry).decode('utf-8')
            except Exception as e:
                log.error("prometheus.generate_metrics_error error=%s", str(e))
                return None
        return None


class PrometheusMetrics:
    """Legacy compatibility class."""
    
    def __init__(self):
        self.registry = _prometheus_registry.registry if _prometheus_registry.available else None
    
    def get_metrics(self) -> Optional[str]:
        """Get Prometheus metrics."""
        if _prometheus_registry.available and _prometheus_registry.generate_latest:
            try:
                return _prometheus_registry.generate_latest(_prometheus_registry.registry).decode('utf-8')
            except Exception as e:
                log.error("prometheus.generate_metrics_error error=%s", str(e))
                return None
        return None
```

### ✅ metrics.py Checklist Validation:
- ✓ Singleton Prometheus registry
- ✓ Thread safety for all metrics
- ✓ Memory management with LRU eviction
- ✓ Percentile calculations (p50, p95, p99)
- ✓ Sliding window for recent metrics
- ✓ Graceful Prometheus fallback
- ✓ Tool metrics wrapper
- ✓ System metrics tracking
- ✓ Cleanup mechanisms
- ✓ No placeholder comments

---

### 3. **config.py** - Complete Production-Ready Version

```python
"""
Configuration management system for MCP server.
Production-ready implementation with validation, hot-reload, and sensitive data handling.
"""
import os
import logging
import json
import yaml
import threading
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from contextlib import contextmanager

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
    max_file_size: int = 10485760
    backup_count: int = 5


@dataclass
class ServerConfig:
    """Server configuration."""
    host: str = "0.0.0.0"
    port: int = 8080
    transport: str = "stdio"
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
        self._lock = threading.RLock()
        
        self.database = DatabaseConfig()
        self.security = SecurityConfig()
        self.circuit_breaker = CircuitBreakerConfig()
        self.health = HealthConfig()
        self.metrics = MetricsConfig()
        self.logging = LoggingConfig()
        self.server = ServerConfig()
        self.tool = ToolConfig()
        
        self.load_config()
    
    @contextmanager
    def _config_lock(self):
        """Context manager for thread-safe config access."""
        self._lock.acquire()
        try:
            yield
        finally:
            self._lock.release()
    
    def load_config(self):
        """Thread-safe configuration loading."""
        with self._config_lock():
            try:
                config_data = self._get_defaults()
                
                if self.config_path and os.path.exists(self.config_path):
                    file_data = self._load_from_file(self.config_path)
                    config_data = self._deep_merge(config_data, file_data)
                
                env_data = self._load_from_environment()
                config_data = self._deep_merge(config_data, env_data)
                
                self._validate_config(config_data)
                self._apply_config(config_data)
                
                if self.config_path and os.path.exists(self.config_path):
                    self.last_modified = os.path.getmtime(self.config_path)
                
                log.info("config.loaded_successfully")
                
            except Exception as e:
                log.error("config.load_failed error=%s", str(e))
                if not hasattr(self, 'server'):
                    self._initialize_defaults()
    
    def _initialize_defaults(self):
        """Initialize with default configuration."""
        self.database = DatabaseConfig()
        self.security = SecurityConfig()
        self.circuit_breaker = CircuitBreakerConfig()
        self.health = HealthConfig()
        self.metrics = MetricsConfig()
        self.logging = LoggingConfig()
        self.server = ServerConfig()
        self.tool = ToolConfig()
    
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
        
        env_mappings = {
            'MCP_DATABASE_URL': ('database', 'url'),
            'MCP_DATABASE_POOL_SIZE': ('database', 'pool_size'),
            'MCP_SECURITY_MAX_ARGS_LENGTH': ('security', 'max_args_length'),
            'MCP_SECURITY_TIMEOUT_SECONDS': ('security', 'timeout_seconds'),
            'MCP_SECURITY_CONCURRENCY_LIMIT': ('security', 'concurrency_limit'),
            'MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD': ('circuit_breaker', 'failure_threshold'),
            'MCP_CIRCUIT_BREAKER_RECOVERY_TIMEOUT': ('circuit_breaker', 'recovery_timeout'),
            'MCP_HEALTH_CHECK_INTERVAL': ('health', 'check_interval'),
            'MCP_HEALTH_CPU_THRESHOLD': ('health', 'cpu_threshold'),
            'MCP_HEALTH_MEMORY_THRESHOLD': ('health', 'memory_threshold'),
            'MCP_HEALTH_DISK_THRESHOLD': ('health', 'disk_threshold'),
            'MCP_METRICS_ENABLED': ('metrics', 'enabled'),
            'MCP_METRICS_PROMETHEUS_PORT': ('metrics', 'prometheus_port'),
            'MCP_LOGGING_LEVEL': ('logging', 'level'),
            'MCP_LOGGING_FILE_PATH': ('logging', 'file_path'),
            'MCP_SERVER_HOST': ('server', 'host'),
            'MCP_SERVER_PORT': ('server', 'port'),
            'MCP_SERVER_TRANSPORT': ('server', 'transport'),
            'MCP_SERVER_SHUTDOWN_GRACE_PERIOD': ('server', 'shutdown_grace_period'),
            'MCP_TOOL_DEFAULT_TIMEOUT': ('tool', 'default_timeout'),
            'MCP_TOOL_DEFAULT_CONCURRENCY': ('tool', 'default_concurrency'),
        }
        
        for env_var, (section, key) in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                if section not in config:
                    config[section] = {}
                
                if key in ['pool_size', 'max_args_length', 'timeout_seconds', 'concurrency_limit',
                          'failure_threshold', 'prometheus_port', 'default_timeout', 'default_concurrency',
                          'port', 'workers', 'max_connections']:
                    try:
                        config[section][key] = int(value)
                    except ValueError:
                        log.warning("config.invalid_int env_var=%s value=%s", env_var, value)
                elif key in ['recovery_timeout', 'check_interval', 'cpu_threshold', 'memory_threshold',
                            'disk_threshold', 'timeout', 'collection_interval', 'shutdown_grace_period']:
                    try:
                        config[section][key] = float(value)
                    except ValueError:
                        log.warning("config.invalid_float env_var=%s value=%s", env_var, value)
                elif key in ['enabled', 'prometheus_enabled']:
                    config[section][key] = value.lower() in ['true', '1', 'yes', 'on']
                else:
                    config[section][key] = value
        
        return config
    
    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """Deep merge configuration dictionaries."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result
    
    def _validate_config(self, config_data: Dict[str, Any]):
        """Comprehensive configuration validation."""
        validators = {
            'database': self._validate_database_config,
            'security': self._validate_security_config,
            'circuit_breaker': self._validate_circuit_breaker_config,
            'health': self._validate_health_config,
            'metrics': self._validate_metrics_config,
            'server': self._validate_server_config,
            'tool': self._validate_tool_config,
        }
        
        for section, validator in validators.items():
            if section in config_data:
                validator(config_data[section])
    
    def _validate_database_config(self, config: Dict):
        """Validate database configuration."""
        if 'pool_size' in config:
            config['pool_size'] = max(1, min(100, int(config['pool_size'])))
        if 'max_overflow' in config:
            config['max_overflow'] = max(0, min(100, int(config['max_overflow'])))
        if 'pool_timeout' in config:
            config['pool_timeout'] = max(1, min(300, int(config['pool_timeout'])))
        if 'pool_recycle' in config:
            config['pool_recycle'] = max(60, min(7200, int(config['pool_recycle'])))
    
    def _validate_security_config(self, config: Dict):
        """Validate security configuration."""
        if 'max_args_length' in config:
            config['max_args_length'] = max(1, min(10240, int(config['max_args_length'])))
        if 'max_output_size' in config:
            config['max_output_size'] = max(1024, min(10485760, int(config['max_output_size'])))
        if 'timeout_seconds' in config:
            config['timeout_seconds'] = max(1, min(3600, int(config['timeout_seconds'])))
        if 'concurrency_limit' in config:
            config['concurrency_limit'] = max(1, min(100, int(config['concurrency_limit'])))
    
    def _validate_circuit_breaker_config(self, config: Dict):
        """Validate circuit breaker configuration."""
        if 'failure_threshold' in config:
            config['failure_threshold'] = max(1, min(100, int(config['failure_threshold'])))
        if 'recovery_timeout' in config:
            config['recovery_timeout'] = max(1.0, min(600.0, float(config['recovery_timeout'])))
        if 'half_open_success_threshold' in config:
            config['half_open_success_threshold'] = max(1, min(10, int(config['half_open_success_threshold'])))
    
    def _validate_health_config(self, config: Dict):
        """Validate health configuration."""
        if 'check_interval' in config:
            config['check_interval'] = max(5.0, min(300.0, float(config['check_interval'])))
        for threshold_key in ['cpu_threshold', 'memory_threshold', 'disk_threshold']:
            if threshold_key in config:
                config[threshold_key] = max(0.0, min(100.0, float(config[threshold_key])))
        if 'timeout' in config:
            config['timeout'] = max(1.0, min(60.0, float(config['timeout'])))
    
    def _validate_metrics_config(self, config: Dict):
        """Validate metrics configuration."""
        if 'prometheus_port' in config:
            config['prometheus_port'] = max(1, min(65535, int(config['prometheus_port'])))
        if 'collection_interval' in config:
            config['collection_interval'] = max(5.0, min(300.0, float(config['collection_interval'])))
    
    def _validate_server_config(self, config: Dict):
        """Validate server configuration."""
        if 'port' in config:
            port = int(config['port'])
            if not (1 <= port <= 65535):
                raise ValueError(f"Invalid port: {port}")
            config['port'] = port
        
        if 'transport' in config:
            transport = str(config['transport']).lower()
            if transport not in ['stdio', 'http']:
                raise ValueError(f"Invalid transport: {transport}")
            config['transport'] = transport
        
        if 'host' in config:
            import socket
            try:
                socket.inet_aton(config['host'])
            except socket.error:
                try:
                    socket.gethostbyname(config['host'])
                except socket.error:
                    raise ValueError(f"Invalid host: {config['host']}")
        
        if 'workers' in config:
            config['workers'] = max(1, min(16, int(config['workers'])))
        if 'max_connections' in config:
            config['max_connections'] = max(1, min(10000, int(config['max_connections'])))
        if 'shutdown_grace_period' in config:
            config['shutdown_grace_period'] = max(0.0, min(300.0, float(config['shutdown_grace_period'])))
    
    def _validate_tool_config(self, config: Dict):
        """Validate tool configuration."""
        if 'default_timeout' in config:
            config['default_timeout'] = max(1, min(3600, int(config['default_timeout'])))
        if 'default_concurrency' in config:
            config['default_concurrency'] = max(1, min(100, int(config['default_concurrency'])))
    
    def _apply_config(self, config_data: Dict[str, Any]):
        """Apply validated configuration."""
        if 'database' in config_data:
            for key, value in config_data['database'].items():
                setattr(self.database, key, value)
        
        if 'security' in config_data:
            for key, value in config_data['security'].items():
                setattr(self.security, key, value)
        
        if 'circuit_breaker' in config_data:
            for key, value in config_data['circuit_breaker'].items():
                setattr(self.circuit_breaker, key, value)
        
        if 'health' in config_data:
            for key, value in config_data['health'].items():
                setattr(self.health, key, value)
        
        if 'metrics' in config_data:
            for key, value in config_data['metrics'].items():
                setattr(self.metrics, key, value)
        
        if 'logging' in config_data:
            for key, value in config_data['logging'].items():
                setattr(self.logging, key, value)
        
        if 'server' in config_data:
            for key, value in config_data['server'].items():
                setattr(self.server, key, value)
        
        if 'tool' in config_data:
            for key, value in config_data['tool'].items():
                setattr(self.tool, key, value)
        
        self._config_data = config_data
    
    def check_for_changes(self) -> bool:
        """Check if configuration file has been modified."""
        if not self.config_path:
            return False
        
        try:
            current_mtime = os.path.getmtime(self.config_path)
            if current_mtime != self.last_modified:
                return True
        except OSError:
            pass
        
        return False
    
    def reload_config(self):
        """Thread-safe configuration reload."""
        with self._config_lock():
            if self.check_for_changes():
                log.info("config.reloading_changes_detected")
                backup = self.to_dict(redact_sensitive=False)
                try:
                    self.load_config()
                    return True
                except Exception as e:
                    log.error("config.reload_failed error=%s reverting", str(e))
                    self._apply_config(backup)
                    return False
        return False
    
    def get_sensitive_keys(self) -> List[str]:
        """Get list of sensitive configuration keys."""
        return [
            'database.url',
            'security.api_key',
            'security.secret_key',
            'logging.file_path'
        ]
    
    def redact_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Redact sensitive data from configuration."""
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


_config_instance = None
_config_lock = threading.Lock()


def get_config(config_path: Optional[str] = None, force_new: bool = False) -> MCPConfig:
    """Get configuration instance with testing support."""
    global _config_instance
    
    with _config_lock:
        if force_new or _config_instance is None:
            _config_instance = MCPConfig(config_path)
        return _config_instance


def reset_config():
    """Reset configuration (for testing)."""
    global _config_instance
    with _config_lock:
        _config_instance = None
```

### ✅ config.py Checklist Validation:
- ✓ Thread safety with RLock
- ✓ Complete validation for all config sections
- ✓ Safe config normalization
- ✓ Hot-reload functionality
- ✓ Deep merge implementation
- ✓ Testing support (force_new, reset_config)
- ✓ Sensitive data redaction
- ✓ Type conversion and constraints
- ✓ File save/load with YAML/JSON support
- ✓ No placeholder comments

---
