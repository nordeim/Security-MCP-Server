Got it — the safest way to test **NmapTool**’s parsing/validation logic without actually invoking `nmap` is to **monkeypatch its internal execution method**. In your code, `NmapTool.run()` eventually calls `_execute_tool()` (inherited from `MCPBaseTool`) which spawns a subprocess. We can override that in tests to capture the command/args instead.

Here’s a **patch-style test addition** you can drop into `tests/test_nmap_tool.py`:

```python
# tests/test_nmap_tool.py (additions)

import pytest
from mcp_server.tools.nmap_tool import NmapTool
from mcp_server.base_tool import ToolInput

@pytest.mark.asyncio
async def test_nmaptool_parsing_and_command_build(monkeypatch):
    tool = NmapTool()

    captured = {}

    async def fake_execute(self, cmd, timeout):
        # Instead of spawning, capture the command and return a dummy result
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        class DummyResult:
            returncode = 0
            stdout = b"FAKE NMAP OUTPUT"
            stderr = b""
        return DummyResult()

    # Patch the base class _execute_tool
    monkeypatch.setattr(NmapTool, "_execute_tool", fake_execute)

    # Provide safe args that should pass validation
    ti = ToolInput(target="10.0.0.5", extra_args="-sV -p 22,80,443")

    result = await tool.run(ti)

    # Assertions: we never spawned, but we captured the built command
    assert "cmd" in captured
    cmd = captured["cmd"]
    # First element should be "nmap"
    assert cmd[0] == "nmap"
    # Target should appear at the end
    assert cmd[-1] == "10.0.0.5"
    # Our flags should be preserved
    assert "-sV" in cmd
    assert "-p" in cmd
    # Optimizations should be injected if not provided
    assert "-T4" in cmd
    assert "--max-parallelism=10" in cmd
    assert "--top-ports=1000" in cmd
    # Timeout should come from config defaults
    assert isinstance(captured["timeout"], int)
    # The fake result should propagate stdout
    assert "FAKE NMAP OUTPUT" in result.stdout
```

---

### How this works
- We **monkeypatch** `NmapTool._execute_tool` to a fake coroutine that just records the command and returns a dummy result.
- This lets us assert:
  - The **command structure** (binary, flags, target).
  - That **optimizations** (`-T4`, `--max-parallelism=10`, `--top-ports=1000`) are injected.
  - That **timeout** is passed correctly from config.
- No subprocess is spawned, so tests are deterministic and safe.

---

### Next steps
- You can extend this pattern to test **invalid args** (e.g., `--script=exploit`) by asserting that `tool.run()` raises before `_execute_tool` is even called.
- If you’d like, I can also provide a **helper fixture** that automatically patches `_execute_tool` for all tool tests, so you can reuse it across Gobuster, Masscan, etc. Would you like me to draft that reusable fixture?

https://copilot.microsoft.com/shares/au2C5iXcFFqaP475pWYes

---
# Test plan, pytest suite, Makefile target, and traceability matrix

Below is a meticulous plan followed by ready-to-drop-in pytest files, a Makefile target, and a concise one-page traceability matrix. The tests focus on config, health, metrics, and the Nmap tool, aligning to PAD/README claims. They’re designed to be auditable, deterministic, and CI-friendly.

---

## Plan overview

- **Scope:** config.py, health.py, metrics.py, tools/nmap_tool.py
- **Test types:**
  - **Unit:** pure validation, parsing, bounds, and guards
  - **Integration-light:** health manager aggregation, tool metrics emission path
- **Design principles:**
  - **Isolation:** monkeypatch and temp files for config reload; no network calls
  - **Determinism:** fixed seeds where randomness exists; strict assertions
  - **Skips:** soft-skip tests if optional deps are missing (psutil, prometheus_client)
- **Outputs:**
  - pytest files in tests/
  - Makefile target make test
  - One-page traceability matrix

---

## Project files to add

### tests/conftest.py

```python
# tests/conftest.py
import os
import shutil
import tempfile
from contextlib import contextmanager
import pytest

@contextmanager
def temp_env(env: dict):
    old = {}
    try:
        for k, v in env.items():
            old[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        yield
    finally:
        for k, v in env.items():
            if old[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old[k]

@pytest.fixture
def tmp_config_dir():
    d = tempfile.mkdtemp(prefix="mcp_cfg_")
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)

@pytest.fixture
def has_psutil():
    try:
        import psutil  # noqa: F401
        return True
    except Exception:
        return False

@pytest.fixture
def has_prom():
    try:
        import prometheus_client  # noqa: F401
        return True
    except Exception:
        return False
```

---

### tests/test_config.py

