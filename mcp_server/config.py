# File: config.py
"""
Configuration management system for MCP server.
Production-ready implementation with validation, hot-reload, and sensitive data handling.
"""
import os
import logging
import json
import yaml
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict

# Pydantic for configuration validation
try:
    from pydantic import BaseModel, Field, validator
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    # Fallback validation without Pydantic
    class BaseModel:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
        
        def dict(self):
            return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}
    
    Field = lambda default=None, **kwargs: default
    def validator(field_name, *args, **kwargs):
        def decorator(func):
            return func
        return decorator

log = logging.getLogger(__name__)

@dataclass
class DatabaseConfig:
    """Database configuration."""
    url: str = ""
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 3600

@dataclass
class SecurityConfig:
    """Security configuration."""
    allowed_targets: List[str] = field(default_factory=lambda: ["RFC1918", ".lab.internal"])
    max_args_length: int = 2048
    max_output_size: int = 1048576
    timeout_seconds: int = 300
    concurrency_limit: int = 2

@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    expected_exceptions: List[str] = field(default_factory=lambda: ["Exception"])
    half_open_success_threshold: int = 1

@dataclass
class HealthConfig:
    """Health check configuration."""
    check_interval: float = 30.0
    cpu_threshold: float = 80.0
    memory_threshold: float = 80.0
    disk_threshold: float = 80.0
    dependencies: List[str] = field(default_factory=list)
    timeout: float = 10.0

@dataclass
class MetricsConfig:
    """Metrics configuration."""
    enabled: bool = True
    prometheus_enabled: bool = True
    prometheus_port: int = 9090
    collection_interval: float = 15.0

@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file_path: Optional[str] = None
    max_file_size: int = 10485760  # 10MB
    backup_count: int = 5

@dataclass
class ServerConfig:
    """Server configuration."""
    host: str = "0.0.0.0"
    port: int = 8080
    transport: str = "stdio"  # "stdio" or "http"
    workers: int = 1
    max_connections: int = 100
    shutdown_grace_period: float = 30.0

@dataclass
class ToolConfig:
    """Tool-specific configuration."""
    include_patterns: List[str] = field(default_factory=lambda: ["*"])
    exclude_patterns: List[str] = field(default_factory=list)
    default_timeout: int = 300
    default_concurrency: int = 2

