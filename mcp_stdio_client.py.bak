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