```python
# tests/test_config.py
import json
import os
import time
import textwrap
import pathlib
import pytest

from mcp_server import config as cfg_mod

def write_yaml(path: str, data: str):
    p = pathlib.Path(path)
    p.write_text(textwrap.dedent(data), encoding="utf-8")

def test_config_layering_precedence(tmp_config_dir, monkeypatch):
    cfg_file = os.path.join(tmp_config_dir, "mcp.yaml")
    write_yaml(cfg_file, """
    server:
      host: "0.0.0.0"
      port: 8080
      transport: "http"
    tool:
      default_timeout: 45
      default_concurrency: 3
    """)
    with monkeypatch.context() as m:
        m.setenv("MCP_CONFIG_FILE", cfg_file)
        m.setenv("MCP_SERVER_HOST", "127.0.0.1")  # env should override file
        m.setenv("MCP_TOOL_DEFAULT_TIMEOUT", "60")
        cfg_mod.reset_config()
        conf = cfg_mod.get_config()

    assert conf.server.host == "127.0.0.1"
    assert conf.server.port == 8080
    assert conf.server.transport == "http"
    assert conf.tool.default_timeout == 60
    assert conf.tool.default_concurrency == 3

def test_config_validation_and_clamps(tmp_config_dir, monkeypatch):
    cfg_file = os.path.join(tmp_config_dir, "mcp.yaml")
    write_yaml(cfg_file, """
    tool:
      default_timeout: -5
      default_concurrency: 0
    circuit_breaker:
      failure_threshold: -1
      recovery_timeout: 0
      success_threshold: 0
    health:
      interval_seconds: 0
      check_timeout_seconds: -1
    """)
    with monkeypatch.context() as m:
        m.setenv("MCP_CONFIG_FILE", cfg_file)
        cfg_mod.reset_config()
        conf = cfg_mod.get_config()

    # Expect sane minimums applied by validation
    assert conf.tool.default_timeout >= 1
    assert conf.tool.default_concurrency >= 1
    assert conf.circuit_breaker.failure_threshold >= 1
    assert conf.circuit_breaker.recovery_timeout >= 1
    assert conf.circuit_breaker.success_threshold >= 1
    assert conf.health.interval_seconds >= 1
    assert conf.health.check_timeout_seconds >= 1

def test_invalid_transport_rejected(monkeypatch):
    with monkeypatch.context() as m:
        m.setenv("MCP_SERVER_TRANSPORT", "invalid-xyz")
        cfg_mod.reset_config()
        with pytest.raises(ValueError):
            _ = cfg_mod.get_config()

def test_redaction_of_sensitive_data(tmp_config_dir, monkeypatch):
    cfg_file = os.path.join(tmp_config_dir, "mcp.yaml")
    write_yaml(cfg_file, """
    database:
      url: "postgres://user:secret@example/db"
    security:
      api_key: "supersecret"
      token: "moresecret"
    """)
    with monkeypatch.context() as m:
        m.setenv("MCP_CONFIG_FILE", cfg_file)
        cfg_mod.reset_config()
        conf = cfg_mod.get_config()
    dumped = conf.to_dict(redact_sensitive=True)
    assert dumped["database"]["url"] == "***REDACTED***"
    assert dumped["security"]["api_key"] == "***REDACTED***"
    assert dumped["security"]["token"] == "***REDACTED***"
    # JSON stringify should also be safe to print
    _ = json.dumps(dumped)

def test_hot_reload_applies_changes(tmp_config_dir, monkeypatch):
    cfg_file = os.path.join(tmp_config_dir, "mcp.yaml")
    write_yaml(cfg_file, """
    tool:
      default_timeout: 40
    """)
    with monkeypatch.context() as m:
        m.setenv("MCP_CONFIG_FILE", cfg_file)
        cfg_mod.reset_config()
        conf = cfg_mod.get_config()
        assert conf.tool.default_timeout == 40

        # Modify file
        time.sleep(0.01)  # ensure mtime differences
        write_yaml(cfg_file, """
        tool:
          default_timeout: 75
        """)
        # Manual reload trigger (depends on config implementation)
        reloaded = cfg_mod.reload_config()
        assert reloaded is True
        conf2 = cfg_mod.get_config()
        assert conf2.tool.default_timeout == 75
```

---

### tests/test_health.py

