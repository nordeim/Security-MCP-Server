import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mcp_server.tools.nmap_tool import NmapTool


def run_tool(extra_args: str) -> tuple[NmapTool, str, str]:
    tool = NmapTool()
    validated = tool._parse_and_validate_args(extra_args)  # type: ignore[attr-defined]
    optimized = tool._optimize_nmap_args(validated)
    return tool, validated, optimized


def test_allows_user_os_detection_flag():
    _, validated, optimized = run_tool("-O")
    assert "-O" in validated.split()
    assert "-O" in optimized.split()


def test_optimizer_defaults_are_permitted():
    _, validated, optimized = run_tool("")
    # Validation step should succeed (may return empty string)
    assert validated == ""
    tokens = optimized.split()
    assert "-T4" in tokens
    assert "--max-parallelism" in tokens
    assert "10" in tokens
    assert "-Pn" in tokens
    assert "--top-ports" in tokens
    assert "1000" in tokens


def test_combined_user_and_defaults():
    _, validated, optimized = run_tool("-O --max-parallelism 20")
    validated_tokens = validated.split()
    assert "--max-parallelism" in validated_tokens
    assert "20" in validated_tokens
    assert "-O" in validated_tokens

    optimized_tokens = optimized.split()
    assert optimized_tokens.count("--max-parallelism") == 1
    assert "20" in optimized_tokens
    assert "-O" in optimized_tokens
