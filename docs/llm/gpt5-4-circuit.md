Nice — I reviewed circuit_breaker.py carefully and prepared a focused, safe patch plus a validation plan and tests. Below I:

- Summarize the problems I found (priority order).
- Explain the fixes and rationale.
- Provide an improved, fully compatible implementation of circuit_breaker.py (ready to drop into the repo).
- Give a concise validation checklist and example unit tests / runtime checks to verify behavior.

High-priority issues found (summary)
1. force_open and force_close are synchronous def methods that use "async with self._lock" — that is invalid (cannot use async context manager inside a plain sync function). This will raise a SyntaxError / runtime error if those methods are called.
2. call() assumed the provided func is awaitable (an async function). If a sync function is passed, awaiting it will fail. The implementation should accept both sync and async callables (call the function, check if return is awaitable, await if needed).
3. CircuitBreaker.call catches expected exceptions via "except self.expected_exception as e" — fine, but clearer/more robust to use isinstance(e, self.expected_exception) in a single except Exception handler to properly handle mixed expected/ unexpected exceptions when using sync/async support.
4. Small improvements: better typing for expected_exception, defensive logging, and helper synchronous wrappers for force_open/force_close (convenience when library used from sync code).
5. Minor: CircuitBreakerConfig dataclass is unused but can remain (harmless). I preserved it.

What I changed and why
- Made force_open and force_close asynchronous (async def) and added synchronous convenience wrappers force_open_nowait and force_close_nowait that schedule the async operation if an event loop is running, or run it directly otherwise — this makes APIs safe from both sync and async callsites.
- Made call() accept both sync and async callables: call the function; if return value is awaitable, await it; otherwise use the result directly.
- Consolidated exception handling: use a single except Exception as e clause and check isinstance(e, self.expected_exception) to decide whether to count as expected failure and call _on_failure() (then re-raise), or treat as unexpected (log and re-raise without increment).
- Improved docstrings and small defensive checks (e.g., skip scheduling if no loop).
- Kept API backwards-compatible: existing code that uses await cb.call(async_function, ...) continues to work; code that used cb.force_open() may need to call force_open_nowait() in sync contexts (I added wrapper). I also left CircuitBreakerContext unchanged other than minor formatting.

Proposed corrected file
```python name=mcp_server/circuit_breaker.py
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

Validation checklist (how you can verify locally)
1. Static checks
   - Run flake8 / pylint on the file to check style and obvious errors.
   - Run mypy if you use static typing.

2. Unit tests (examples)
   - Test successful calls (sync and async):
     - Create cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1)
     - Define sync func that returns value; assert await cb.call(sync_func) returns value
     - Define async func that returns value; assert await cb.call(async_func) returns value
   - Test failure counting:
     - Create a callable that raises a custom expected_exception (pass that class in expected_exception tuple), call twice, verify cb.state becomes OPEN after threshold.
   - Test open behavior:
     - When OPEN and within recovery_timeout, calling call should raise CircuitBreakerOpenError.
   - Test half-open reset:
     - After wait for recovery_timeout, call again (success) and ensure state transitions to CLOSED.
   - Test force_open_nowait/force_close_nowait:
     - Call force_open_nowait() from sync test and verify cb.get_stats()['state']=='open' (give small sleep if needed for scheduled task).

3. Runtime / integration
   - Integrate with a sample tool that raises a known expected exception; verify CircuitBreaker transitions behave as expected under concurrent calls.
   - Add integration test where multiple concurrent failing calls properly increment failure_count and flip the breaker.

Minimal example unit test snippets (pytest)
- sync success:
```python
import asyncio
from mcp_server.circuit_breaker import CircuitBreaker

def test_call_with_sync_function():
    cb = CircuitBreaker(failure_threshold=3)
    def sync_ok(x): return x*2
    result = asyncio.run(cb.call(sync_ok, 3))
    assert result == 6
```

- async failure and open:
```python
import asyncio
import pytest
from mcp_server.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError

class MyErr(Exception): pass

async def failing():
    raise MyErr("boom")

@pytest.mark.asyncio
async def test_failure_counts_and_open():
    cb = CircuitBreaker(failure_threshold=2, expected_exception=(MyErr,))
    with pytest.raises(MyErr):
        await cb.call(failing)
    with pytest.raises(MyErr):
        await cb.call(failing)
    stats = cb.get_stats()
    assert stats["state"] == "open"
    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(lambda: None)
```

Notes, trade-offs and alternatives
- I preserved the async-first approach (asyncio.Lock, async methods) consistent with the rest of the repo. If you want a purely synchronous API surface, we could implement a synchronous-only circuit breaker using threading.Lock instead, but the codebase is asyncio-centric.
- I added convenience sync wrappers force_open_nowait/force_close_nowait for ease of use from synchronous management scripts; they will schedule tasks on the running loop when available, or run the coroutine in a fresh loop when no loop is running.
- The call() method now supports both sync and async callables — this makes it more flexible and reduces potential misuse.

Would you like me to:
- Open a PR with the above replacement of mcp_server/circuit_breaker.py?
- Add the pytest unit tests I suggested into tests/ so CI can run them?
- Also update any other modules (e.g., base_tool.py) to use the new convenience wrappers where they previously used the sync force_open/force_close?

Tell me which next step you prefer and I’ll produce the patch / PR and test files.

https://github.com/copilot/share/c8111184-0804-8cd5-a900-7e48a46921e2
