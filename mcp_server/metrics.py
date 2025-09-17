# File: metrics.py
"""
Metrics collection system for MCP server.
Production-ready implementation with proper validation and error handling.
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
except ImportError:
    PROMETHEUS_AVAILABLE = False

log = logging.getLogger(__name__)

@dataclass
class ToolExecutionMetrics:
    """Metrics for tool execution with validation."""
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
        """Record a tool execution with validation."""
        # Validate execution time
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
        """Get statistics for this tool."""
        if self.execution_count == 0:
            return {
                "tool_name": self.tool_name,
                "execution_count": 0,
                "success_rate": 0.0,
                "average_execution_time": 0.0,
                "min_execution_time": 0.0,
                "max_execution_time": 0.0
            }
        
        # Prevent division by zero
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
    """System-level metrics with thread safety."""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.request_count = 0
        self.error_count = 0
        self.active_connections = 0
        self._lock = None  # Could use threading.Lock if needed
    
    def increment_request_count(self):
        """Increment request count."""
        self.request_count += 1
    
    def increment_error_count(self):
        """Increment error count."""
        self.error_count += 1
    
    def increment_active_connections(self):
        """Increment active connections."""
        self.active_connections += 1
    
    def decrement_active_connections(self):
        """Decrement active connections."""
        self.active_connections = max(0, self.active_connections - 1)
    
    def get_uptime(self) -> float:
        """Get uptime in seconds."""
        return (datetime.now() - self.start_time).total_seconds()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get system statistics."""
        uptime = self.get_uptime()
        error_rate = (self.error_count / self.request_count * 100) if self.request_count > 0 else 0
        
        return {
            "uptime_seconds": uptime,
            "uptime_formatted": str(timedelta(seconds=int(uptime))),
            "request_count": self.request_count,
            "error_count": self.error_count,
            "error_rate": round(error_rate, 2),
            "active_connections": self.active_connections,
            "start_time": self.start_time.isoformat()
        }

