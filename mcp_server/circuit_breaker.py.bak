# File: circuit_breaker.py
"""
Circuit breaker implementation for MCP tool resilience.
Production-ready implementation with proper exception handling and edge cases.
"""
import asyncio
import time
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Callable, Any, Optional, Tuple

log = logging.getLogger(__name__)

class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass

class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation, requests pass through
    OPEN = "open"         # Circuit is open, requests fail fast
    HALF_OPEN = "half_open"  # Testing if service has recovered

@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    expected_exception: Tuple = (Exception,)
    timeout_exception: Tuple = (asyncio.TimeoutError,)

class CircuitBreaker:
    """
    Circuit breaker implementation for protecting against cascading failures.
    Production-ready with proper edge case handling and thread safety.
    """
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0,
                 expected_exception: Tuple = (Exception,), name: str = "tool"):
        self.failure_threshold = max(1, failure_threshold)  # Ensure at least 1
        self.recovery_timeout = max(1.0, recovery_timeout)  # Ensure at least 1 second
        self.expected_exception = expected_exception
        self.name = name
        
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0
        self._success_count = 0
        self._lock = asyncio.Lock()
        
        log.info("circuit_breaker.created name=%s threshold=%d timeout=%.1f",
                self.name, self.failure_threshold, self.recovery_timeout)
    
    @property
    def state(self) -> CircuitBreakerState:
        """Get current circuit breaker state."""
        return self._state
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.
        """
        async with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                if self._should_attempt_reset():
                    self._state = CircuitBreakerState.HALF_OPEN
                    self._success_count = 0
                    log.info("circuit_breaker.half_open name=%s", self.name)
                else:
                    raise CircuitBreakerOpenError(f"Circuit breaker is open for {self.name}")
        
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except self.expected_exception as e:
            await self._on_failure()
            raise
        except Exception as e:
            # For unexpected exceptions, we don't count as failures
            log.warning("circuit_breaker.unexpected_error name=%s error=%s",
                       self.name, str(e))
            raise
    
    def _should_attempt_reset(self) -> bool:
        """
        Check if circuit breaker should attempt reset.
        Enhanced with proper edge case handling.
        """
        # Don't attempt reset if we've never had a failure
        if self._last_failure_time <= 0:
            return False
        
        # Check if enough time has passed since last failure
        return (time.time() - self._last_failure_time) >= self.recovery_timeout
    
    async def _on_success(self):
        """Handle successful execution."""
        async with self._lock:
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._success_count += 1
                # Reset after 1 success in half-open state
                if self._success_count >= 1:
                    self._state = CircuitBreakerState.CLOSED
                    self._failure_count = 0
                    log.info("circuit_breaker.closed name=%s", self.name)
            else:
                # Reset failure count on success in closed state
                if self._failure_count > 0:
                    self._failure_count = 0
                    log.debug("circuit_breaker.failure_count_reset name=%s", self.name)
    
    async def _on_failure(self):
        """Handle failed execution."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if (self._state == CircuitBreakerState.CLOSED and 
                self._failure_count >= self.failure_threshold):
                self._state = CircuitBreakerState.OPEN
                log.warning("circuit_breaker.open name=%s failures=%d",
                           self.name, self._failure_count)
            elif self._state == CircuitBreakerState.HALF_OPEN:
                # Immediately return to open state on failure in half-open
                self._state = CircuitBreakerState.OPEN
                log.warning("circuit_breaker.reopened name=%s", self.name)
    
    def force_open(self):
        """Force circuit breaker to open state."""
        async with self._lock:
            self._state = CircuitBreakerState.OPEN
            self._failure_count = self.failure_threshold
            self._last_failure_time = time.time()
            log.info("circuit_breaker.force_open name=%s", self.name)
    
    def force_close(self):
        """Force circuit breaker to closed state."""
        async with self._lock:
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = 0
            log.info("circuit_breaker.force_close name=%s", self.name)
    
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
            "time_since_last_failure": time.time() - self._last_failure_time if self._last_failure_time > 0 else 0
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
        
        return False  # Don't suppress exceptions
