Thanks — I ran a careful, line-by-line review of both tools (nmap_tool.py and gobuster_tool.py) with an eye for correctness, API compatibility with the base classes/config, security, and runtime robustness. Below I summarize the findings and provide small, safe fixes (drop-in patches) that address the highest-impact issues so these tools will import and run cleanly with the rest of the codebase.

What I checked (quick)
- API compatibility with mcp_server.base_tool (method names, signatures, helpers).
- Correct use of the configuration API returned by mcp_server.config.get_config().
- Concurrency / timeout propagation and use of ToolInput / ToolOutput.
- Safety checks (target validation, argument parsing) and flag handling.
- Minor robustness issues that will raise runtime exceptions (NameError, AttributeError) or produce wrong behavior.

High-impact issues found (per file)

1) mcp_server/tools/nmap_tool.py
- Config access mismatch:
  - _setup_enhanced_features checks getattr(self.config, "circuit_breaker_enabled", False) and then tries to read flat attributes like self.config.circuit_breaker_failure_timeout. MCPConfig exposes a structured object (config.circuit_breaker.failure_threshold, recovery_timeout). Using getattr with flat names will not work.
- Timeout propagation:
  - _execute_tool creates enhanced_input with timeout_sec set to timeout_sec or self.default_timeout_sec but then calls super()._execute_tool(enhanced_input, timeout_sec). If the original timeout_sec argument is None, super() may ignore the intended enhanced_input.timeout_sec. We should pass enhanced_input.timeout_sec to the super call.
- Minor: get_tool_info unconditionally sets "prometheus_available": True if metrics property exists — fine but slightly optimistic (metrics may be None); current code checks hasattr and self.metrics truthy so it's OK.
- Recommendation: read circuit breaker settings from config.circuit_breaker if present; fall back to environment or class defaults. Ensure the class-level circuit breaker is reinitialized (use type(self)._circuit_breaker = None) — current code already does that.

2) mcp_server/tools/gobuster_tool.py
- Config access mismatch:
  - _setup_enhanced_features uses self.config.circuit_breaker_enabled and flat attributes (self.config.circuit_breaker_failure_threshold) which do not exist on MCPConfig.
- Incorrect reinitialization of circuit breaker:
  - It sets self._circuit_breaker = None and then calls _initialize_circuit_breaker(). base_tool expects the circuit breaker to be a class-level var (type(self)._circuit_breaker). Setting the instance var doesn't reset the class-level circuit breaker. This makes reinitialization ineffective.
- Missing helper method:
  - run() calls self._create_command_not_found_error_output(inp.correlation_id) — there is no such method in base_tool. That will raise AttributeError.
- Minor validation: _validate_gobuster_requirements rejects empty extra_args; acceptable but note some callers might pass mode via extra_args only; that's fine.
- Recommendation: set type(self)._circuit_breaker = None for reinit, read config.circuit_breaker.* properly, and replace the non-existent helper with constructing an ErrorContext and returning self._create_error_output(...).

Patches
Below are safe, small edits that fix the above issues. Each patch is minimal and conservative.

