### Test script to list tools from the MCP HTTP server

Use this Python script to simulate a simple AI agent querying your MCP server over HTTP, verifying health, listing tools, and optionally executing one. It mirrors the flow an agent would follow: check readiness, discover capabilities, then act.

```python
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
```

---

### How to run

- Ensure the server is up and healthy.
- Save as `mcp_client.py` and run:
  - `python3 mcp_client.py`
- Optional environment:
  - `MCP_BASE_URL` to change server URL (default `http://localhost:8080`)
  - `MCP_TEST_TARGET` for tool target (default `example.com`)
  - `MCP_CLIENT_TIMEOUT`, `MCP_CLIENT_RETRIES` to tune client behavior

---

### Optional: subscribe to events (SSE)

If you want to stream health updates, you can add a basic SSE consumer using `requests`:

```python
def stream_events():
    with requests.get(EVENTS_URL, stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line:
                try:
                    msg = line.decode("utf-8")
                    if msg.startswith("data:"):
                        data = msg[5:].strip()
                        print("[EVENT]", data)
                except Exception as e:
                    print("[EVENT][ERROR]", e)
```

Call `stream_events()` in `main()` if you want to observe live updates.

---

Got it — let’s build you a **minimal MCP stdio client** that behaves like an AI agent talking to your MCP server over the **MCP standard JSON‑RPC via stdin/stdout**.  
This will let you simulate the exact wire‑level interaction an LLM‑powered agent would use when the MCP transport is `stdio`.

---

## **Key points of the stdio MCP protocol**
- Communication is **JSON‑RPC 2.0** messages over stdin/stdout.
- The client sends a `list_tools` request to discover available tools.
- The server responds with a JSON object containing tool metadata.
- You can then send `execute_tool` requests with validated input.

---

## **Drop‑in Python stdio MCP client**

Save this as `mcp_stdio_client.py`:

```python
#!/usr/bin/env python3
import json
import sys
import subprocess
import threading
import uuid

MCP_SERVER_CMD = [
    "docker", "exec", "-i", "mcp-server",
    "python", "-m", "mcp_server.server"
]

def send_message(proc, message):
    """Send a JSON-RPC message to the MCP server."""
    data = json.dumps(message)
    proc.stdin.write(data + "\n")
    proc.stdin.flush()

def read_responses(proc):
    """Read and print responses from the MCP server."""
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            print("[SERVER]", json.dumps(msg, indent=2))
        except json.JSONDecodeError:
            print("[SERVER RAW]", line)

def main():
    # Start MCP server process (stdio mode)
    proc = subprocess.Popen(
        MCP_SERVER_CMD,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Start thread to read responses
    threading.Thread(target=read_responses, args=(proc,), daemon=True).start()

    # 1. Send list_tools request
    list_tools_req = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "list_tools",
        "params": {}
    }
    send_message(proc, list_tools_req)

    # 2. Wait for user to choose a tool
    tool_name = input("Enter tool name to execute: ").strip()

    # 3. Send execute_tool request
    execute_req = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "execute_tool",
        "params": {
            "name": tool_name,
            "input": {
                "target": "example.com",
                "extra_args": "",
                "timeout_sec": 30
            }
        }
    }
    send_message(proc, execute_req)

    # Keep process alive to read responses
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()

if __name__ == "__main__":
    main()
```

---

## **How it works**
1. **Starts** your MCP server in stdio mode inside the container.
2. **Sends** a `list_tools` JSON‑RPC request.
3. **Prints** the server’s response.
4. Lets you **choose a tool** interactively.
5. Sends an `execute_tool` request with a sample target.
6. Prints the execution result.

---

## **Running it**
```bash
python3 mcp_stdio_client.py
```
Make sure your MCP server is configured with:
```env
MCP_SERVER_TRANSPORT=stdio
```
in `.env` so it runs in stdio mode.

---

## **Next steps**
If you want, I can extend this client to:
- Automatically parse the `list_tools` response and pick the first enabled tool.
- Handle streaming outputs/events.
- Wrap it in a reusable class so your LLM agent can call `list_tools()` and `execute_tool()` as Python methods.

Do you want me to evolve this into a **full agent‑friendly MCP client library** so you can plug it straight into your AI workflows? That would make it production‑ready for your stack.

https://copilot.microsoft.com/shares/vMA2ctQP1zfHUAggchR34
