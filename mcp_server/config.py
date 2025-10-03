"""
Configuration management system for MCP server.
Production-ready implementation with validation, hot-reload, and sensitive data handling.
Enhanced with all security and reliability fixes.
"""
import os
import logging
import json
import yaml
import threading
import socket
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from contextlib import contextmanager

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
    """Security configuration with enhanced validation."""
    allowed_targets: List[str] = field(default_factory=lambda: ["RFC1918", ".lab.internal"])
    max_args_length: int = 2048
    max_output_size: int = 1048576
    timeout_seconds: int = 300
    concurrency_limit: int = 2
    allow_intrusive: bool = False  # Added for intrusive scan control


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
    max_file_size: int = 10485760
    backup_count: int = 5


@dataclass
class ServerConfig:
    """Server configuration."""
    host: str = "0.0.0.0"
    port: int = 8080
    transport: str = "stdio"
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
    Enhanced with security fixes and improved validation.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path
        self.last_modified = None
        self._config_data = {}
        self._lock = threading.RLock()
        
        self.database = DatabaseConfig()
        self.security = SecurityConfig()
        self.circuit_breaker = CircuitBreakerConfig()
        self.health = HealthConfig()
        self.metrics = MetricsConfig()
        self.logging = LoggingConfig()
        self.server = ServerConfig()
        self.tool = ToolConfig()
        
        self.load_config()
    
    @contextmanager
    def _config_lock(self):
        """Context manager for thread-safe config access."""
        self._lock.acquire()
        try:
            yield
        finally:
            self._lock.release()
    
    def load_config(self):
        """Thread-safe configuration loading."""
        with self._config_lock():
            try:
                config_data = self._get_defaults()
                
                if self.config_path and os.path.exists(self.config_path):
                    file_data = self._load_from_file(self.config_path)
                    config_data = self._deep_merge(config_data, file_data)
                
                env_data = self._load_from_environment()
                config_data = self._deep_merge(config_data, env_data)
                
                self._validate_config(config_data)
                self._apply_config(config_data)
                
                if self.config_path and os.path.exists(self.config_path):
                    self.last_modified = os.path.getmtime(self.config_path)
                
                log.info("config.loaded_successfully")
                
            except Exception as e:
                log.error("config.load_failed error=%s", str(e))
                if not hasattr(self, 'server'):
                    self._initialize_defaults()
    
    def _initialize_defaults(self):
        """Initialize with default configuration."""
        self.database = DatabaseConfig()
        self.security = SecurityConfig()
        self.circuit_breaker = CircuitBreakerConfig()
        self.health = HealthConfig()
        self.metrics = MetricsConfig()
        self.logging = LoggingConfig()
        self.server = ServerConfig()
        self.tool = ToolConfig()
    
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
        
        env_mappings = {
            'MCP_DATABASE_URL': ('database', 'url'),
            'MCP_DATABASE_POOL_SIZE': ('database', 'pool_size'),
            'MCP_SECURITY_MAX_ARGS_LENGTH': ('security', 'max_args_length'),
            'MCP_SECURITY_TIMEOUT_SECONDS': ('security', 'timeout_seconds'),
            'MCP_SECURITY_CONCURRENCY_LIMIT': ('security', 'concurrency_limit'),
            'MCP_SECURITY_ALLOW_INTRUSIVE': ('security', 'allow_intrusive'),
            'MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD': ('circuit_breaker', 'failure_threshold'),
            'MCP_CIRCUIT_BREAKER_RECOVERY_TIMEOUT': ('circuit_breaker', 'recovery_timeout'),
            'MCP_HEALTH_CHECK_INTERVAL': ('health', 'check_interval'),
            'MCP_HEALTH_CPU_THRESHOLD': ('health', 'cpu_threshold'),
            'MCP_HEALTH_MEMORY_THRESHOLD': ('health', 'memory_threshold'),
            'MCP_HEALTH_DISK_THRESHOLD': ('health', 'disk_threshold'),
            'MCP_METRICS_ENABLED': ('metrics', 'enabled'),
            'MCP_METRICS_PROMETHEUS_PORT': ('metrics', 'prometheus_port'),
            'MCP_LOGGING_LEVEL': ('logging', 'level'),
            'MCP_LOGGING_FILE_PATH': ('logging', 'file_path'),
            'MCP_SERVER_HOST': ('server', 'host'),
            'MCP_SERVER_PORT': ('server', 'port'),
            'MCP_SERVER_TRANSPORT': ('server', 'transport'),
            'MCP_SERVER_SHUTDOWN_GRACE_PERIOD': ('server', 'shutdown_grace_period'),
            'MCP_TOOL_DEFAULT_TIMEOUT': ('tool', 'default_timeout'),
            'MCP_TOOL_DEFAULT_CONCURRENCY': ('tool', 'default_concurrency'),
        }
        
        for env_var, (section, key) in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                if section not in config:
                    config[section] = {}
                
                if key in ['pool_size', 'max_args_length', 'timeout_seconds', 'concurrency_limit',
                          'failure_threshold', 'prometheus_port', 'default_timeout', 'default_concurrency',
                          'port', 'workers', 'max_connections']:
                    try:
                        config[section][key] = int(value)
                    except ValueError:
                        log.warning("config.invalid_int env_var=%s value=%s", env_var, value)
                elif key in ['recovery_timeout', 'check_interval', 'cpu_threshold', 'memory_threshold',
                            'disk_threshold', 'timeout', 'collection_interval', 'shutdown_grace_period']:
                    try:
                        config[section][key] = float(value)
                    except ValueError:
                        log.warning("config.invalid_float env_var=%s value=%s", env_var, value)
                elif key in ['enabled', 'prometheus_enabled', 'allow_intrusive']:
                    config[section][key] = value.lower() in ['true', '1', 'yes', 'on']
                else:
                    config[section][key] = value
        
        return config
    
    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """Enhanced deep merge configuration dictionaries with list handling."""
        result = base.copy()
        for key, value in override.items():
            if key in result:
                if isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = self._deep_merge(result[key], value)
                elif isinstance(result[key], list) and isinstance(value, list):
                    # For lists, replace instead of extend to maintain control
                    result[key] = value
                else:
                    result[key] = value
            else:
                result[key] = value
        return result
    
    def _validate_config(self, config_data: Dict[str, Any]):
        """Comprehensive configuration validation."""
        validators = {
            'database': self._validate_database_config,
            'security': self._validate_security_config,
            'circuit_breaker': self._validate_circuit_breaker_config,
            'health': self._validate_health_config,
            'metrics': self._validate_metrics_config,
            'server': self._validate_server_config,
            'tool': self._validate_tool_config,
        }
        
        for section, validator in validators.items():
            if section in config_data:
                validator(config_data[section])
    
    def _validate_database_config(self, config: Dict):
        """Validate database configuration."""
        if 'pool_size' in config:
            config['pool_size'] = max(1, min(100, int(config['pool_size'])))
        if 'max_overflow' in config:
            config['max_overflow'] = max(0, min(100, int(config['max_overflow'])))
        if 'pool_timeout' in config:
            config['pool_timeout'] = max(1, min(300, int(config['pool_timeout'])))
        if 'pool_recycle' in config:
            config['pool_recycle'] = max(60, min(7200, int(config['pool_recycle'])))
    
    def _validate_security_config(self, config: Dict):
        """Enhanced security configuration validation."""
        if 'max_args_length' in config:
            config['max_args_length'] = max(1, min(10240, int(config['max_args_length'])))
        if 'max_output_size' in config:
            config['max_output_size'] = max(1024, min(10485760, int(config['max_output_size'])))
        if 'timeout_seconds' in config:
            config['timeout_seconds'] = max(1, min(3600, int(config['timeout_seconds'])))
        if 'concurrency_limit' in config:
            config['concurrency_limit'] = max(1, min(100, int(config['concurrency_limit'])))
        
        # Validate allowed targets
        if 'allowed_targets' in config:
            valid_patterns = {'RFC1918', 'loopback'}
            validated_targets = []
            for target in config['allowed_targets']:
                if target in valid_patterns or (isinstance(target, str) and target.startswith('.')):
                    validated_targets.append(target)
                else:
                    log.warning("config.invalid_target_pattern pattern=%s", target)
            config['allowed_targets'] = validated_targets if validated_targets else ['RFC1918']
    
    def _validate_circuit_breaker_config(self, config: Dict):
        """Validate circuit breaker configuration."""
        if 'failure_threshold' in config:
            config['failure_threshold'] = max(1, min(100, int(config['failure_threshold'])))
        if 'recovery_timeout' in config:
            config['recovery_timeout'] = max(1.0, min(600.0, float(config['recovery_timeout'])))
        if 'half_open_success_threshold' in config:
            config['half_open_success_threshold'] = max(1, min(10, int(config['half_open_success_threshold'])))
    
    def _validate_health_config(self, config: Dict):
        """Validate health configuration."""
        if 'check_interval' in config:
            config['check_interval'] = max(5.0, min(300.0, float(config['check_interval'])))
        for threshold_key in ['cpu_threshold', 'memory_threshold', 'disk_threshold']:
            if threshold_key in config:
                config[threshold_key] = max(0.0, min(100.0, float(config[threshold_key])))
        if 'timeout' in config:
            config['timeout'] = max(1.0, min(60.0, float(config['timeout'])))
    
    def _validate_metrics_config(self, config: Dict):
        """Validate metrics configuration."""
        if 'prometheus_port' in config:
            config['prometheus_port'] = max(1, min(65535, int(config['prometheus_port'])))
        if 'collection_interval' in config:
            config['collection_interval'] = max(5.0, min(300.0, float(config['collection_interval'])))
    
    def _validate_server_config(self, config: Dict):
        """Enhanced server configuration validation with proper host checking."""
        if 'port' in config:
            port = int(config['port'])
            if not (1 <= port <= 65535):
                raise ValueError(f"Invalid port: {port}")
            config['port'] = port
        
        if 'transport' in config:
            transport = str(config['transport']).lower()
            if transport not in ['stdio', 'http']:
                raise ValueError(f"Invalid transport: {transport}")
            config['transport'] = transport
        
        if 'host' in config:
            if not self._validate_host(config['host']):
                raise ValueError(f"Invalid host: {config['host']}")
        
        if 'workers' in config:
            config['workers'] = max(1, min(16, int(config['workers'])))
        if 'max_connections' in config:
            config['max_connections'] = max(1, min(10000, int(config['max_connections'])))
        if 'shutdown_grace_period' in config:
            config['shutdown_grace_period'] = max(0.0, min(300.0, float(config['shutdown_grace_period'])))
    
    def _validate_host(self, host: str) -> bool:
        """Validate host without resource leaks."""
        try:
            # Try to parse as IP address first
            socket.inet_aton(host)
            return True
        except socket.error:
            pass
        
        # Use getaddrinfo which handles cleanup properly
        try:
            socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            return True
        except (socket.gaierror, socket.error):
            return False
    
    def _validate_tool_config(self, config: Dict):
        """Validate tool configuration."""
        if 'default_timeout' in config:
            config['default_timeout'] = max(1, min(3600, int(config['default_timeout'])))
        if 'default_concurrency' in config:
            config['default_concurrency'] = max(1, min(100, int(config['default_concurrency'])))
    
    def _apply_config(self, config_data: Dict[str, Any]):
        """Apply validated configuration."""
        for section_name in ['database', 'security', 'circuit_breaker', 'health', 
                             'metrics', 'logging', 'server', 'tool']:
            if section_name in config_data:
                section_obj = getattr(self, section_name)
                for key, value in config_data[section_name].items():
                    setattr(section_obj, key, value)
        
        self._config_data = config_data
    
    def check_for_changes(self) -> bool:
        """Check if configuration file has been modified."""
        if not self.config_path:
            return False
        
        try:
            current_mtime = os.path.getmtime(self.config_path)
            if current_mtime != self.last_modified:
                return True
        except OSError:
            pass
        
        return False
    
    def reload_config(self) -> bool:
        """Thread-safe configuration reload."""
        with self._config_lock():
            if self.check_for_changes():
                log.info("config.reloading_changes_detected")
                backup = self.to_dict(redact_sensitive=False)
                try:
                    self.load_config()
                    return True
                except Exception as e:
                    log.error("config.reload_failed error=%s reverting", str(e))
                    self._apply_config(backup)
                    return False
        return False
    
    def get_sensitive_keys(self) -> List[str]:
        """Get list of sensitive configuration keys."""
        return [
            'database.url',
            'security.api_key',
            'security.secret_key',
            'security.token'
        ]
    
    def redact_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Redact sensitive data from configuration."""
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


_config_instance = None
_config_lock = threading.Lock()


def get_config(config_path: Optional[str] = None, force_new: bool = False) -> MCPConfig:
    """Get configuration instance with testing support."""
    global _config_instance
    
    with _config_lock:
        if force_new or _config_instance is None:
            config_path = config_path or os.getenv('MCP_CONFIG_FILE')
            _config_instance = MCPConfig(config_path)
        return _config_instance


def reset_config():
    """Reset configuration (for testing)."""
    global _config_instance
    with _config_lock:
        _config_instance = None