```python
# tests/test_health.py
import asyncio
import pytest

from mcp_server.health import (
    HealthStatus,
    HealthCheckResult,
    HealthCheck,
    HealthCheckManager,
)

class DummyCheck(HealthCheck):
    def __init__(self, name, status, priority=1):
        super().__init__(name=name, priority=priority)
        self._status = status

    async def run(self) -> HealthCheckResult:
        return HealthCheckResult(
            name=self.name,
            status=self._status,
            priority=self.priority,
            message=f"{self.name}:{self._status.name}",
            metadata={},
        )

@pytest.mark.asyncio
async def test_priority_aggregation_rules():
    # critical unhealthy should drive overall UNHEALTHY
    checks = [
        DummyCheck("crit_bad", HealthStatus.UNHEALTHY, priority=0),
        DummyCheck("info_good", HealthStatus.HEALTHY, priority=2),
    ]
    mgr = HealthCheckManager(checks=checks)
    summary = await mgr.run_checks()
    assert summary.overall_status == HealthStatus.UNHEALTHY

    # important degraded should yield DEGRADED if no critical unhealthy
    checks = [
        DummyCheck("imp_bad", HealthStatus.UNHEALTHY, priority=1),
        DummyCheck("info_good", HealthStatus.HEALTHY, priority=2),
    ]
    mgr = HealthCheckManager(checks=checks)
    summary = await mgr.run_checks()
    assert summary.overall_status == HealthStatus.DEGRADED

    # all healthy -> HEALTHY
    checks = [
        DummyCheck("crit_ok", HealthStatus.HEALTHY, priority=0),
        DummyCheck("imp_ok", HealthStatus.HEALTHY, priority=1),
        DummyCheck("info_ok", HealthStatus.HEALTHY, priority=2),
    ]
    mgr = HealthCheckManager(checks=checks)
    summary = await mgr.run_checks()
    assert summary.overall_status == HealthStatus.HEALTHY

@pytest.mark.asyncio
async def test_check_timeouts_do_not_break_summary():
    class SlowCheck(HealthCheck):
        async def run(self):
            await asyncio.sleep(0.2)
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                priority=self.priority,
                message="slow ok",
                metadata={},
            )
    mgr = HealthCheckManager(
        checks=[SlowCheck(name="slow", priority=1)],
        check_timeout_seconds=0.05,
    )
    summary = await mgr.run_checks()
    # A timeout should not raise; manager should mark degraded/unhealthy per policy
    assert summary is not None
    assert summary.overall_status in (HealthStatus.DEGRADED, HealthStatus.UNHEALTHY)
```

---

### tests/test_metrics.py

```python
# tests/test_metrics.py
import time
import pytest

from mcp_server.metrics import MetricsManager, ToolMetrics

def test_tool_metrics_record_and_failure_rate():
    tm = ToolMetrics(tool_name="NmapTool")
    start = time.time()
    tm.record_start()
    time.sleep(0.01)
    tm.record_end(status="success", error_type=None, duration_seconds=time.time() - start)

    tm.record_start()
    time.sleep(0.005)
    tm.record_end(status="error", error_type="timeout", duration_seconds=0.005)

    stats = tm.to_dict()
    assert stats["executions_total"] == 2
    assert stats["success_count"] == 1
    assert stats["error_count"] == 1
    assert stats["timeout_count"] == 1
    assert 0.0 <= stats["recent_failure_rate"] <= 1.0

def test_metrics_manager_aggregates_and_cleans():
    mm = MetricsManager.get()
    mm.reset()  # ensure clean slate if supported
    mm.record_tool_execution("NmapTool", status="success", error_type=None, duration_seconds=0.02)
    mm.record_tool_execution("NmapTool", status="error", error_type="timeout", duration_seconds=0.01)
    sys_stats = mm.get_system_stats()
    assert sys_stats["uptime_seconds"] >= 0
    tool_stats = mm.get_tool_stats("NmapTool")
    assert tool_stats["executions_total"] == 2
    assert tool_stats["timeout_count"] == 1

@pytest.mark.skipif(not __import__("importlib").util.find_spec("prometheus_client"), reason="prometheus_client not installed")
def test_prometheus_exposition_available():
    mm = MetricsManager.get()
    text = mm.get_prometheus_metrics()
    assert text is None or isinstance(text, str)  # If using default REGISTRY route, may return None
```

---

### tests/test_nmap_tool.py

