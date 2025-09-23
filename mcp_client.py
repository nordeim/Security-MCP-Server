#!/usr/bin/env python3
import os
import sys
import time
import json
from typing import Any, Dict, List, Optional

import requests

BASE_URL = os.getenv("MCP_BASE_URL", "http://localhost:8080")
HEALTH_URL = f"{BASE_URL}/health"
TOOLS_URL = f"{BASE_URL}/tools"
EXEC_URL = f"{BASE_URL}/tools/{{tool}}/execute"
EVENTS_URL = f"{BASE_URL}/events"  # SSE (optional)
TIMEOUT = float(os.getenv("MCP_CLIENT_TIMEOUT", "10"))
RETRIES = int(os.getenv("MCP_CLIENT_RETRIES", "10"))
SLEEP_BETWEEN = float(os.getenv("MCP_CLIENT_SLEEP", "1.5"))


def check_health() -> Optional[Dict[str, Any]]:
    """Poll /health until healthy or degraded."""
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(HEALTH_URL, timeout=TIMEOUT)
            # Accept 200 (healthy) and 207 (degraded)
            if r.status_code in (200, 207):
                data = r.json()
                print(f"[OK] Health status={data.get('status')} attempt={attempt}")
                return data
            else:
                print(f"[WAIT] Health status_code={r.status_code} attempt={attempt}")
        except requests.RequestException as e:
            print(f"[WAIT] Health request failed attempt={attempt} error={e}")
        time.sleep(SLEEP_BETWEEN)
    return None


def list_tools() -> List[Dict[str, Any]]:
    """GET /tools and return the tool list."""
    r = requests.get(TOOLS_URL, timeout=TIMEOUT)
    r.raise_for_status()
    payload = r.json()
    tools = payload.get("tools", [])
    print(f"[INFO] Tools available: {len(tools)}")
    print(json.dumps(tools, indent=2))
    return tools


def execute_tool(tool_name: str, target: str, extra_args: str = "", timeout_sec: Optional[float] = None):
    """POST /tools/{tool_name}/execute with validated payload."""
    body = {
        "target": target,
        "extra_args": extra_args,
        "timeout_sec": timeout_sec,
        "correlation_id": f"client-{int(time.time())}"
    }
    url = EXEC_URL.format(tool=tool_name)
    r = requests.post(url, json=body, timeout=TIMEOUT)
    if r.status_code == 404:
        print(f"[ERROR] Tool {tool_name} not found")
        return None
    if r.status_code == 403:
        print(f"[ERROR] Tool {tool_name} is disabled")
        return None
    r.raise_for_status()
    result = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
    print(f"[RESULT] {tool_name} ->")
    print(json.dumps(result, indent=2) if isinstance(result, dict) else result)
    return result


def main():
    print(f"[INFO] MCP client targeting {BASE_URL}")

    health = check_health()
    if not health:
        print("[FATAL] Server did not become healthy/degraded within retry window")
        sys.exit(1)

    tools = list_tools()
    if not tools:
        print("[WARN] No tools reported by server")
        return

    # Pick the first enabled tool, or first tool if none marked
    enabled = [t for t in tools if t.get("enabled")]
    chosen = (enabled[0] if enabled else tools[0])["name"]
    print(f"[INFO] Selected tool: {chosen}")

    # Demo: run chosen tool against a benign target (adjust as needed)
    # For network tools, 'example.com' or '127.0.0.1' are safe placeholders.
    execute_tool(tool_name=chosen, target=os.getenv("MCP_TEST_TARGET", "example.com"), extra_args=os.getenv("MCP_TEST_ARGS", ""))


if __name__ == "__main__":
    main()
