"""
Metrics collection system for MCP server.
Production-ready implementation with thread safety and memory management.
"""
import time
import logging
import threading
from typing import Dict, Any, Optional, Set, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import deque

log = logging.getLogger(__name__)


class PrometheusRegistry:
    """Singleton registry to prevent duplicate metric registration."""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def initialize(self):
        """Initialize Prometheus metrics once."""
        if self._initialized:
            return
        
        with self._lock:
            if self._initialized:
                return
            
            try:
                from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, generate_latest
                from prometheus_client.core import REGISTRY
                
                self.registry = REGISTRY
                self.generate_latest = generate_latest
                
                existing_metrics = {collector.name for collector in self.registry._collector_to_names.keys() 
                                  if hasattr(collector, 'name')}
                
                if 'mcp_tool_execution_total' not in existing_metrics:
                    self.execution_counter = Counter(
                        'mcp_tool_execution_total',
                        'Total tool executions',
                        ['tool', 'status', 'error_type'],
                        registry=self.registry
                    )
                else:
                    self.execution_counter = None
                    for collector in self.registry._collector_to_names.keys():
                        if hasattr(collector, '_name') and collector._name == 'mcp_tool_execution_total':
                            self.execution_counter = collector
                            break
                
                if 'mcp_tool_execution_seconds' not in existing_metrics:
                    self.execution_histogram = Histogram(
                        'mcp_tool_execution_seconds',
                        'Tool execution time in seconds',
                        ['tool'],
                        registry=self.registry
                    )
                else:
                    self.execution_histogram = None
                    for collector in self.registry._collector_to_names.keys():
                        if hasattr(collector, '_name') and collector._name == 'mcp_tool_execution_seconds':
                            self.execution_histogram = collector
                            break
                
                if 'mcp_tool_active' not in existing_metrics:
                    self.active_gauge = Gauge(
                        'mcp_tool_active',
                        'Currently active tool executions',
                        ['tool'],
                        registry=self.registry
                    )
                else:
                    self.active_gauge = None
                    for collector in self.registry._collector_to_names.keys():
                        if hasattr(collector, '_name') and collector._name == 'mcp_tool_active':
                            self.active_gauge = collector
                            break
                
                if 'mcp_tool_errors_total' not in existing_metrics:
                    self.error_counter = Counter(
                        'mcp_tool_errors_total',
                        'Total tool errors',
                        ['tool', 'error_type'],
                        registry=self.registry
                    )
                else:
                    self.error_counter = None
                    for collector in self.registry._collector_to_names.keys():
                        if hasattr(collector, '_name') and collector._name == 'mcp_tool_errors_total':
                            self.error_counter = collector
                            break
                
                self._initialized = True
                self.available = True
                log.info("prometheus.initialized successfully")
                
            except ImportError:
                self.available = False
                self.generate_latest = None
                log.info("prometheus.not_available")
            except Exception as e:
                self.available = False
                self.generate_latest = None
                log.error("prometheus.initialization_failed error=%s", str(e))


_prometheus_registry = PrometheusRegistry()
_prometheus_registry.initialize()


