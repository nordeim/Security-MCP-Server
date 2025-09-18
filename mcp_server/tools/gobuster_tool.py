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
