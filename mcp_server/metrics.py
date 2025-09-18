# File: metrics.py
"""
Metrics collection system for MCP server.
Adjusted to avoid repeated registrations of identical Prometheus metrics.
Metrics objects are created once globally and reused by tool-specific wrappers.
"""
import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field

# Graceful Prometheus dependency handling
try:
    from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest
    from prometheus_client.core import CollectorRegistry
    PROMETHEUS_AVAILABLE = True
except Exception:
    PROMETHEUS_AVAILABLE = False

log = logging.getLogger(__name__)

# Module-level, single definitions of commonly used metric families to avoid duplicate registration.
if PROMETHEUS_AVAILABLE:
    try:
        GLOBAL_EXECUTION_COUNTER = Counter(
            'mcp_tool_execution_total',
            'Total tool executions',
            ['tool', 'status', 'error_type']
        )
        GLOBAL_EXECUTION_HISTOGRAM = Histogram(
            'mcp_tool_execution_seconds',
            'Tool execution time in seconds',
            ['tool']
        )
        GLOBAL_ACTIVE_GAUGE = Gauge(
            'mcp_tool_active',
            'Currently active tool executions',
            ['tool']
        )
        GLOBAL_ERROR_COUNTER = Counter(
            'mcp_tool_errors_total',
            'Total tool errors',
            ['tool', 'error_type']
        )
    except Exception as e:
        log.warning("prometheus.global_metric_initialization_failed error=%s", str(e))
        GLOBAL_EXECUTION_COUNTER = GLOBAL_EXECUTION_HISTOGRAM = GLOBAL_ACTIVE_GAUGE = GLOBAL_ERROR_COUNTER = None
else:
    GLOBAL_EXECUTION_COUNTER = GLOBAL_EXECUTION_HISTOGRAM = GLOBAL_ACTIVE_GAUGE = GLOBAL_ERROR_COUNTER = None

@dataclass
class ToolExecutionMetrics:
    tool_name: str
    execution_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0
    total_execution_time: float = 0.0
    min_execution_time: float = float('inf')
    max_execution_time: float = 0.0
    last_execution_time: Optional[datetime] = None

    def record_execution(self, success: bool, execution_time: float, timed_out: bool = False):
        execution_time = max(0.0, float(execution_time))
        self.execution_count += 1
        self.total_execution_time += execution_time
        if execution_time < self.min_execution_time:
            self.min_execution_time = execution_time
        if execution_time > self.max_execution_time:
            self.max_execution_time = execution_time
        self.last_execution_time = datetime.now()
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
        if timed_out:
            self.timeout_count += 1

    def get_stats(self) -> Dict[str, Any]:
        if self.execution_count == 0:
            return {
                "tool_name": self.tool_name,
                "execution_count": 0,
                "success_rate": 0.0,
                "average_execution_time": 0.0,
                "min_execution_time": 0.0,
                "max_execution_time": 0.0
            }
        avg_execution_time = self.total_execution_time / self.execution_count
        success_rate = (self.success_count / self.execution_count) * 100
        return {
            "tool_name": self.tool_name,
            "execution_count": self.execution_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "timeout_count": self.timeout_count,
            "success_rate": round(success_rate, 2),
            "average_execution_time": round(avg_execution_time, 4),
            "min_execution_time": round(self.min_execution_time, 4) if self.min_execution_time != float('inf') else 0.0,
            "max_execution_time": round(self.max_execution_time, 4),
            "last_execution_time": self.last_execution_time.isoformat() if self.last_execution_time else None
        }

class SystemMetrics:
    def __init__(self):
        self.start_time = datetime.now()
        self.request_count = 0
        self.error_count = 0
        self.active_connections = 0
        self._lock = None

    def increment_request_count(self):
        self.request_count += 1

    def increment_error_count(self):
        self.error_count += 1

    def increment_active_connections(self):
        self.active_connections += 1

    def decrement_active_connections(self):
        self.active_connections = max(0, self.active_connections - 1)

    def get_uptime(self) -> float:
        return (datetime.now() - self.start_time).total_seconds()

    def get_stats(self) -> Dict[str, Any]:
        uptime = self.get_uptime()
        error_rate = (self.error_count / self.request_count * 100) if self.request_count > 0 else 0
        return {
            "uptime_seconds": uptime,
            "request_count": self.request_count,
            "error_count": self.error_count,
            "error_rate": round(error_rate, 2),
            "active_connections": self.active_connections,
            "start_time": self.start_time.isoformat()
        }

class PrometheusMetrics:
    def __init__(self):
        if not PROMETHEUS_AVAILABLE:
            log.warning("prometheus.unavailable")
            self.registry = None
            return
        try:
            self.registry = CollectorRegistry()
            # The module-level globals hold main metric families to avoid duplicates.
            log.info("prometheus.metrics_initialized")
        except Exception as e:
            log.error("prometheus.initialization_failed error=%s", str(e))
            self.registry = None

    def get_metrics(self) -> Optional[str]:
        if not PROMETHEUS_AVAILABLE or not self.registry:
            return None
        try:
            return generate_latest(self.registry).decode('utf-8')
        except Exception as e:
            log.error("prometheus.generate_metrics_error error=%s", str(e))
            return None

class MetricsManager:
    def __init__(self):
        self.tool_metrics: Dict[str, ToolExecutionMetrics] = {}
        self.system_metrics = SystemMetrics()
        self.prometheus_metrics = PrometheusMetrics()
        self.start_time = datetime.now()

    def get_tool_metrics(self, tool_name: str) -> ToolExecutionMetrics:
        if tool_name not in self.tool_metrics:
            self.tool_metrics[tool_name] = ToolExecutionMetrics(tool_name)
        return self.tool_metrics[tool_name]

    def record_tool_execution(self, tool_name: str, success: bool, execution_time: float,
                             timed_out: bool = False, error_type: str = None):
        tool_metrics = self.get_tool_metrics(tool_name)
        tool_metrics.record_execution(success, execution_time, timed_out)
        # Prometheus: use module-level global metrics if available
        if PROMETHEUS_AVAILABLE and GLOBAL_EXECUTION_COUNTER is not None:
            try:
                status = 'success' if success else 'failure'
                GLOBAL_EXECUTION_COUNTER.labels(tool=tool_name, status=status, error_type=error_type or 'none').inc()
                if GLOBAL_EXECUTION_HISTOGRAM:
                    GLOBAL_EXECUTION_HISTOGRAM.labels(tool=tool_name).observe(float(execution_time))
                if not success and GLOBAL_ERROR_COUNTER:
                    GLOBAL_ERROR_COUNTER.labels(tool=tool_name, error_type=error_type or 'unknown').inc()
            except Exception as e:
                log.warning("prometheus.tool_execution_error error=%s", str(e))
        self.system_metrics.increment_request_count()
        if not success:
            self.system_metrics.increment_error_count()

    def get_all_stats(self) -> Dict[str, Any]:
        return {
            "system": self.system_metrics.get_stats(),
            "tools": {name: metrics.get_stats() for name, metrics in self.tool_metrics.items()},
            "prometheus_available": PROMETHEUS_AVAILABLE,
            "collection_start_time": self.start_time.isoformat()
        }

    def get_prometheus_metrics(self) -> Optional[str]:
        return self.prometheus_metrics.get_metrics()
