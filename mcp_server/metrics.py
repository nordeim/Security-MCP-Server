# metrics.py - Production-ready version

import time
import logging
import threading
from typing import Dict, Any, Optional, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import deque
import weakref

log = logging.getLogger(__name__)

# Singleton registry for Prometheus metrics
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
                from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry
                from prometheus_client.core import REGISTRY
                
                # Use default registry or create new one
                self.registry = REGISTRY
                
                # Check if metrics already exist
                existing_metrics = {m.name for m in self.registry.collect()}
                
                if 'mcp_tool_execution_total' not in existing_metrics:
                    self.execution_counter = Counter(
                        'mcp_tool_execution_total',
                        'Total tool executions',
                        ['tool', 'status', 'error_type'],
                        registry=self.registry
                    )
                else:
                    # Reuse existing metric
                    self.execution_counter = None
                    for collector in self.registry.collect():
                        if collector.name == 'mcp_tool_execution_total':
                            self.execution_counter = collector
                            break
                
                # Similar pattern for other metrics
                self._initialize_other_metrics(existing_metrics)
                
                self._initialized = True
                self.available = True
                log.info("prometheus.initialized successfully")
                
            except ImportError:
                self.available = False
                log.info("prometheus.not_available")
            except Exception as e:
                self.available = False
                log.error("prometheus.initialization_failed error=%s", str(e))
    
    def _initialize_other_metrics(self, existing_metrics: Set[str]):
        """Initialize remaining metrics with duplicate checking."""
        from prometheus_client import Histogram, Gauge, Counter
        
        if 'mcp_tool_execution_seconds' not in existing_metrics:
            self.execution_histogram = Histogram(
                'mcp_tool_execution_seconds',
                'Tool execution time in seconds',
                ['tool'],
                registry=self.registry
            )
        
        if 'mcp_tool_active' not in existing_metrics:
            self.active_gauge = Gauge(
                'mcp_tool_active',
                'Currently active tool executions',
                ['tool'],
                registry=self.registry
            )
        
        if 'mcp_tool_errors_total' not in existing_metrics:
            self.error_counter = Counter(
                'mcp_tool_errors_total',
                'Total tool errors',
                ['tool', 'error_type'],
                registry=self.registry
            )

# Get or create singleton
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
    
    # Sliding window for recent metrics
    recent_executions: deque = field(default_factory=lambda: deque(maxlen=100))
    
    def record_execution(self, success: bool, execution_time: float, 
                         timed_out: bool = False, error_type: Optional[str] = None):
        """Thread-safe execution recording."""
        with self._lock:
            execution_time = max(0.0, float(execution_time))
            
            # Update counters
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
            
            # Add to recent executions
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
            
            # Calculate percentiles from recent executions
            recent_times = sorted([
                e["execution_time"] for e in self.recent_executions
            ])
            
            p50 = recent_times[len(recent_times) // 2] if recent_times else 0.0
            p95 = recent_times[int(len(recent_times) * 0.95)] if recent_times else 0.0
            p99 = recent_times[int(len(recent_times) * 0.99)] if recent_times else 0.0
            
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
        # Update internal metrics
        self.metrics.record_execution(success, execution_time, timed_out, error_type)
        
        # Update Prometheus metrics if available
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
        
        # Cleanup old metrics periodically
        self._last_cleanup = time.time()
        self._cleanup_interval = 3600  # 1 hour
    
    def get_tool_metrics(self, tool_name: str) -> ToolMetrics:
        """Get or create tool metrics with cleanup."""
        with self._lock:
            # Periodic cleanup
            if time.time() - self._last_cleanup > self._cleanup_interval:
                self._cleanup_old_metrics()
            
            if tool_name not in self.tool_metrics:
                # Check if we're at capacity
                if len(self.tool_metrics) >= self.max_tools:
                    self._evict_oldest_metrics()
                
                self.tool_metrics[tool_name] = ToolMetrics(tool_name)
            
            return self.tool_metrics[tool_name]
    
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
        
        # Find oldest
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
