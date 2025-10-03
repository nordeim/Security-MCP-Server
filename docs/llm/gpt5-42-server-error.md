Jeremiah — I’ve gone through the full `server.py` in context and here’s the deep‑dive on what’s really happening in `run_http_enhanced()` and why your container is still tripping the `"FastAPI and Uvicorn are required for HTTP transport"` RuntimeError.

---

## **1. How the dependency check works**
At the very top of `server.py` (outside this snippet), there are module‑level constants:

```python
try:
    import fastapi
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

try:
    import uvicorn
    UVICORN_AVAILABLE = True
except ImportError:
    UVICORN_AVAILABLE = False
```

These are evaluated **once at import time** when the module is first loaded — **before** your entrypoint runs its own import test.

If either of those imports fails at that moment, the boolean stays `False` for the lifetime of the process. Later, in `run_http_enhanced()`:

```python
if not FASTAPI_AVAILABLE or not UVICORN_AVAILABLE:
    log.error("enhanced_server.http_missing_deps")
    raise RuntimeError("FastAPI and Uvicorn are required for HTTP transport")
```

…it doesn’t re‑try the import. It just checks the cached booleans.

---

## **2. Why this can fail even though the packages are installed**
- If the module is imported **before** `/opt/venv/bin` is in `PATH` or before `VIRTUAL_ENV` is set, Python will use the system interpreter’s site‑packages, not the venv.  
  → In your container, the image’s `PATH` is correct, but if something imports `server.py` before the venv is active, those imports can fail.
- If the override file or dev mounts shadow `/app/mcp_server` with host code, the import may happen in a different environment.
- If there’s a transient ImportError (e.g., missing sub‑dependency at build time), the flag stays `False` even if later the package is available.

---

## **3. How to fix it robustly**
You want the HTTP transport check to run **at method call time**, not rely on a stale module‑level flag.

### Patch:
Replace the top‑level constants with a function:

```python
def _check_http_deps():
    import importlib
    missing = []
    for mod in ("fastapi", "uvicorn"):
        try:
            importlib.import_module(mod)
        except Exception as e:
            log.error("enhanced_server.http_dep_error mod=%s err=%s", mod, e)
            missing.append(mod)
    return missing
```

Then in `run_http_enhanced()`:

```python
missing = _check_http_deps()
if missing:
    raise RuntimeError(f"FastAPI and Uvicorn are required for HTTP transport; missing={missing}")
```

This way, even if the module was imported early in a bad environment, it will re‑check with the correct interpreter and venv.

---

## **4. Additional guardrails**
- Ensure your Dockerfile sets:
  ```dockerfile
  ENV PATH="/opt/venv/bin:$PATH" VIRTUAL_ENV="/opt/venv"
  ```
  **before** any Python imports happen.
- Avoid mounting `./mcp_server` over `/app/mcp_server` unless you’re actively developing — it can shadow the packaged code and change import timing.
- If you need dev mounts, keep the safe override we built (no `command:` override, read‑only mounts) so `/entrypoint.sh` runs and sets up the environment before imports.

---

## **5. Why this matches your logs**
Your entrypoint’s inline Python check passes (`HTTP deps present`) because it runs after venv activation.  
But `server.py` was imported earlier in the process (possibly by another module in the stack) before that activation, so `FASTAPI_AVAILABLE` or `UVICORN_AVAILABLE` was set to `False`.  
When `run_http_enhanced()` checks those flags, it sees `False` and raises.

---

## **6. Recommended next step**
- Patch `server.py` to re‑check imports at runtime as above.
- Rebuild the image and run without the dev override to confirm the container starts and stays healthy.
- Once stable, re‑introduce the safe override for development.

If you want, I can give you the exact diff to apply to `server.py` so it’s a drop‑in change — no other parts of the app need to be touched, and it will eliminate this false “missing deps” error permanently. Would you like me to prepare that?

https://copilot.microsoft.com/shares/rUjsfFkACSW7L4pqSZFeV