@dataclass
class ToolExecutionMetrics:
    """Thread-safe tool execution metrics."""
    tool_name: str
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    execution_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0
    total_execution_time: float = 0.0
    min_execution_time: float = float('inf')
    max_execution_time: float = 0.0
    last_execution_time: Optional[datetime] = None
    recent_executions: deque = field(default_factory=lambda: deque(maxlen=100))
    
    def record_execution(self, success: bool, execution_time: float, 
                         timed_out: bool = False, error_type: Optional[str] = None):
        """Thread-safe execution recording."""
        with self._lock:
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
            
            self.recent_executions.append({
                "timestamp": datetime.now(),
                "success": success,
                "execution_time": execution_time,
                "timed_out": timed_out,
                "error_type": error_type
            })
    
    def get_stats(self) -> Dict[str, Any]:
        """Get thread-safe statistics snapshot."""
        with self._lock:
            if self.execution_count == 0:
                return {
                    "tool_name": self.tool_name,
                    "execution_count": 0,
                    "success_rate": 0.0,
                    "average_execution_time": 0.0,
                    "p50_execution_time": 0.0,
                    "p95_execution_time": 0.0,
                    "p99_execution_time": 0.0,
                }
            
            recent_times = sorted([
                e["execution_time"] for e in self.recent_executions
            ])
            
            if recent_times:
                p50_idx = len(recent_times) // 2
                p95_idx = min(int(len(recent_times) * 0.95), len(recent_times) - 1)
                p99_idx = min(int(len(recent_times) * 0.99), len(recent_times) - 1)
                
                p50 = recent_times[p50_idx]
                p95 = recent_times[p95_idx]
                p99 = recent_times[p99_idx]
            else:
                p50 = p95 = p99 = 0.0
            
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
                "p50_execution_time": round(p50, 4),
                "p95_execution_time": round(p95, 4),
                "p99_execution_time": round(p99, 4),
                "last_execution_time": self.last_execution_time.isoformat() if self.last_execution_time else None,
                "recent_failure_rate": self._calculate_recent_failure_rate(),
            }
    
    def _calculate_recent_failure_rate(self) -> float:
        """Calculate failure rate from recent executions."""
        if not self.recent_executions:
            return 0.0
        
        recent_failures = sum(
            1 for e in self.recent_executions if not e["success"]
        )
        return round((recent_failures / len(self.recent_executions)) * 100, 2)