```python name=mcp_server/tools/nmap_tool.py
# File: mcp_server/tools/nmap_tool.py
"""
Enhanced Nmap tool with circuit breaker, metrics, and advanced features.
"""
import logging
import shlex
import ipaddress
from datetime import datetime, timezone
from typing import Sequence, Optional

from mcp_server.base_tool import MCPBaseTool, ToolInput, ToolOutput, ToolErrorType, ErrorContext
from mcp_server.config import get_config

log = logging.getLogger(__name__)

class NmapTool(MCPBaseTool):
    """
    Enhanced Nmap network scanner tool with advanced features.
    """
    command_name: str = "nmap"

    # Conservative, safe flags for nmap (prefix/option names only; values allowed after '=' or space)
    allowed_flags: Sequence[str] = [
        "-sV", "-sC", "-A", "-p", "--top-ports", "-T", "-T4", "-Pn",
        "-O", "--script", "-oX", "-oN", "-oG", "--max-parallelism",
    ]

    # Nmap can run long; set higher timeout
    default_timeout_sec: float = 600.0

    # Limit concurrency to avoid overloading host and network
    concurrency: int = 1

    # Circuit breaker configuration defaults
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: float = 120.0  # 2 minutes for nmap
    circuit_breaker_expected_exception: tuple = (Exception,)

    def __init__(self):
        super().__init__()
        self.config = get_config()
        self._setup_enhanced_features()

    def _setup_enhanced_features(self):
        """Setup enhanced features for Nmap tool."""
        # Prefer explicit structured config if available
        try:
            cb = getattr(self.config, "circuit_breaker", None)
            if cb:
                # MCPConfig uses nested circuit_breaker dataclass
                self.circuit_breaker_failure_threshold = getattr(cb, "failure_threshold", self.circuit_breaker_failure_threshold)
                self.circuit_breaker_recovery_timeout = getattr(cb, "recovery_timeout", self.circuit_breaker_recovery_timeout)
            else:
                # Fallback to optional flat env-like flags if present on config object
                if getattr(self.config, "circuit_breaker_enabled", False):
                    self.circuit_breaker_failure_threshold = getattr(self.config, "circuit_breaker_failure_threshold", self.circuit_breaker_failure_threshold)
                    self.circuit_breaker_recovery_timeout = getattr(self.config, "circuit_breaker_recovery_timeout", self.circuit_breaker_recovery_timeout)
        except Exception:
            log.debug("nmap._setup_enhanced_features: unable to read config; using defaults")

        # Reinitialize circuit breaker with new settings (class-level, not instance)
        try:
            type(self)._circuit_breaker = None
        except Exception:
            self.__class__._circuit_breaker = None
        self._initialize_circuit_breaker()

    async def _execute_tool(self, inp: ToolInput, timeout_sec: Optional[float] = None) -> ToolOutput:
        """Enhanced tool execution with nmap-specific features."""
        # Validate nmap-specific requirements
        validation_result = self._validate_nmap_requirements(inp)
        if validation_result:
            return validation_result

        # Add nmap-specific optimizations
        optimized_args = self._optimize_nmap_args(inp.extra_args or "")

        # Create enhanced input with optimizations
        enhanced_input = ToolInput(
            target=inp.target,
            extra_args=optimized_args,
            timeout_sec=timeout_sec or self.default_timeout_sec,
            correlation_id=inp.correlation_id,
        )

        # Execute with enhanced monitoring - pass the enhanced timeout explicitly
        return await super()._execute_tool(enhanced_input, enhanced_input.timeout_sec)

    def _validate_nmap_requirements(self, inp: ToolInput) -> Optional[ToolOutput]:
        """Validate nmap-specific requirements."""
        target = inp.target.strip()

        # CIDR/network targets
        if "/" in target:
            try:
                network = ipaddress.ip_network(target, strict=False)
            except ValueError:
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Invalid network range: {target}",
                    recovery_suggestion="Use valid CIDR notation (e.g., 192.168.1.0/24)",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                )
                return self._create_error_output(error_context, inp.correlation_id)

            # Enforce reasonable scan size
            if network.num_addresses > 1024:
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Network range too large: {network.num_addresses} addresses",
                    recovery_suggestion="Use smaller network ranges or specify individual hosts",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                    metadata={"network_size": network.num_addresses},
                )
                return self._create_error_output(error_context, inp.correlation_id)

            # Enforce RFC1918/loopback for networks
            if not (network.is_private or network.is_loopback):
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Network not permitted: {target}",
                    recovery_suggestion="Use RFC1918 or loopback ranges only (e.g., 10.0.0.0/8, 192.168.0.0/16)",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                )
                return self._create_error_output(error_context, inp.correlation_id)

            return None

        # Single-host targets
        try:
            ip = ipaddress.ip_address(target)
            if not (ip.is_private or ip.is_loopback):
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"IP not permitted: {target}",
                    recovery_suggestion="Use RFC1918 or loopback IPs only",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                )
                return self._create_error_output(error_context, inp.correlation_id)
        except ValueError:
            # Not an IP -> treat as hostname
            if not target.endswith(".lab.internal"):
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Hostname not permitted: {target}",
                    recovery_suggestion="Use hostnames ending in .lab.internal",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=target,
                )
                return self._create_error_output(error_context, inp.correlation_id)

        return None

    def _optimize_nmap_args(self, extra_args: str) -> str:
        """Optimize nmap arguments for performance and safety."""
        if not extra_args:
            return ""

        try:
            args = shlex.split(extra_args)
        except ValueError as e:
            log.warning("nmap.args.parse_failed tool=%s error=%s args=%r", self.tool_name, str(e), extra_args)
            return extra_args

        optimized: list[str] = []

        has_timing = any(a.startswith("-T") for a in args)
        has_parallelism = any(a.startswith("--max-parallelism") for a in args)
        has_host_discovery = any(a in ("-Pn", "-sn") for a in args)

        if not has_timing:
            optimized.append("-T4")

        if not has_parallelism:
            optimized.append("--max-parallelism=10")

        if not has_host_discovery:
            optimized.append("-Pn")

        optimized.extend(args)
        return " ".join(optimized)

    def _get_timestamp(self):
        """Get current timestamp (UTC, timezone-aware)."""
        return datetime.now(timezone.utc)

    def get_tool_info(self) -> dict:
        """Get enhanced tool information."""
        base_info = {
            "name": self.tool_name,
            "command": self.command_name,
            "description": self.__doc__,
            "concurrency": self.concurrency,
            "timeout": self.default_timeout_sec,
            "allowed_flags": list(self.allowed_flags) if self.allowed_flags else [],
            "circuit_breaker": {
                "failure_threshold": self.circuit_breaker_failure_threshold,
                "recovery_timeout": self.circuit_breaker_recovery_timeout,
            },
            "optimizations": [
                "Aggressive timing (-T4)",
                "Limited parallelism (--max-parallelism=10)",
                "Host discovery skip (-Pn)",
            ],
        }

        if hasattr(self, "metrics") and self.metrics:
            base_info["metrics"] = {
                "prometheus_available": True,
                "execution_metrics": f'mcp_tool_execution_total{{tool="{self.tool_name}"}}',
            }

        return base_info
```