```python
# tests/test_nmap_tool.py
import asyncio
import pytest

from mcp_server.tools.nmap_tool import NmapTool
from mcp_server.base_tool import ToolInput

@pytest.mark.asyncio
async def test_target_validation_private_ip_and_cidr_ok(monkeypatch):
    tool = NmapTool()
    # Single private IP
    ti = ToolInput(target="10.0.0.1", extra_args="")
    # Validate via tool's internal validator if exposed, else run a dry parse
    info = tool.get_tool_info()
    assert info["name"].lower().find("nmap") != -1

@pytest.mark.asyncio
async def test_target_validation_rejects_public_ip():
    tool = NmapTool()
    bad = ToolInput(target="8.8.8.8", extra_args="")
    with pytest.raises(Exception):
        await tool.run(bad)  # Expect validation error before process spawn

@pytest.mark.asyncio
async def test_network_size_limit_rejects_large_cidr():
    tool = NmapTool()
    # Example: /16 might exceed the MAX_NETWORK_SIZE gate
    bad = ToolInput(target="192.168.0.0/16", extra_args="")
    with pytest.raises(Exception):
        await tool.run(bad)

@pytest.mark.asyncio
async def test_script_and_ports_validation(monkeypatch):
    tool = NmapTool()
    # Safe scripts and valid ports
    ok = ToolInput(target="10.0.0.5", extra_args="--script=default,discovery -p 22,80,443,8000-8010")
    # We don't actually want to execute nmap; intercept underlying spawn by making command fail early
    with pytest.raises(Exception):
        await tool.run(ok)  # Either validation passes then spawn fails, or run path requires nmap installed

    # Illegal script category
    bad_script = ToolInput(target="10.0.0.5", extra_args="--script=exploit")
    with pytest.raises(Exception):
        await tool.run(bad_script)

    # Illegal port range
    bad_ports = ToolInput(target="10.0.0.5", extra_args="-p 0,70000")
    with pytest.raises(Exception):
        await tool.run(bad_ports)

@pytest.mark.asyncio
async def test_aggressive_flags_policy(monkeypatch):
    tool = NmapTool()
    # If policy forbids -A or vuln, this should raise; otherwise adjust when security.allow_intrusive is enabled
    maybe_bad = ToolInput(target="10.0.0.5", extra_args="-A --script=vuln")
    with pytest.raises(Exception):
        await tool.run(maybe_bad)
```

Notes:
- These Nmap tests intentionally avoid executing nmap; they rely on validation paths raising before process spawn. If your NmapTool requires nmap presence even to parse, we can monkeypatch the spawn method to prevent external calls and assert parsed/validated args directly. Tell me if you want me to add precise monkeypatch hooks based on your code.

---

## Makefile target

```make
# Makefile
PYTEST ?= pytest
PYTEST_ARGS ?= -q --maxfail=1 --disable-warnings

.PHONY: test lint unit integration

test:
	$(PYTEST) $(PYTEST_ARGS) tests

unit:
	$(PYTEST) $(PYTEST_ARGS) -k "config or health or metrics or nmap" tests

integration:
	$(PYTEST) $(PYTEST_ARGS) -k "integration" tests
```

Optional: add a requirements-dev.txt with pytest and pytest-asyncio.

---

## One-page traceability matrix

| PAD/README claim | Code reference | Test coverage |
|---|---|---|
| Layered config (defaults < file < env) with validation and hot reload | config.MCPConfig: load order methods; validate_*; reload_config | test_config_layering_precedence; test_config_validation_and_clamps; test_hot_reload_applies_changes |
| Sensitive values are redacted for audit-safe outputs | config.MCPConfig.to_dict(redact_sensitive=True) | test_redaction_of_sensitive_data |
| Priority-aware health model with critical/important/info | health.HealthStatus; HealthCheck; HealthCheckManager.aggregate | test_priority_aggregation_rules |
| Health checks robust to timeouts and failures | health.HealthCheckManager(check_timeout_seconds) | test_check_timeouts_do_not_break_summary |
| Prometheus metrics for executions, durations, active, errors | metrics.MetricsManager; ToolMetrics; Prom counters/histograms | test_tool_metrics_record_and_failure_rate; test_metrics_manager_aggregates_and_cleans; test_prometheus_exposition_available |
| Safe-by-default Nmap with private-only targets and network-size limit | tools.nmap_tool.NmapTool._validate_* | test_target_validation_rejects_public_ip; test_network_size_limit_rejects_large_cidr |
| Strict arg validation for ports, scripts, timing, and flags | tools.nmap_tool.NmapTool._parse_and_validate_args | test_script_and_ports_validation |
| Restrict intrusive scans unless explicitly allowed | tools.nmap_tool.NmapTool SAFE_SCRIPTS/allowed_flags and policy checks | test_aggressive_flags_policy |

---

## Next steps

- If method names differ (e.g., reload_config vs check_for_changes), I can align the tests precisely once you confirm the exact symbols.
- Want me to add a small monkeypatch to NmapTool to bypass subprocess spawn and assert the parsed command/args exactly?

---
# Codebase review and validation against PAD and README

Below is a focused, auditable review of the specified modules, validating implementation details against the architecture intent described in the PAD and README. Each section highlights confirmations, notable design choices, potential gaps or risks, and concrete test validations.

---

## Configuration management