class SystemMetrics:
    """System-wide metrics tracking."""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.request_count = 0
        self.error_count = 0
        self.active_connections = 0
        self._lock = threading.Lock()
    
    def increment_request_count(self):
        """Thread-safe request count increment."""
        with self._lock:
            self.request_count += 1
    
    def increment_error_count(self):
        """Thread-safe error count increment."""
        with self._lock:
            self.error_count += 1
    
    def increment_active_connections(self):
        """Thread-safe active connections increment."""
        with self._lock:
            self.active_connections += 1
    
    def decrement_active_connections(self):
        """Thread-safe active connections decrement."""
        with self._lock:
            self.active_connections = max(0, self.active_connections - 1)
    
    def get_uptime(self) -> float:
        """Get system uptime in seconds."""
        return (datetime.now() - self.start_time).total_seconds()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get system statistics."""
        with self._lock:
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


class ToolMetrics:
    """Per-tool metrics wrapper with Prometheus integration."""
    
    def __init__(self, tool_name: str):
        self.tool_name = tool_name
        self.metrics = ToolExecutionMetrics(tool_name)
        self._active_count = 0
        self._lock = threading.Lock()
    
    async def record_execution(self, success: bool, execution_time: float,
                               timed_out: bool = False, error_type: Optional[str] = None):
        """Record execution with Prometheus metrics."""
        self.metrics.record_execution(success, execution_time, timed_out, error_type)
        
        if _prometheus_registry.available:
            try:
                status = 'success' if success else 'failure'
                error_type = error_type or 'none'
                
                if _prometheus_registry.execution_counter:
                    _prometheus_registry.execution_counter.labels(
                        tool=self.tool_name,
                        status=status,
                        error_type=error_type
                    ).inc()
                
                if _prometheus_registry.execution_histogram:
                    _prometheus_registry.execution_histogram.labels(
                        tool=self.tool_name
                    ).observe(execution_time)
                
                if not success and _prometheus_registry.error_counter:
                    _prometheus_registry.error_counter.labels(
                        tool=self.tool_name,
                        error_type=error_type
                    ).inc()
                
            except Exception as e:
                log.debug("prometheus.record_failed error=%s", str(e))
    
    def increment_active(self):
        """Increment active execution count."""
        with self._lock:
            self._active_count += 1
            if _prometheus_registry.available and _prometheus_registry.active_gauge:
                try:
                    _prometheus_registry.active_gauge.labels(tool=self.tool_name).inc()
                except Exception:
                    pass
    
    def decrement_active(self):
        """Decrement active execution count."""
        with self._lock:
            self._active_count = max(0, self._active_count - 1)
            if _prometheus_registry.available and _prometheus_registry.active_gauge:
                try:
                    _prometheus_registry.active_gauge.labels(tool=self.tool_name).dec()
                except Exception:
                    pass


class MetricsManager:
    """Enhanced metrics manager with memory management."""
    
    def __init__(self, max_tools: int = 1000):
        self.tool_metrics: Dict[str, ToolMetrics] = {}
        self.system_metrics = SystemMetrics()
        self.max_tools = max_tools
        self._lock = threading.Lock()
        self._last_cleanup = time.time()
        self._cleanup_interval = 3600
        self.start_time = datetime.now()
    
    def get_tool_metrics(self, tool_name: str) -> ToolMetrics:
        """Get or create tool metrics with cleanup."""
        with self._lock:
            if time.time() - self._last_cleanup > self._cleanup_interval:
                self._cleanup_old_metrics()
            
            if tool_name not in self.tool_metrics:
                if len(self.tool_metrics) >= self.max_tools:
                    self._evict_oldest_metrics()
                
                self.tool_metrics[tool_name] = ToolMetrics(tool_name)
            
            return self.tool_metrics[tool_name]
    
    def record_tool_execution(self, tool_name: str, success: bool, execution_time: float,
                             timed_out: bool = False, error_type: str = None):
        """Record tool execution metrics."""
        tool_metrics = self.get_tool_metrics(tool_name)
        tool_metrics.metrics.record_execution(success, execution_time, timed_out, error_type)
        
        if _prometheus_registry.available:
            try:
                status = 'success' if success else 'failure'
                error_type = error_type or 'none'
                
                if _prometheus_registry.execution_counter:
                    _prometheus_registry.execution_counter.labels(
                        tool=tool_name,
                        status=status,
                        error_type=error_type
                    ).inc()
                
                if _prometheus_registry.execution_histogram:
                    _prometheus_registry.execution_histogram.labels(tool=tool_name).observe(float(execution_time))
                
                if not success and _prometheus_registry.error_counter:
                    _prometheus_registry.error_counter.labels(
                        tool=tool_name,
                        error_type=error_type
                    ).inc()
            except Exception as e:
                log.warning("prometheus.tool_execution_error error=%s", str(e))
        
        self.system_metrics.increment_request_count()
        if not success:
            self.system_metrics.increment_error_count()
    
    def _cleanup_old_metrics(self):
        """Remove metrics for tools not used recently."""
        cutoff_time = datetime.now() - timedelta(hours=24)
        
        to_remove = []
        for name, metrics in self.tool_metrics.items():
            last_time = metrics.metrics.last_execution_time
            if last_time and last_time < cutoff_time:
                to_remove.append(name)
        
        for name in to_remove:
            del self.tool_metrics[name]
        
        if to_remove:
            log.info("metrics.cleanup removed=%d tools", len(to_remove))
        
        self._last_cleanup = time.time()
    
    def _evict_oldest_metrics(self):
        """Evict least recently used metrics."""
        if not self.tool_metrics:
            return
        
        oldest_name = None
        oldest_time = datetime.now()
        
        for name, metrics in self.tool_metrics.items():
            last_time = metrics.metrics.last_execution_time
            if last_time and last_time < oldest_time:
                oldest_time = last_time
                oldest_name = name
        
        if oldest_name:
            del self.tool_metrics[oldest_name]
            log.info("metrics.evicted tool=%s", oldest_name)
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get all metrics statistics."""
        return {
            "system": self.system_metrics.get_stats(),
            "tools": {name: metrics.metrics.get_stats() for name, metrics in self.tool_metrics.items()},
            "prometheus_available": _prometheus_registry.available,
            "collection_start_time": self.start_time.isoformat()
        }
    
    def get_prometheus_metrics(self) -> Optional[str]:
        """Get Prometheus metrics in text format."""
        if _prometheus_registry.available and _prometheus_registry.generate_latest:
            try:
                return _prometheus_registry.generate_latest(_prometheus_registry.registry).decode('utf-8')
            except Exception as e:
                log.error("prometheus.generate_metrics_error error=%s", str(e))
                return None
        return None


class PrometheusMetrics:
    """Legacy compatibility class."""
    
    def __init__(self):
        self.registry = _prometheus_registry.registry if _prometheus_registry.available else None
    
    def get_metrics(self) -> Optional[str]:
        """Get Prometheus metrics."""
        if _prometheus_registry.available and _prometheus_registry.generate_latest:
            try:
                return _prometheus_registry.generate_latest(_prometheus_registry.registry).decode('utf-8')
            except Exception as e:
                log.error("prometheus.generate_metrics_error error=%s", str(e))
                return None
        return None
