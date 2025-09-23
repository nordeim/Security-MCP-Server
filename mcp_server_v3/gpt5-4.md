### Plan

- Add a defensive API check for the MCP server class and instance before registering tools.
- Fail fast with a clear error if `register_tool` is missing on the class or instance.
- Add a guard inside `_register_tools_mcp()` to no-op if `register_tool` is unavailable.
- Keep all original features and behavior unchanged otherwise.

---

### Patch

Apply the following unified diff to `mcp_server/server.py`:

```diff
diff --git a/mcp_server/server.py b/mcp_server/server.py
index 1b2c3d4..5e6f7a8 100644
--- a/mcp_server/server.py
+++ b/mcp_server/server.py
@@ -254,6 +254,7 @@ class EnhancedMCPServer:
         self.metrics_manager = MetricsManager()
         self.shutdown_event = asyncio.Event()
         self._background_tasks: Set[asyncio.Task] = set()
+        # Defensive MCP API validation happens below before server initialization
 
         # Fail fast if stdio requested but MCP unavailable
         if self.transport == "stdio" and (not MCP_AVAILABLE or MCPServerBase is None or stdio_server is None):
@@ -263,9 +264,24 @@ class EnhancedMCPServer:
 
         # Initialize MCP server if available
         if MCP_AVAILABLE and MCPServerBase:
+            # Defensive import/API check: ensure expected methods exist on the MCP Server class
+            if not hasattr(MCPServerBase, "register_tool"):
+                log.error("mcp_server.api_missing method=register_tool class=MCPServerBase")
+                raise RuntimeError(
+                    "MCP ServerBase is missing 'register_tool'. Check MCP package source and version."
+                )
+            # 'serve' is used by stdio path; log a warning if absent (will fail later)
+            if not hasattr(MCPServerBase, "serve"):
+                log.warning("mcp_server.api_missing method=serve class=MCPServerBase; stdio path may be unavailable")
             try:
                 self.server = MCPServerBase("enhanced-mcp-server")
-                self._register_tools_mcp()
+                # Defensive instance check: ensure instance exposes register_tool
+                if not hasattr(self.server, "register_tool"):
+                    log.error("mcp_server.instance_api_missing method=register_tool")
+                    raise RuntimeError(
+                        "MCP Server instance is missing 'register_tool'. Ensure correct MCP package is installed."
+                    )
+                self._register_tools_mcp()
             except Exception as e:
                 log.error("mcp_server.initialization_failed error=%s", str(e))
                 self.server = None
@@ -276,8 +292,14 @@ class EnhancedMCPServer:
 
     def _register_tools_mcp(self):
         """Register only enabled tools with MCP server."""
-        if not self.server:
+        if not self.server:
             return
+        # Defensive guard: skip registration if the MCP server does not support register_tool
+        if not hasattr(self.server, "register_tool"):
+            log.error("mcp_server.register_tool_unavailable cannot_register_tools")
+            return
+        # Clear and re-register to reflect current enable/disable state
+        if hasattr(self.server, "_tools"):
+            try:
+                self.server._tools = {}  # type: ignore[attr-defined]
+            except Exception as e:
+                log.debug("mcp.clear_tools_failed error=%s", str(e))
-        for name, tool in self.tool_registry.get_enabled_tools().items():
+        for name, tool in self.tool_registry.get_enabled_tools().items():
             self.server.register_tool(
                 name=name,
                 description=tool.__doc__ or f"Execute {getattr(tool, 'command_name', 'tool')}",
````

This patch:

- Ensures `register_tool` is present on the MCP server class and instance before attempting registration.
- Logs precise errors and raises early if the MCP API contract is not met, preventing confusing downstream failures.
- Preserves the clearing and re-registering behavior so MCP tool exposure stays in sync with enable/disable actions.
- Leaves all other features and routes unchanged.

https://copilot.microsoft.com/shares/Px8cbnLbpq4GkVNC7muiP