class PrometheusMetrics:
    """Prometheus metrics collection with graceful degradation."""
    
    def __init__(self):
        if not PROMETHEUS_AVAILABLE:
            log.warning("prometheus.unavailable")
            self.registry = None
            return
        
        try:
            self.registry = CollectorRegistry()
            
            # Tool execution metrics
            self.tool_execution_counter = Counter(
                'mcp_tool_execution_total',
                'Total tool executions',
                ['tool', 'status', 'error_type'],
                registry=self.registry
            )
            
            self.tool_execution_histogram = Histogram(
                'mcp_tool_execution_seconds',
                'Tool execution time in seconds',
                ['tool'],
                registry=self.registry
            )
            
            self.tool_active_gauge = Gauge(
                'mcp_tool_active',
                'Currently active tool executions',
                ['tool'],
                registry=self.registry
            )
            
            # System metrics
            self.system_request_counter = Counter(
                'mcp_system_requests_total',
                'Total system requests',
                registry=self.registry
            )
            
            self.system_error_counter = Counter(
                'mcp_system_errors_total',
                'Total system errors',
                ['error_type'],
                registry=self.registry
            )
            
            self.system_active_connections = Gauge(
                'mcp_system_active_connections',
                'Currently active connections',
                registry=self.registry
            )
            
            self.system_uptime_gauge = Gauge(
                'mcp_system_uptime_seconds',
                'System uptime in seconds',
                registry=self.registry
            )
            
            log.info("prometheus.metrics_initialized")
            
        except Exception as e:
            log.error("prometheus.initialization_failed error=%s", str(e))
            self.registry = None
    
    def record_tool_execution(self, tool_name: str, success: bool, execution_time: float, 
                             error_type: str = None):
        """Record tool execution metrics."""
        if not PROMETHEUS_AVAILABLE or not self.registry:
            return
        
        try:
            # Validate execution time
            execution_time = max(0.0, float(execution_time))
            
            status = 'success' if success else 'failure'
            self.tool_execution_counter.labels(
                tool=tool_name,
                status=status,
                error_type=error_type or 'none'
            ).inc()
            
            self.tool_execution_histogram.labels(tool=tool_name).observe(execution_time)
            
        except Exception as e:
            log.warning("prometheus.tool_execution_error error=%s", str(e))
    
    def increment_tool_active(self, tool_name: str):
        """Increment active tool gauge."""
        if PROMETHEUS_AVAILABLE and self.registry and self.tool_active_gauge:
            try:
                self.tool_active_gauge.labels(tool=tool_name).inc()
            except Exception as e:
                log.warning("prometheus.increment_active_error error=%s", str(e))
    
    def decrement_tool_active(self, tool_name: str):
        """Decrement active tool gauge."""
        if PROMETHEUS_AVAILABLE and self.registry and self.tool_active_gauge:
            try:
                self.tool_active_gauge.labels(tool=tool_name).dec()
            except Exception as e:
                log.warning("prometheus.decrement_active_error error=%s", str(e))
    
    def increment_system_request(self):
        """Increment system request counter."""
        if PROMETHEUS_AVAILABLE and self.registry and self.system_request_counter:
            try:
                self.system_request_counter.inc()
            except Exception as e:
                log.warning("prometheus.system_request_error error=%s", str(e))
    
    def increment_system_error(self, error_type: str = 'unknown'):
        """Increment system error counter."""
        if PROMETHEUS_AVAILABLE and self.registry and self.system_error_counter:
            try:
                self.system_error_counter.labels(error_type=error_type).inc()
            except Exception as e:
                log.warning("prometheus.system_error_error error=%s", str(e))
    
    def update_active_connections(self, count: int):
        """Update active connections gauge."""
        if PROMETHEUS_AVAILABLE and self.registry and self.system_active_connections:
            try:
                self.system_active_connections.set(max(0, count))
            except Exception as e:
                log.warning("prometheus.active_connections_error error=%s", str(e))
    
    def update_uptime(self, uptime_seconds: float):
        """Update uptime gauge."""
        if PROMETHEUS_AVAILABLE and self.registry and self.system_uptime_gauge:
            try:
                self.system_uptime_gauge.set(max(0.0, uptime_seconds))
            except Exception as e:
                log.warning("prometheus.uptime_error error=%s", str(e))
    
    def get_metrics(self) -> Optional[str]:
        """Get Prometheus metrics in text format."""
        if not PROMETHEUS_AVAILABLE or not self.registry:
            return None
        
        try:
            return generate_latest(self.registry).decode('utf-8')
        except Exception as e:
            log.error("prometheus.generate_metrics_error error=%s", str(e))
            return None

class MetricsManager:
    """Manager for all metrics collection."""
    
    def __init__(self):
        self.tool_metrics: Dict[str, ToolExecutionMetrics] = {}
        self.system_metrics = SystemMetrics()
        self.prometheus_metrics = PrometheusMetrics()
        self.start_time = datetime.now()
    
    def get_tool_metrics(self, tool_name: str) -> ToolExecutionMetrics:
        """Get or create tool metrics."""
        if tool_name not in self.tool_metrics:
            self.tool_metrics[tool_name] = ToolExecutionMetrics(tool_name)
        return self.tool_metrics[tool_name]
    
    def record_tool_execution(self, tool_name: str, success: bool, execution_time: float, 
                             timed_out: bool = False, error_type: str = None):
        """Record tool execution across all metrics systems."""
        # Record in tool-specific metrics
        tool_metrics = self.get_tool_metrics(tool_name)
        tool_metrics.record_execution(success, execution_time, timed_out)
        
        # Record in Prometheus
        self.prometheus_metrics.record_tool_execution(tool_name, success, execution_time, error_type)
        
        # Record in system metrics
        self.system_metrics.increment_request_count()
        if not success:
            self.system_metrics.increment_error_count()
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get all statistics."""
        return {
            "system": self.system_metrics.get_stats(),
            "tools": {name: metrics.get_stats() for name, metrics in self.tool_metrics.items()},
            "prometheus_available": PROMETHEUS_AVAILABLE,
            "collection_start_time": self.start_time.isoformat()
        }
    
    def get_prometheus_metrics(self) -> Optional[str]:
        """Get Prometheus metrics export."""
        return self.prometheus_metrics.get_metrics()
