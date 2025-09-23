#!/usr/bin/env python3
import os
import sys
import json
import time
import uuid
import queue
import threading
import subprocess
from typing import Any, Dict, Optional, Tuple

# Configure how to launch the MCP server in stdio mode.
# Option A: exec inside the running container (recommended for your setup)
MCP_SERVER_CMD = [
    "docker", "exec", "-i", "mcp-server",
    "env", "MCP_SERVER_TRANSPORT=stdio",
    "python", "-m", "mcp_server.server"
]

# Option B: run the image directly (uncomment if you prefer a standalone run)
# MCP_SERVER_CMD = [
#     "docker", "run", "--rm", "-i",
#     "mcp-server:latest",
#     "env", "MCP_SERVER_TRANSPORT=stdio",
#     "python", "-m", "mcp_server.server"
# ]

READ_TIMEOUT_SEC = float(os.getenv("MCP_CLIENT_READ_TIMEOUT", "15"))
REQUEST_TIMEOUT_SEC = float(os.getenv("MCP_CLIENT_REQ_TIMEOUT", "30"))

def gen_id() -> str:
    return str(uuid.uuid4())

class StdioClient:
    def __init__(self, cmd: list[str]):
        self.cmd = cmd
        self.proc: Optional[subprocess.Popen] = None
        self.responses: "dict[str, queue.Queue]" = {}
        self.reader_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self.proc = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1  # line-buffered
        )
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()

    def stop(self) -> None:
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
        except Exception:
            pass

    def _reader_loop(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                print(f"[SERVER RAW] {line}")
                continue

            # Route by id if present, otherwise print
            msg_id = msg.get("id")
            if msg_id:
                with self._lock:
                    q = self.responses.get(msg_id)
                if q:
                    q.put(msg)
                else:
                    print(f"[SERVER UNROUTED] {json.dumps(msg, indent=2)}")
            else:
                print(f"[SERVER EVENT] {json.dumps(msg, indent=2)}")

    def send_request(self, method: str, params: Dict[str, Any]) -> Tuple[str, queue.Queue]:
        assert self.proc and self.proc.stdin
        req_id = gen_id()
        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        data = json.dumps(message)
        with self._lock:
            self.responses[req_id] = queue.Queue()
        self.proc.stdin.write(data + "\n")
        self.proc.stdin.flush()
        return req_id, self.responses[req_id]

    def wait_response(self, req_id: str, q: queue.Queue, timeout_sec: float) -> Dict[str, Any]:
        try:
            msg = q.get(timeout=timeout_sec)
            return msg
        except queue.Empty:
            raise TimeoutError(f"Timed out waiting for response to id={req_id}")

def rpc_ok(msg: Dict[str, Any]) -> bool:
    return "result" in msg and msg.get("jsonrpc") == "2.0"

def print_result(msg: Dict[str, Any]) -> None:
    if rpc_ok(msg):
        print(json.dumps(msg["result"], indent=2))
    elif "error" in msg:
        print(json.dumps(msg["error"], indent=2))
    else:
        print(json.dumps(msg, indent=2))

def main():
    print("[INFO] Starting MCP stdio client")
    client = StdioClient(MCP_SERVER_CMD)
    client.start()
    time.sleep(0.5)  # tiny delay to let the server initialize

    try:
        # 1) list_tools
        print("\n[STEP] list_tools")
        req_id, q = client.send_request("list_tools", {})
        resp = client.wait_response(req_id, q, REQUEST_TIMEOUT_SEC)
        print("[RESP] list_tools ->")
        print_result(resp)

        # Extract tool names safely
        tools = []
        if rpc_ok(resp):
            res = resp["result"]
            # Normalize result shapes: ensure a list of dicts with 'name'
            if isinstance(res, dict) and "tools" in res and isinstance(res["tools"], list):
                tools = [t.get("name") for t in res["tools"] if isinstance(t, dict)]
            elif isinstance(res, list):
                tools = [t.get("name") for t in res if isinstance(t, dict)]
        tools = [t for t in tools if t]

        if not tools:
            print("[WARN] No tools returned by list_tools; ending.")
            return

        print(f"[INFO] Found tools: {tools}")

        # 2) Execute tools in a safe cycle
        # We’ll use benign targets and minimal args to exercise the pipeline without intrusion.
        for name in tools:
            print(f"\n[STEP] execute_tool name={name}")
            # Choose a target based on tool name heuristics (safe defaults)
            if "Gobuster" in name:
                # Gobuster usually needs a mode; we let the server’s validation handle it.
                target = os.getenv("MCP_TEST_GOBUSTER_TARGET", "http://127.0.0.1:8080")
                extra_args = os.getenv("MCP_TEST_GOBUSTER_ARGS", "")
            elif "Masscan" in name:
                # Keep to RFC1918 and low risk params; actual tool may still enforce rate limits.
                target = os.getenv("MCP_TEST_MASSCAN_TARGET", "127.0.0.1")
                extra_args = os.getenv("MCP_TEST_MASSCAN_ARGS", "--ports 80")
            elif "Nmap" in name:
                # Nmap module may be unavailable per earlier logs; handle gracefully.
                target = os.getenv("MCP_TEST_NMAP_TARGET", "127.0.0.1")
                extra_args = os.getenv("MCP_TEST_NMAP_ARGS", "-Pn -p 80")
            else:
                target = os.getenv("MCP_TEST_DEFAULT_TARGET", "127.0.0.1")
                extra_args = os.getenv("MCP_TEST_DEFAULT_ARGS", "")

            params = {
                "name": name,
                "input": {
                    "target": target,
                    "extra_args": extra_args,
                    "timeout_sec": float(os.getenv("MCP_TEST_TIMEOUT_SEC", "30")),
                    "correlation_id": f"client-{uuid.uuid4()}"
                }
            }
            req_id, q = client.send_request("execute_tool", params)
            try:
                resp = client.wait_response(req_id, q, REQUEST_TIMEOUT_SEC)
                print("[RESP] execute_tool ->")
                print_result(resp)
            except TimeoutError as e:
                print(f"[TIMEOUT] execute_tool name={name}: {e}")

        print("\n[INFO] Test cycle complete.")

    finally:
        client.stop()

if __name__ == "__main__":
    main()