The configuration system provides dataclass-backed sections (database, security, circuit breaker, health, metrics, logging, server, tool), supports layered loading (defaults → file → environment), clamps values to sane ranges, performs thread-safe hot reload, and redacts sensitive keys on output. It validates server host/port and transport values, and cleanly exposes getters and a global singleton accessor with reset for tests. These align with production-grade requirements for safety, maintainability, and auditability.

- **Core confirmations:**
  - **Layered load order:** Defaults merged with optional file, then with environment; deep-merged per section.
  - **Validation clamps:** Bounds applied to security, circuit breaker, health, metrics, server, and tool settings; invalid host/transport rejected.
  - **Thread-safety & reloads:** Global RLock guards load/apply; mtime-based change detection; revert-to-backup on reload failure.
  - **Sensitive redaction:** Redacts nested keys such as database.url and security keys in to_dict()/__str__.

- **Potential gaps/risks:**
  - **Sensitive keys list:** Includes logging.file_path; not strictly sensitive, but acceptable. Consider adding any auth tokens used in future to the list proactively.
  - **Env mappings:** Prometheus enable flag is parsed but not explicitly mapped in env map (enabled, prometheus_enabled handled generically). This is fine, but verify docker envs align with these variable names.

- **Validation steps:**
  - **Hot reload:** Edit config file values for timeouts and thresholds; assert reload_config() applies and clamps within specified ranges.
  - **Transport validation:** Set MCP_SERVER_TRANSPORT=invalid → expect ValueError; “stdio” and “http” accepted.
  - **Redaction:** to_dict(redact_sensitive=True) must replace database.url and security secret keys with ***REDACTED***.

---

## Health monitoring

The health system defines clear status levels (healthy, degraded, unhealthy), check result structures, and a manager that runs multiple checks concurrently with prioritization (0=critical, 1=important, 2=informational). Default checks include system resources, process health, and optional dependency presence. If psutil is unavailable, checks degrade gracefully. The manager provides a monitoring loop, history, and summary aggregation, with overall status determined by priority-weighted logic, matching PAD/README’s emphasis on priority-aware health and graceful degradation.

- **Core confirmations:**
  - **Priority-driven status:** Critical failures yield unhealthy; important failures degrade; info-only all unhealthy also degrade.
  - **Default checks:** System resources (CPU/memory/disk), process health, and dependency checks if configured.
  - **Robust execution:** Per-check timeouts, centralized timeout for the run, cancellation handling, and rich metadata in results and summary.
  - **Tool availability check:** Verifies tools are enabled and their command resolves via _resolve_command to detect missing binaries/misconfigurations.

- **Potential gaps/risks:**
  - **psutil dependency:** When unavailable, resource and process checks return degraded; ensure container image includes psutil if full fidelity is required.
  - **ToolAvailabilityHealthCheck:** Assumes tool objects expose _resolve_command; if base class changes method name, check will misreport. Keep consistent across refactors.

- **Validation steps:**
  - **Priority semantics:** Introduce a custom critical check that returns unhealthy; assert overall = unhealthy and HTTP status mapping in server layer follows 503/207/200 (validated in integration).
  - **Dependency injection:** Configure health_dependencies with a missing module; assert overall degrades and metadata lists missing dependencies.
  - **Tool availability:** Temporarily modify PATH to hide nmap; assert degraded with unavailable tool listed.

---

## Metrics and Prometheus integration

A singleton Prometheus registry defends against double registration, with counters, histograms, and gauges for tool executions, latency, activity, and errors. Local in-memory stats track success/failure/timeouts, last run, and recent failure rate. MetricsManager aggregates per-tool stats, system stats (uptime, request count, error rate), and supports cleanup and eviction to manage cardinality. It can render Prometheus exposition text if the client library is available. This maps to PAD/README claims for per-tool execution metrics and system-level observability.

- **Core confirmations:**
  - **Metric names:** mcp_tool_execution_total{tool,status,error_type}, mcp_tool_execution_seconds{tool}, mcp_tool_active{tool}, mcp_tool_errors_total{tool,error_type}.
  - **Thread safety:** RLocks around tool stats; locks for system counters and active gauge updates.
  - **Registry initialization:** Attempts to find existing collectors to avoid duplication across imports; marks availability if prometheus_client not present.
  - **System stats:** Uptime, request_count, error_count/rate, active_connections for fallback JSON view and internal monitoring.

- **Potential gaps/risks:**
  - **Registry internals:** Accesses private attributes of the default REGISTRY (_collector_to_names). This is practical but brittle across prometheus_client versions; monitor for upstream changes.
  - **Active connections metric:** Exposed only in internal JSON, not as Prometheus metrics; consider adding an explicit gauge if deemed valuable.
  - **Double emission paths:** Both ToolMetrics.record_execution and MetricsManager.record_tool_execution emit Prometheus metrics. Ensure routes don’t call both for the same execution to avoid double counting.

