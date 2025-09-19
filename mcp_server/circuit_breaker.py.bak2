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
