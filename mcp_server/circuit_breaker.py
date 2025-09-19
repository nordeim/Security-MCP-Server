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