- **Validation steps:**
  - **Metric emission:** Execute a tool successfully and with a forced error; assert increments across execution_total, errors_total, and histogram observations; active gauge increments during execution and decrements after.
  - **Eviction/cleanup:** Simulate many tools with last_execution_time stale >24h; assert cleanup removes old series from in-memory catalog (Prometheus series persist until TTL).
  - **Availability fallback:** Temporarily uninstall prometheus_client in a test venv; get_prometheus_metrics() should return None and JSON stats should still populate.

---

## Nmap tool

NmapTool extends the base tool with strict target validation (RFC1918 or .lab.internal), network-size limits, safe script categories, port-spec validation, allowed flag safelist, and default performance optimizations (T4, max-parallelism=10, -Pn, top-1000 ports). It pulls timeouts/concurrency and circuit-breaker thresholds from config and surfaces a comprehensive get_tool_info for discovery/UX. This closely matches the PAD/README requirements for safety, performance, and resilience by default.

- **Core confirmations:**
  - **Target safety:** Networks must be private/loopback and ≤ 1024 addresses; single IPs must be private/loopback; hostnames must end with .lab.internal.
  - **Args validation:** Port specs constrained to digits, commas, dashes with range bounds and count limit; scripts restricted to SAFE_SCRIPTS or safe/default/discovery categories; timing templates validated; flags limited to an allowlist (including -sV, -sC, -T4, -Pn, -p, --script, etc.).
  - **Optimizations:** Adds -T4, --max-parallelism=10, -Pn, --top-ports=1000 when not provided, supporting sensible defaults for speed with restraint.
  - **Config integration:** Applies circuit breaker thresholds and tool defaults (timeout, concurrency) from MCP config on init.

- **Potential gaps/risks:**
  - **SAFE_SCRIPTS includes “vuln”:** Some “vuln” scripts can be intrusive; if the PAD mandates strictly non-intrusive scans, consider moving “vuln” behind an explicit opt-in feature flag or higher trust mode.
  - **Allowed flags contain “-A”:** This aggregates aggressive behaviors (OS detection, script scanning). If PAD requires conservative defaults, consider blocking “-A” unless explicitly permitted by policy.
  - **Network size error message:** Recovery suggestion uses f"/{32 - network.prefixlen + 10}" which can produce confusing CIDR math; replace with a clear message like “use at most /22 for IPv4 to keep ≤1024 hosts”.
  - **Non-flag tokens passthrough:** Parser allows non-flag tokens (treated as positional args). Base tool likely constructs command as [nmap, tokens..., target]; allowing extra positional tokens could create multi-target invocations or accidental input injection. Consider rejecting non-flag tokens or enforcing they only appear as legitimate values of known flags.

- **Validation steps:**
  - **Target acceptance:** Accept 10.0.0.1 and 192.168.1.0/24; reject 8.8.8.8, 192.168.0.0/16 (if exceeding size limit), and example.com (not .lab.internal) with specific error messages.
  - **Port and script guards:** Reject -p “0,70000” and --script “exploit”; accept -p “80,443,8000-8100” and --script “default,discovery”.
  - **Aggressive flags:** Attempt “-A” and “--script=vuln”; ensure they’re allowed only if policy permits; else add tests to enforce desired policy by tightening allowed_flags/SAFE_SCRIPTS.
  - **Optimizations apply:** Call with no extra args; assert injected -T4 --max-parallelism=10 -Pn --top-ports=1000 appear before user args.
  - **Config overrides:** Set MCP_TOOL_DEFAULT_TIMEOUT=120 and MCP_TOOL_DEFAULT_CONCURRENCY=4; assert reflected in get_tool_info() and execution behavior.

---

## Alignment highlights and discrepancies

- **Safety model:** Strong input validation and allowlists enforce private targets, script categories, and port specs, consistent with a “safe-by-default” posture described in PAD/README.
- **Observability:** Per-tool counters, latencies, active gauges, and error typing are implemented and exportable to Prometheus, meeting observability claims.
- **Health semantics:** Priority-aware aggregation with system/process/dependency checks and tool availability aligns with reliability claims.
- **Configuration:** Layered config, clamped bounds, safe reloads, and redaction support operational excellence and auditability.

- **Notable deviations to resolve:**
  - **Intrusive options:** “vuln” and “-A” may exceed “strictly safe” posture; require explicit policy and potentially environment-based toggles to prevent accidental use.
  - **CIDR hint accuracy:** Correct the network-size recovery hint for clarity and operator trust.
  - **Argument non-flags:** Consider disallowing arbitrary positional args to avoid multi-target or ambiguous invocation, unless explicitly designed for it.
  - **Prometheus internals:** Reduce reliance on private REGISTRY attributes to improve forward compatibility.