```python name=mcp_server/tools/gobuster_tool.py
# File: gobuster_tool.py
"""
Enhanced Gobuster tool with ALL original functionality preserved + comprehensive enhancements.
"""
import logging
from typing import List, Sequence, Tuple

from mcp_server.base_tool import MCPBaseTool, ToolInput, ToolOutput, ToolErrorType, ErrorContext
from mcp_server.config import get_config

log = logging.getLogger(__name__)

class GobusterTool(MCPBaseTool):
    """
    Enhanced Gobuster content/dns/vhost discovery tool.
    """
    command_name: str = "gobuster"
    allowed_modes: Tuple[str, ...] = ("dir", "dns", "vhost")
    allowed_flags: Sequence[str] = [
        "-w", "--wordlist", "-t", "--threads", "-q", "--quiet", "-k", "--no-tls-validation",
        "-o", "--output", "-s", "--status-codes", "-x", "--extensions", "--timeout",
        "--no-color", "-H", "--header", "-r", "--follow-redirect",
        "-u", "--url", "-d", "--domain", "--wildcard", "--append-domain",
    ]

    default_timeout_sec: float = 1200.0
    concurrency: int = 1

    circuit_breaker_failure_threshold: int = 4
    circuit_breaker_recovery_timeout: float = 180.0
    circuit_breaker_expected_exception: tuple = (Exception,)

    def __init__(self):
        super().__init__()
        self.config = get_config()
        self._setup_enhanced_features()

    def _setup_enhanced_features(self):
        """Setup enhanced features for Gobuster tool."""
        try:
            cb = getattr(self.config, "circuit_breaker", None)
            if cb:
                self.circuit_breaker_failure_threshold = getattr(cb, "failure_threshold", self.circuit_breaker_failure_threshold)
                self.circuit_breaker_recovery_timeout = getattr(cb, "recovery_timeout", self.circuit_breaker_recovery_timeout)
            else:
                if getattr(self.config, "circuit_breaker_enabled", False):
                    self.circuit_breaker_failure_threshold = getattr(self.config, "circuit_breaker_failure_threshold", self.circuit_breaker_failure_threshold)
                    self.circuit_breaker_recovery_timeout = getattr(self.config, "circuit_breaker_recovery_timeout", self.circuit_breaker_recovery_timeout)
        except Exception:
            log.debug("gobuster._setup_enhanced_features: unable to read config; using defaults")

        # Reinitialize circuit breaker at the class level so base class uses new settings
        try:
            type(self)._circuit_breaker = None
        except Exception:
            self.__class__._circuit_breaker = None
        self._initialize_circuit_breaker()

    def _split_tokens(self, extra_args: str) -> List[str]:
        """Get token list using base parser (which enforces safety)."""
        tokens = super()._parse_args(extra_args)
        return list(tokens)

    def _extract_mode_and_args(self, tokens: List[str]) -> Tuple[str, List[str]]:
        """ Determine mode and return (mode, remaining_args_without_mode). """
        mode = None
        rest: List[str] = []

        for i, tok in enumerate(tokens):
            if tok.startswith("-"):
                rest.append(tok)
                continue
            mode = tok
            rest.extend(tokens[i + 1 :])
            break

        if mode is None:
            raise ValueError("gobuster requires a mode: one of {dir,dns,vhost} as the first non-flag token")

        if mode not in self.allowed_modes:
            raise ValueError(f"gobuster mode not allowed: {mode!r}")

        return mode, rest

    def _ensure_target_arg(self, mode: str, args: List[str], target: str) -> List[str]:
        """ Ensure the proper -u/-d argument is present; inject from ToolInput if missing. """
        out = list(args)
        has_u = any(a in ("-u", "--url") for a in out)
        has_d = any(a in ("-d", "--domain") for a in out)

        if mode in ("dir", "vhost"):
            if not has_u:
                out.extend(["-u", target])
        elif mode == "dns":
            if not has_d:
                out.extend(["-d", target])

        return out

    async def run(self, inp: "ToolInput", timeout_sec: float | None = None):  # type: ignore[override]
        """Run gobuster with validation, optimization and execution."""
        resolved = self._resolve_command()
        if not resolved:
            # Construct a standardized "command not found" error output
            error_context = ErrorContext(
                error_type=ToolErrorType.NOT_FOUND,
                message=f"Command not found: {self.command_name}",
                recovery_suggestion="Install the required tool or check PATH",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target,
            )
            return self._create_error_output(error_context, inp.correlation_id)

        validation_result = self._validate_gobuster_requirements(inp)
        if validation_result:
            return validation_result

        try:
            tokens = self._split_tokens(inp.extra_args or "")
            mode, rest = self._extract_mode_and_args(tokens)

            if not self._is_mode_valid_for_target(mode, inp.target):
                error_context = ErrorContext(
                    error_type=ToolErrorType.VALIDATION_ERROR,
                    message=f"Invalid target '{inp.target}' for mode '{mode}'",
                    recovery_suggestion=f"For {mode} mode, use appropriate target format",
                    timestamp=self._get_timestamp(),
                    tool_name=self.tool_name,
                    target=inp.target
                )
                return self._create_error_output(error_context, inp.correlation_id)

            for t in rest:
                if not t.startswith("-") and t in self.allowed_modes:
                    error_context = ErrorContext(
                        error_type=ToolErrorType.VALIDATION_ERROR,
                        message=f"Multiple modes specified: {mode}, {t}",
                        recovery_suggestion="Specify only one mode",
                        timestamp=self._get_timestamp(),
                        tool_name=self.tool_name,
                        target=inp.target
                    )
                    return self._create_error_output(error_context, inp.correlation_id)

            final_args = self._ensure_target_arg(mode, rest, inp.target)
            optimized_args = self._optimize_gobuster_args(mode, final_args)

            cmd = [resolved] + [mode] + optimized_args
            timeout = float(timeout_sec or self.default_timeout_sec)
            return await self._spawn(cmd, timeout)

        except ValueError as e:
            error_context = ErrorContext(
                error_type=ToolErrorType.VALIDATION_ERROR,
                message=f"Argument validation failed: {str(e)}",
                recovery_suggestion="Check arguments and try again",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target
            )
            return self._create_error_output(error_context, inp.correlation_id)

    def _validate_gobuster_requirements(self, inp: ToolInput) -> Optional[ToolOutput]:
        """Validate gobuster-specific requirements."""
        if not (inp.extra_args and inp.extra_args.strip()):
            error_context = ErrorContext(
                error_type=ToolErrorType.VALIDATION_ERROR,
                message="Gobuster requires a mode: dir, dns, or vhost",
                recovery_suggestion="Specify a mode as the first argument",
                timestamp=self._get_timestamp(),
                tool_name=self.tool_name,
                target=inp.target
            )
            return self._create_error_output(error_context, inp.correlation_id)
        return None

    def _is_mode_valid_for_target(self, mode: str, target: str) -> bool:
        """Check if the target is valid for the specified mode."""
        if mode == "dns":
            return not target.startswith(("http://", "https://"))
        elif mode in ("dir", "vhost"):
            return target.startswith(("http://", "https://"))
        return True

    def _optimize_gobuster_args(self, mode: str, args: List[str]) -> List[str]:
        """Optimize gobuster arguments for performance and safety."""
        optimized = list(args)

        if mode == "dir":
            has_threads = any(arg in ("-t", "--threads") for arg in args)
            if not has_threads:
                optimized.extend(["-t", "50"])
            has_status_codes = any(arg in ("-s", "--status-codes") for arg in args)
            if not has_status_codes:
                optimized.extend(["-s", "200,204,301,302,307,401,403"])

        elif mode == "dns":
            has_threads = any(arg in ("-t", "--threads") for arg in args)
            if not has_threads:
                optimized.extend(["-t", "100"])
            has_wildcard = any(arg == "--wildcard" for arg in args)
            if not has_wildcard:
                optimized.append("--wildcard")

        elif mode == "vhost":
            has_threads = any(arg in ("-t", "--threads") for arg in args)
            if not has_threads:
                optimized.extend(["-t", "30"])

        return optimized

    def _get_timestamp(self):
        """Get current timestamp."""
        from datetime import datetime
        return datetime.now()

    def get_tool_info(self) -> dict:
        """Get enhanced tool information."""
        base_info = {
            "name": self.tool_name,
            "command": self.command_name,
            "description": self.__doc__,
            "concurrency": self.concurrency,
            "timeout": self.default_timeout_sec,
            "allowed_modes": list(self.allowed_modes),
            "allowed_flags": list(self.allowed_flags) if self.allowed_flags else [],
            "circuit_breaker": {
                "failure_threshold": self.circuit_breaker_failure_threshold,
                "recovery_timeout": self.circuit_breaker_recovery_timeout
            },
            "mode_optimizations": {
                "dir": {"default_threads": 50, "default_status_codes": "200,204,301,302,307,401,403"},
                "dns": {"default_threads": 100, "wildcard_detection": True},
                "vhost": {"default_threads": 30}
            }
        }

        if hasattr(self, 'metrics') and self.metrics:
            base_info["metrics"] = {
                "prometheus_available": True,
                "execution_metrics": f"mcp_tool_execution_total{{tool=\"{self.tool_name}\"}}"
            }

        return base_info
```

