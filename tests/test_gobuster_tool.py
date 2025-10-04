"""Regression tests for `GobusterTool`.

References:
- docs/tool_refactor_todo.md
- docs/tool_tests_todo.md
"""
from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mcp_server.base_tool import ToolErrorType
from mcp_server.tools.gobuster_tool import GobusterTool


@pytest.fixture
def tool() -> GobusterTool:
    return GobusterTool()


def test_mode_extraction_and_target_injection(tool: GobusterTool, make_input) -> None:
    inp = make_input(target="http://192.168.0.5")
    tokens = tool._parse_and_validate_args("dir -w /tmp/wordlist.txt", inp)
    assert isinstance(tokens, list)
    mode, remaining = tool._extract_mode_and_args(tokens)
    final_args = tool._ensure_target_argument(mode, remaining, inp.target)
    assert "-u" in final_args
    assert final_args[final_args.index("-u") + 1] == inp.target


def test_dns_mode_rejects_url_target(tool: GobusterTool) -> None:
    output = tool._validate_mode_target_compatibility("dns", "http://192.168.0.5")
    assert output is not None
    assert output.error_type == ToolErrorType.VALIDATION_ERROR.value
    assert "requires domain" in output.stderr


def test_invalid_flag_rejected_by_base_sanitizer(tool: GobusterTool, make_input, assert_validation_error) -> None:
    output = tool._parse_and_validate_args("dir --dangerous", make_input())
    assert_validation_error(output, "Flag not allowed")


def test_optimizer_does_not_duplicate_defaults(tool: GobusterTool) -> None:
    args = tool._optimize_mode_args("dir", ["-q", "--timeout", "10s", "-s", "200"])
    assert args.count("-q") == 1
    assert args.count("--timeout") == 1
    assert args.count("-s") == 1
    assert args.count("-z") == 1