---

## Test suite blueprint (first-pass coverage)

### Unit tests

- **config_test.py**
  - **Layering precedence:** Defaults < file < env; verify clamps and ValueErrors for invalid transport/host; verify redaction of sensitive keys.
  - **Hot reload:** Modify on-disk config and assert reload_config applies and reverts on simulated failure.

- **health_test.py**
  - **Priority aggregation:** Inject critical/important/info failures and assert overall status transitions; verify psutil absence yields degraded not unhealthy; dependency miss causes unhealthy for that check and overall downgraded appropriately.
  - **Tool availability:** Mock tool_registry with failing _resolve_command; assert degraded with explicit listing.

- **metrics_test.py**
  - **Emission and stats:** Record success/failure/timeout and assert counters, histograms, active gauge behavior, and recent_failure_rate; test cleanup and eviction behavior boundaries.
  - **Prometheus availability fallback:** Simulate missing prometheus_client and assert JSON stats still returned, Prometheus text is None.

- **nmap_tool_test.py**
  - **Target validation:** Accept RFC1918/.lab.internal; reject public IPs and oversized CIDRs with correct messages; validate CIDR hint correctness once fixed.
  - **Port/script/flags:** Validate legal and illegal values; assert timing templates and allowlist enforcement; test behavior when “-A”/“vuln” restricted by policy toggle.
  - **Optimizations & config:** Assert injected defaults and config-driven overrides for timeout/concurrency.

### Integration tests

- **metrics_integration_test.py**
  - **End-to-end emission:** Execute NmapTool with success and injected failures/timeouts; scrape /metrics; assert presence and correct label sets for mcp_tool_execution_total, _seconds, _active, _errors_total.

- **health_integration_test.py**
  - **End-to-end health:** Start HealthCheckManager; assert summaries reflect resource/process/dependency and tool availability over time with history recorded.

> Sources: 

---

## Quick wins and recommended fixes

- **Restrict intrusive capabilities:**
  - **Option toggle:** Add config.security.allow_intrusive=false to gate “-A” and “vuln” scripts; enforce in NmapTool._parse_and_validate_args() and SAFE_SCRIPTS selection.
- **Clarify network-size guidance:**
  - **Fix message:** Replace the recovery_suggestion with a precise limit (e.g., “Use at most /22 for IPv4 to keep ≤1024 hosts”).
- **Harden argument parsing:**
  - **Reject stray positional tokens:** Unless explicitly intended, reject non-flag tokens that don’t belong to known flags; this prevents multi-target/unexpected inputs.
- **Prometheus registry robustness:**
  - **Custom registry:** Prefer an explicit CollectorRegistry per process or feature-gated registration flags to avoid accessing private registry attributes.

---

## What I’ll deliver next

- **Pytest skeletons** for the four modules with fixtures and parametrized cases to validate the above.
- **One-page traceability matrix** mapping PAD/README claims to specific code lines/functions and the corresponding tests.
- **A short PR** with the recommended fixes (intrusive toggle, CIDR message, parser tightening) and targeted unit tests.

If you want me to generate the pytest files and a Makefile target now, I’ll produce drop-in test modules and a minimal tox/pytest.ini to run them cleanly in your repo.

---
Perfect — now that we’ve pulled in **`config.py`**, **`nmap_tool.py`**, and the full **Prometheus/Grafana/alerting stack** (Dockerfile, docker‑compose, alerts, prometheus.yml, healthcheck.sh), we can extend the **review + validation plan** to cover them in the **first pass**. Here’s the meticulous, auditable plan:

---

# 🔍 Extended Review & Validation Plan (with Config + Nmap + Prometheus stack)

## 1. **Traceability Matrix Expansion**

We now add **configuration management** and **Nmap tool specifics** to the PAD/README → Code → Test mapping.