What I changed and why (summary)
- Fixed config reads to use structured config.circuit_breaker.* when available, with a safe fallback for older/flat attributes or env-like fields.
- Ensured circuit-breaker reinitialization resets the class-level circuit breaker (type(self)._circuit_breaker = None).
- Replaced missing helper call in Gobuster ( _create_command_not_found_error_output ) with a standard ErrorContext + _create_error_output usage.
- Ensured timeouts propagate: Nmap now passes the resolved/enhanced timeout into super()._execute_tool.
- Made small defensive changes (use inp.extra_args or "" when parsing) to avoid None issues.

Validation steps you should run locally or in CI
1. Static import test:
   - python -c "import mcp_server.tools.nmap_tool; import mcp_server.tools.gobuster_tool; print('imports OK')"
   - Expect no ImportError/AttributeError.
2. Unit smoke:
   - Create a ToolInput for each tool with safe RFC1918 target (e.g., 192.168.1.1) and a minimal extra_args (e.g., "dir -w /tmp/wl -t 1"); call the tool.run() in an asyncio event loop and check outputs or errors — this assumes the actual binary exists; for CI, mock _resolve_command or set PATH to point to a small script.
3. Circuit breaker integration:
   - Confirm that after setup, type(tool)._circuit_breaker exists and its configured thresholds match config settings (if you provide config).
4. Lint & tests:
   - flake8 / pytest (add small unit tests that mock subprocess execution or mock _spawn to not actually run binaries).

Would you like me to:
- Open a branch and push these patches as a PR (I can prepare the commit and PR text)?
- Add small unit tests that mock _resolve_command/_spawn and validate argument parsing, target injection, and error outputs?
- Run additional cross-file checks (e.g., ensure tests for base_tool + metrics + circuit_breaker work together)?

If you want the PR, I’ll prepare it next (I can include both file updates and a couple of small unit tests).

https://github.com/copilot/share/c8111184-0804-8cd5-a900-7e48a46921e2
