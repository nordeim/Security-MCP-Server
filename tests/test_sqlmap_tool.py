"""Regression tests for `SqlmapTool`.

References:
- docs/tool_refactor_todo.md
- docs/tool_tests_todo.md
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from types import SimpleNamespace

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mcp_server.tools.sqlmap_tool import SqlmapTool


@pytest.fixture
def tool(tool_runtime_stub) -> SqlmapTool:
    instance = SqlmapTool()
    return tool_runtime_stub(instance)


@pytest.mark.asyncio
async def test_url_and_batch_required(tool: SqlmapTool, assert_validation_error) -> None:
    inp = SimpleNamespace(
        target="http://192.168.0.5/item?id=1",
        extra_args="",
        timeout_sec=None,
        correlation_id="sqlmap-test",
    )
    output = await tool._execute_tool(inp, None)
    assert_validation_error(output, "requires target URL")


def test_placeholder_payload_restore(tool: SqlmapTool, make_input) -> None:
    payload = "-u http://192.168.0.5/item?id=1&view=detail --batch"
    secured = tool._secure_sqlmap_args(payload)
    restored = tool._parse_and_validate_args(
        secured,
        make_input(target="http://192.168.0.5/item?id=1"),
    )
    assert isinstance(restored, str)
    assert "id=1&view=detail" in restored


def test_risk_level_clamped(tool: SqlmapTool, make_input) -> None:
    secured = tool._secure_sqlmap_args("-u http://192.168.0.5/item?id=1 --batch --risk 5")
    restored = tool._parse_and_validate_args(
        secured,
        make_input(target="http://192.168.0.5/item?id=1"),
    )
    assert isinstance(restored, str)
    tokens = restored.split()
    assert "--risk" in tokens
    assert tokens[tokens.index("--risk") + 1] == str(tool.max_risk_level)


def test_invalid_payload_token_rejected(tool: SqlmapTool, make_input, assert_validation_error) -> None:
    payload = "-u http://192.168.0.5/item?id=1;drop --batch"
    secured = tool._secure_sqlmap_args(payload)
    output = tool._parse_and_validate_args(
        secured,
        make_input(target="http://192.168.0.5/item?id=1"),
    )
    assert_validation_error(output, "Unsupported sqlmap payload token")
