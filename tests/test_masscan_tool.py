"""Regression tests for `MasscanTool`.

References:
- docs/tool_refactor_todo.md
- docs/tool_tests_todo.md
"""
from __future__ import annotations

import logging
import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mcp_server.tools.masscan_tool import MasscanTool


@pytest.fixture
def tool() -> MasscanTool:
    instance = MasscanTool()
    instance.config_max_rate = 500
    instance.allow_intrusive = False
    return instance


def test_rate_clamped_to_config_max(tool: MasscanTool, make_input, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        result = tool._parse_and_validate_args("--rate 10000", make_input())
    assert isinstance(result, str)
    tokens = result.split()
    assert "--rate" in tokens
    assert tokens[tokens.index("--rate") + 1] == "500"
    assert any("masscan.rate_limited" in record.message for record in caplog.records)


@pytest.mark.parametrize(
    "port_spec, expect_error",
    [("80,443", False), ("0", True), ("22-80", False), ("70000", True)],
)
def test_port_spec_validation(tool: MasscanTool, make_input, assert_validation_error, port_spec: str, expect_error: bool) -> None:
    result = tool._parse_and_validate_args(f"-p {port_spec}", make_input())
    if expect_error:
        assert_validation_error(result, "Invalid port specification")
    else:
        assert isinstance(result, str)
        assert port_spec in result


def test_banners_blocked_when_intrusive_disabled(tool: MasscanTool, make_input) -> None:
    result = tool._parse_and_validate_args("--banners", make_input())
    assert isinstance(result, str)
    assert "--banners" not in result.split()

    tool.allow_intrusive = True
    result_intrusive = tool._parse_and_validate_args("--banners", make_input())
    assert "--banners" in result_intrusive.split()


def test_apply_safety_limits_injects_defaults_once(tool: MasscanTool) -> None:
    args = "--rate 500 --wait 2 --retries 1 -p 80"
    output = tool._apply_safety_limits(args)
    tokens = output.split()
    assert tokens.count("--rate") == 1
    assert tokens.count("--wait") == 1
    assert tokens.count("--retries") == 1
    assert tokens.count("-p") == 1