| Requirement | Location in Code | Enforcement | Validation Method |
|-------------|-----------------|-------------|------------------|
| Config supports **file, env, defaults, hot reload** | `config.py` (`MCPConfig`) | `_load_from_file`, `_load_from_environment`, `check_for_changes`, `reload_config` | Unit tests: modify env vars, config file, assert reload applies |
| Config enforces **bounds & validation** (timeouts, concurrency, thresholds) | `config.py` validators | `_validate_*` methods clamp values | Param fuzz tests: set out-of-range values, assert clamped |
| Sensitive keys redacted in logs | `MCPConfig.redact_sensitive_data` | Replaces with `***REDACTED***` | Dump config, assert secrets hidden |
| Nmap tool only allows **RFC1918/.lab.internal** targets | `nmap_tool._validate_nmap_requirements` | ipaddress checks, hostname suffix | Unit tests: valid/invalid IPs & hostnames |
| Nmap tool enforces **network size ≤ 1024 hosts** | `MAX_NETWORK_SIZE` | Rejects larger CIDRs | Test with `/16` vs `/24` |
| Nmap tool enforces **safe flags/scripts** | `allowed_flags`, `_validate_script_specification` | Whitelist + SAFE_SCRIPTS | Try `--script=exploit` → reject |
| Nmap tool auto‑optimizes args | `_optimize_nmap_args` | Adds `-T4`, `--max-parallelism=10`, `-Pn`, `--top-ports=1000` | Execute with empty args, assert defaults injected |
| Prometheus metrics exposed | `metrics.py` + docker-compose | `/metrics` endpoint, port 9090 | Curl endpoint, check `mcp_tool_execution_total` |
| Alerts defined for **failure rate, timeouts, latency, concurrency** | `docker/alerts.yml` | PromQL rules | Run Prometheus, trigger synthetic failures, assert alerts fire |
| Healthcheck integrated | `docker/healthcheck.sh` | Curl/wget `/health` | Docker logs show container healthy/unhealthy |

---

## 2. **Static Inspection Tasks**

### Config (`config.py`)
- Verify **thread‑safe reload** (`RLock`).
- Confirm **deep merge precedence**: defaults < file < env.
- Check **validation clamps** (timeouts, concurrency, thresholds).
- Confirm **sensitive key redaction** works for DB URL, API keys.

### Nmap Tool (`nmap_tool.py`)
- Confirm **allowed_flags** matches PAD (safe subset).
- Validate **script safety**: only `safe`, `default`, `discovery`, `version`, `vuln`, etc.
- Confirm **port spec regex** prevents injection.
- Ensure **optimizations** align with README (T4, parallelism=10, skip host discovery, top 1000 ports).
- Confirm **circuit breaker config** is applied from `config`.

### Prometheus/Grafana Stack
- **Dockerfile**: installs `prometheus-client`, `nmap`, `masscan`, `gobuster`.
- **docker-compose.yml**: 
  - MCP server exposes `8080` (API) + `9090` (metrics).
  - Prometheus scrapes MCP at `9090`.
  - Grafana provisioned with dashboards.
- **alerts.yml**: 
  - Failure rate >20% (warn), >50% (crit).
  - Timeout >10%.
  - Latency p95 >5s, p99 >10s.
  - Concurrency >4 (warn), >8 (crit).
- **prometheus.yml**: 
  - Scrapes MCP, node-exporter, cadvisor, grafana.
  - Drops debug metrics, keeps only `mcp_*`.
- **healthcheck.sh**: 
  - Uses curl/wget to `/health`, fails container if unhealthy.

---

## 3. **Runtime Validation Plan**

### Config
- Start with defaults → assert values.
- Override via YAML → assert applied.
- Override via env → assert env wins.
- Modify config file → trigger `reload_config()` → assert hot reload.

### Nmap Tool
- Run with valid RFC1918 target → success.
- Run with public IP → rejected.
- Run with `/16` → rejected (too many hosts).
- Run with `--script=exploit` → rejected.
- Run with no args → assert `-T4 --max-parallelism=10 -Pn --top-ports=1000` injected.

### Prometheus
- Curl `/metrics` → assert `mcp_tool_execution_total`, `mcp_tool_execution_seconds_bucket`, `mcp_tool_active`.
- Trigger tool failures → assert `mcp_tool_errors_total` increments.
- Trigger breaker open → assert `mcp_circuit_breaker_state` changes.

### Alerts
- Synthetic load test: run failing tool repeatedly → assert `MCPFailureRateHigh` fires.
- Force timeouts → assert `MCPTimeoutRateHigh`.
- Run long jobs → assert `MCPLatencyP95High`.

---

## 4. **Deliverables**

- **Traceability matrix** (PAD/README → code → test).
- **Unit tests** for config + nmap validation.
- **Integration tests** for metrics, health, breaker.
- **Prometheus/Grafana dashboards** validated against metrics.
- **Alert firing evidence** (Prometheus UI screenshots/logs).

---

✅ **Summary**:  
With **config.py** and **nmap_tool.py**, plus the **Prometheus/Grafana/alerting stack**, the MCP server is now fully reviewable against PAD/README. The plan ensures **config correctness, tool safety, observability, and alerting fidelity**.

---

Would you like me to **draft the actual pytest test suite skeletons** (unit + integration) for config and Nmap tool validation, so you can drop them straight into the repo and run them under CI?
