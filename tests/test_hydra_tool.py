"""Regression tests for `HydraTool`.

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

from mcp_server.tools.hydra_tool import HydraTool


@pytest.fixture
def tool(monkeypatch: pytest.MonkeyPatch) -> HydraTool:
    instance = HydraTool()
    monkeypatch.setattr("os.path.exists", lambda path: True)
    monkeypatch.setattr("os.path.getsize", lambda path: 1024)
    return instance


def test_placeholder_payload_restoration(tool: HydraTool, make_input) -> None:
    payload = 'http-post-form "/login:username=^USER^&password=^PASS^:F=denied"'
    secured = tool._secure_hydra_args(f"-l admin -P pass.txt {payload} ssh")
    restored = tool._parse_and_validate_args(secured, make_input())
    assert isinstance(restored, str)
    assert "^USER^&password=^PASS^" in restored


def test_missing_auth_injects_defaults(tool: HydraTool) -> None:
    secured = tool._secure_hydra_args("ssh")
    tokens = secured.split()
    assert tokens.count("-l") == 1
    assert tokens.count("admin") == 1
    assert tokens.count("-P") == 1
    assert tokens.count("/usr/share/wordlists/common-passwords.txt") == 1


def test_unauthorized_target_rejected(tool: HydraTool, assert_validation_error) -> None:
    inp = SimpleNamespace(target="8.8.8.8:ssh", extra_args="-l admin -p password", correlation_id="hydra-test")
    output = tool._validate_hydra_requirements(inp)
    assert output is not None
    assert_validation_error(output, "Unauthorized Hydra target")


def test_invalid_payload_character_blocked(tool: HydraTool, make_input, assert_validation_error) -> None:
    payload = 'http-post-form "/login:user;name=bad"'
    secured = tool._secure_hydra_args(f"-l admin -P pass.txt {payload} ssh")
    output = tool._parse_and_validate_args(secured, make_input())
    assert_validation_error(output, "Unsupported hydra payload token")