class MCPConfig:
    """
    Main MCP configuration class with validation and hot-reload support.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path
        self.last_modified = None
        self._config_data = {}
        
        # Initialize with defaults
        self.database = DatabaseConfig()
        self.security = SecurityConfig()
        self.circuit_breaker = CircuitBreakerConfig()
        self.health = HealthConfig()
        self.metrics = MetricsConfig()
        self.logging = LoggingConfig()
        self.server = ServerConfig()
        self.tool = ToolConfig()
        
        # Load configuration
        self.load_config()
    
    def load_config(self):
        """Load configuration from file and environment variables."""
        # Start with defaults
        config_data = self._get_defaults()
        
        # Load from file if specified
        if self.config_path and os.path.exists(self.config_path):
            config_data.update(self._load_from_file(self.config_path))
        
        # Override with environment variables
        config_data.update(self._load_from_environment())
        
        # Validate and set configuration
        self._validate_and_set_config(config_data)
        
        # Update last modified time
        if self.config_path:
            try:
                self.last_modified = os.path.getmtime(self.config_path)
            except OSError:
                self.last_modified = None
    
    def _get_defaults(self) -> Dict[str, Any]:
        """Get default configuration values."""
        return {
            "database": asdict(DatabaseConfig()),
            "security": asdict(SecurityConfig()),
            "circuit_breaker": asdict(CircuitBreakerConfig()),
            "health": asdict(HealthConfig()),
            "metrics": asdict(MetricsConfig()),
            "logging": asdict(LoggingConfig()),
            "server": asdict(ServerConfig()),
            "tool": asdict(ToolConfig())
        }
    
    def _load_from_file(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from file (JSON or YAML)."""
        try:
            file_path = Path(config_path)
            
            if not file_path.exists():
                log.warning("config.file_not_found path=%s", config_path)
                return {}
            
            with open(file_path, 'r', encoding='utf-8') as f:
                if file_path.suffix.lower() in ['.yaml', '.yml']:
                    return yaml.safe_load(f) or {}
                else:
                    return json.load(f) or {}
        
        except Exception as e:
            log.error("config.file_load_failed path=%s error=%s", config_path, str(e))
            return {}
    
    def _load_from_environment(self) -> Dict[str, Any]:
        """Load configuration from environment variables."""
        config = {}
        
        # Environment variable mappings
        env_mappings = {
            'MCP_DATABASE_URL': ('database', 'url'),
            'MCP_DATABASE_POOL_SIZE': ('database', 'pool_size'),
            'MCP_SECURITY_MAX_ARGS_LENGTH': ('security', 'max_args_length'),
            'MCP_SECURITY_TIMEOUT_SECONDS': ('security', 'timeout_seconds'),
            'MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD': ('circuit_breaker', 'failure_threshold'),
            'MCP_CIRCUIT_BREAKER_RECOVERY_TIMEOUT': ('circuit_breaker', 'recovery_timeout'),
            'MCP_HEALTH_CHECK_INTERVAL': ('health', 'check_interval'),
            'MCP_HEALTH_CPU_THRESHOLD': ('health', 'cpu_threshold'),
            'MCP_METRICS_ENABLED': ('metrics', 'enabled'),
            'MCP_METRICS_PROMETHEUS_PORT': ('metrics', 'prometheus_port'),
            'MCP_LOGGING_LEVEL': ('logging', 'level'),
            'MCP_LOGGING_FILE_PATH': ('logging', 'file_path'),
            'MCP_SERVER_HOST': ('server', 'host'),
            'MCP_SERVER_PORT': ('server', 'port'),
            'MCP_SERVER_TRANSPORT': ('server', 'transport'),
            'MCP_TOOL_DEFAULT_TIMEOUT': ('tool', 'default_timeout'),
        }
        
        for env_var, (section, key) in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                if section not in config:
                    config[section] = {}
                
                # Type conversion
                if key in ['pool_size', 'max_args_length', 'timeout_seconds', 'failure_threshold', 
                          'prometheus_port', 'default_timeout']:
                    try:
                        config[section][key] = int(value)
                    except ValueError:
                        log.warning("config.invalid_int env_var=%s value=%s", env_var, value)
                elif key in ['recovery_timeout', 'check_interval', 'cpu_threshold']:
                    try:
                        config[section][key] = float(value)
                    except ValueError:
                        log.warning("config.invalid_float env_var=%s value=%s", env_var, value)
                elif key in ['enabled']:
                    config[section][key] = value.lower() in ['true', '1', 'yes', 'on']
                else:
                    config[section][key] = value
        
        return config
    
    def _validate_and_set_config(self, config_data: Dict[str, Any]):
        """Validate and set configuration values."""
        try:
            # Validate database config
            if 'database' in config_data:
                db_config = config_data['database']
                self.database.url = str(db_config.get('url', self.database.url))
                self.database.pool_size = max(1, int(db_config.get('pool_size', self.database.pool_size)))
                self.database.max_overflow = max(0, int(db_config.get('max_overflow', self.database.max_overflow)))
            
            # Validate security config
            if 'security' in config_data:
                sec_config = config_data['security']
                self.security.max_args_length = max(1, int(sec_config.get('max_args_length', self.security.max_args_length)))
                self.security.max_output_size = max(1, int(sec_config.get('max_output_size', self.security.max_output_size)))
                self.security.timeout_seconds = max(1, int(sec_config.get('timeout_seconds', self.security.timeout_seconds)))
                self.security.concurrency_limit = max(1, int(sec_config.get('concurrency_limit', self.security.concurrency_limit)))
            
            # Validate circuit breaker config
            if 'circuit_breaker' in config_data:
                cb_config = config_data['circuit_breaker']
                self.circuit_breaker.failure_threshold = max(1, int(cb_config.get('failure_threshold', self.circuit_breaker.failure_threshold)))
                self.circuit_breaker.recovery_timeout = max(1.0, float(cb_config.get('recovery_timeout', self.circuit_breaker.recovery_timeout)))
            
            # Validate health config
            if 'health' in config_data:
                health_config = config_data['health']
                self.health.check_interval = max(5.0, float(health_config.get('check_interval', self.health.check_interval)))
                self.health.cpu_threshold = max(0.0, min(100.0, float(health_config.get('cpu_threshold', self.health.cpu_threshold))))
                self.health.memory_threshold = max(0.0, min(100.0, float(health_config.get('memory_threshold', self.health.memory_threshold))))
                self.health.disk_threshold = max(0.0, min(100.0, float(health_config.get('disk_threshold', self.health.disk_threshold))))
            
            # Validate metrics config
            if 'metrics' in config_data:
                metrics_config = config_data['metrics']
                self.metrics.enabled = bool(metrics_config.get('enabled', self.metrics.enabled))
                self.metrics.prometheus_enabled = bool(metrics_config.get('prometheus_enabled', self.metrics.prometheus_enabled))
                self.metrics.prometheus_port = max(1, min(65535, int(metrics_config.get('prometheus_port', self.metrics.prometheus_port))))
            
            # Validate logging config
            if 'logging' in config_data:
                logging_config = config_data['logging']
                self.logging.level = str(logging_config.get('level', self.logging.level)).upper()
                self.logging.file_path = logging_config.get('file_path') if logging_config.get('file_path') else None
            
            # Validate server config
            if 'server' in config_data:
                server_config = config_data['server']
                self.server.host = str(server_config.get('host', self.server.host))
                self.server.port = max(1, min(65535, int(server_config.get('port', self.server.port))))
                self.server.transport = str(server_config.get('transport', self.server.transport)).lower()
                self.server.workers = max(1, int(server_config.get('workers', self.server.workers)))
            
            # Validate tool config
            if 'tool' in config_data:
                tool_config = config_data['tool']
                self.tool.default_timeout = max(1, int(tool_config.get('default_timeout', self.tool.default_timeout)))
                self.tool.default_concurrency = max(1, int(tool_config.get('default_concurrency', self.tool.default_concurrency)))
            
            # Store raw config data
            self._config_data = config_data
            
            log.info("config.loaded_successfully")
            
        except Exception as e:
            log.error("config.validation_failed error=%s", str(e))
            # Keep defaults if validation fails
    
    def check_for_changes(self) -> bool:
        """Check if configuration file has been modified."""
        if not self.config_path:
            return False
        
        try:
            current_mtime = os.path.getmtime(self.config_path)
            if current_mtime != self.last_modified:
                self.last_modified = current_mtime
                return True
        except OSError:
            pass
        
        return False
    
    def reload_config(self):
        """Reload configuration if file has changed."""
        if self.check_for_changes():
            log.info("config.reloading_changes_detected")
            self.load_config()
            return True
        return False
    
    def get_sensitive_keys(self) -> List[str]:
        """Get list of sensitive configuration keys that should be redacted."""
        return [
            'database.url',
            'security.api_key',
            'security.secret_key',
            'logging.file_path'  # May contain sensitive paths
        ]
    
    def redact_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Redact sensitive data from configuration for logging."""
        sensitive_keys = self.get_sensitive_keys()
        redacted_data = data.copy()
        
        for key in sensitive_keys:
            if '.' in key:
                section, subkey = key.split('.', 1)
                if section in redacted_data and isinstance(redacted_data[section], dict):
                    if subkey in redacted_data[section]:
                        redacted_data[section][subkey] = "***REDACTED***"
            else:
                if key in redacted_data:
                    redacted_data[key] = "***REDACTED***"
        
        return redacted_data
    
    def to_dict(self, redact_sensitive: bool = True) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        config_dict = {
            'database': asdict(self.database),
            'security': asdict(self.security),
            'circuit_breaker': asdict(self.circuit_breaker),
            'health': asdict(self.health),
            'metrics': asdict(self.metrics),
            'logging': asdict(self.logging),
            'server': asdict(self.server),
            'tool': asdict(self.tool)
        }
        
        if redact_sensitive:
            config_dict = self.redact_sensitive_data(config_dict)
        
        return config_dict
    
    def save_config(self, file_path: Optional[str] = None):
        """Save current configuration to file."""
        save_path = file_path or self.config_path
        if not save_path:
            raise ValueError("No config file path specified")
        
        try:
            config_dict = self.to_dict(redact_sensitive=False)
            
            file_path_obj = Path(save_path)
            file_path_obj.parent.mkdir(parents=True, exist_ok=True)
            
            with open(file_path_obj, 'w', encoding='utf-8') as f:
                if file_path_obj.suffix.lower() in ['.yaml', '.yml']:
                    yaml.dump(config_dict, f, default_flow_style=False, indent=2)
                else:
                    json.dump(config_dict, f, indent=2)
            
            log.info("config.saved_successfully path=%s", save_path)
            
        except Exception as e:
            log.error("config.save_failed path=%s error=%s", save_path, str(e))
            raise
    
    def get_section(self, section_name: str) -> Any:
        """Get a specific configuration section."""
        return getattr(self, section_name, None)
    
    def get_value(self, section_name: str, key: str, default=None):
        """Get a specific configuration value."""
        section = self.get_section(section_name)
        if section and hasattr(section, key):
            return getattr(section, key)
        return default
    
    def __str__(self) -> str:
        """String representation with sensitive data redacted."""
        config_dict = self.to_dict(redact_sensitive=True)
        return json.dumps(config_dict, indent=2)

# Global configuration instance
_config_instance = None

def get_config(config_path: Optional[str] = None) -> MCPConfig:
    """Get the global configuration instance."""
    global _config_instance
    if _config_instance is None:
        _config_instance = MCPConfig(config_path)
    return _config_instance

def reload_config():
    """Reload the global configuration."""
    global _config_instance
    if _config_instance is not None:
        _config_instance.reload_config()
