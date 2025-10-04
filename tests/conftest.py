"""Shared pytest fixtures for tool regression tests (staging copy).

References:
- docs/tool_tests_todo.md
"""
from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace
from typing import Callable, Iterable, Optional, Protocol

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mcp_server.base_tool import ToolErrorType, ToolOutput  # noqa: E402


class SupportsSpawn(Protocol):
    async def _spawn(self, cmd: Iterable[str], timeout_sec: float) -> ToolOutput: ...


@pytest.fixture
def tool_runtime_stub(monkeypatch: pytest.MonkeyPatch) -> Callable[[SupportsSpawn], SupportsSpawn]:
    """Patch tool execution helpers to avoid invoking real binaries."""

    def _apply(tool: SupportsSpawn) -> SupportsSpawn:
        async def fake_spawn(cmd: Iterable[str], timeout_sec: float) -> ToolOutput:
            return ToolOutput(stdout="stubbed", stderr="", returncode=0)

        monkeypatch.setattr(tool, "_spawn", fake_spawn.__get__(tool, tool.__class__))
        monkeypatch.setattr(tool, "_resolve_command", lambda: "/usr/bin/true")
        return tool

    return _apply


@pytest.fixture
def make_input() -> Callable[[str, Optional[str], str, Optional[float]], SimpleNamespace]:
    """Create lightweight ToolInput substitutes without triggering Pydantic validators."""

    def _factory(
        target: str = "192.168.0.10",
        correlation_id: Optional[str] = None,
        extra_args: str = "",
        timeout_sec: Optional[float] = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            target=target,
            correlation_id=correlation_id or "test-correlation",
            extra_args=extra_args,
            timeout_sec=timeout_sec,
        )

    return _factory


@pytest.fixture
def assert_validation_error() -> Callable[[ToolOutput, Optional[str]], None]:
    """Assertion helper for validation error ToolOutput objects."""

    def _assert(output: ToolOutput, expected_substring: Optional[str] = None) -> None:
        assert isinstance(output, ToolOutput)
        assert output.returncode == 1
        assert output.error_type == ToolErrorType.VALIDATION_ERROR.value
        assert output.stderr
        if expected_substring:
            assert expected_substring in output.stderr

    return _assert
