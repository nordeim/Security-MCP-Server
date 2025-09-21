# Plan and checklist for a complete alerts.yml

You’ve given enough concrete signal to build a production-ready alerts file tied to your actual metrics. Below is a concise plan, an integrated checklist, and then a drop-in replacement for docker/alerts.yml. I’ve validated expressions against the metric families and labels we confirmed.

---

## Objectives and scope

- **Availability:** Detect target outages and specifically mcp-server downtime.
- **Reliability:** Track failure ratios, timeout rates, and validation errors by tool.
- **Latency:** Watch p95/p99 execution latency from the histogram.
- **Concurrency:** Guard against runaway active executions per tool.
- **Error taxonomy:** Surface error_type spikes (timeout, validation_error, exec_error).
- **Infra health:** Node CPU/memory pressure (node-exporter) and container memory pressure (cAdvisor).
- **Prometheus health:** Self-monitor rule eval issues.

---

## Integrated checklist

- **Metrics confirmation**
  - **Confirmed counters:** mcp_tool_execution_total, mcp_tool_errors_total.
  - **Confirmed histogram:** mcp_tool_execution_seconds (family: _bucket/_sum/_count).
  - **Confirmed gauge:** mcp_tool_active.
  - **Confirmed labels:** tool on all; success, timed_out, error_type on counters (inferred from `.labels` calls and record_tool_execution arguments).
  - **Not confirmed:** circuit breaker and health metrics export (safe to omit; optional placeholder provided).

- **Prometheus config alignment**
  - **Rule file path:** /etc/prometheus/alerts.yml (already mounted read-only).
  - **Jobs present:** mcp-server, node-exporter, cadvisor, prometheus itself (self-scrape).
  - **Reload enabled:** --web.enable-lifecycle set (so POST /-/reload works).

- **Rollout steps**
  1. **Place file:** Save the YAML below as ./docker/alerts.yml.
  2. **Reload:** curl -X POST http://localhost:9091/-/reload (or restart prometheus).
  3. **Verify load:** Prometheus UI → Status → Rules (groups visible, no errors).
  4. **Smoke tests:**
     - **TargetDown:** stop cadvisor; see alert go Pending then Firing.
     - **Failure/timeout:** invoke a tool with invalid args to raise validation_error; observe error alerts.
     - **Latency:** simulate slow tool (add sleep) to push p95 over threshold.
     - **Concurrency:** run parallel executions (if safe) to cross thresholds.
  5. **Tune thresholds:** Adjust marked thresholds after observing baselines.

---

## Drop-in replacement: docker/alerts.yml

```yaml
groups:
  - name: general-availability
    rules:
      - alert: TargetDown
        expr: up == 0
        for: 2m
        labels:
          severity: warning
          category: availability
        annotations:
          summary: "Target down: {{ $labels.job }} on {{ $labels.instance }}"
          description: "Prometheus target {{ $labels.job }} ({{ $labels.instance }}) has been down for 2 minutes."

      - alert: MCPServerDown
        expr: up{job="mcp-server"} == 0
        for: 1m
        labels:
          severity: critical
          category: availability
        annotations:
          summary: "MCP server metrics endpoint down"
          description: "The mcp-server metrics endpoint {{ $labels.instance }} is unreachable for 1 minute."

  - name: mcp-reliability
    rules:
      - alert: MCPFailureRateHigh
        expr: |
          sum by (tool) (rate(mcp_tool_execution_total{success="false"}[10m]))
          /
          clamp_min(sum by (tool) (rate(mcp_tool_execution_total[10m])), 1e-6)
          > 0.2
        for: 10m
        labels:
          severity: warning
          category: reliability
        annotations:
          summary: "High failure rate for {{ $labels.tool }}"
          description: "Failure ratio > 20% over 10m for tool {{ $labels.tool }}."

      - alert: MCPFailureRateSevere
        expr: |
          sum by (tool) (rate(mcp_tool_execution_total{success="false"}[10m]))
          /
          clamp_min(sum by (tool) (rate(mcp_tool_execution_total[10m])), 1e-6)
          > 0.5
        for: 10m
        labels:
          severity: critical
          category: reliability
        annotations:
          summary: "Severe failure rate for {{ $labels.tool }}"
          description: "Failure ratio > 50% over 10m for tool {{ $labels.tool }}."

      - alert: MCPTimeoutRateHigh
        expr: |
          sum by (tool) (rate(mcp_tool_execution_total{timed_out="true"}[10m]))
          /
          clamp_min(sum by (tool) (rate(mcp_tool_execution_total[10m])), 1e-6)
          > 0.1
        for: 10m
        labels:
          severity: warning
          category: reliability
        annotations:
          summary: "Timeouts > 10% for {{ $labels.tool }}"
          description: "Timeout rate exceeds 10% over 10m for tool {{ $labels.tool }}."

      - alert: MCPValidationErrorsObserved
        expr: |
          sum by (tool) (rate(mcp_tool_errors_total{error_type="validation_error"}[10m])) > 0
        for: 10m
        labels:
          severity: info
          category: reliability
        annotations:
          summary: "Input validation errors for {{ $labels.tool }}"
          description: "Sustained validation errors over 10m. Investigate client inputs or configuration."

      - alert: MCPExecutionErrorsSpike
        expr: |
          sum by (tool, error_type) (rate(mcp_tool_errors_total{error_type!~"validation_error|timeout"}[10m])) > 0.05
        for: 10m
        labels:
          severity: warning
          category: reliability
        annotations:
          summary: "Execution errors for {{ $labels.tool }} (type={{ $labels.error_type }})"
          description: "Non-validation, non-timeout errors > 0.05/s over 10m."

  - name: mcp-latency
    rules:
      - alert: MCPLatencyP95High
        expr: |
          histogram_quantile(
            0.95,
            sum by (le, tool) (rate(mcp_tool_execution_seconds_bucket[5m]))
          ) > 5
        for: 10m
        labels:
          severity: warning
          category: performance
        annotations:
          summary: "High p95 latency for {{ $labels.tool }}"
          description: "p95 execution time > 5s for 10m."

      - alert: MCPLatencyP99Severe
        expr: |
          histogram_quantile(
            0.99,
            sum by (le, tool) (rate(mcp_tool_execution_seconds_bucket[5m]))
          ) > 10
        for: 10m
        labels:
          severity: critical
          category: performance
        annotations:
          summary: "Severe p99 latency for {{ $labels.tool }}"
          description: "p99 execution time > 10s for 10m."

  - name: mcp-concurrency
    rules:
      - alert: MCPActiveExecutionsHigh
        expr: mcp_tool_active > 4
        for: 10m
        labels:
          severity: warning
          category: capacity
        annotations:
          summary: "High active executions for {{ $labels.tool }}"
          description: "Active executions > 4 for 10m. Review concurrency limits or workload spikes."

      - alert: MCPActiveExecutionsCritical
        expr: mcp_tool_active > 8
        for: 10m
        labels:
          severity: critical
          category: capacity
        annotations:
          summary: "Critical active executions for {{ $labels.tool }}"
          description: "Active executions > 8 for 10m. Possible runaway concurrency."

  - name: container-observability
    rules:
      - alert: MCPContainerMemoryPressure
        expr: |
          (container_memory_usage_bytes{container="mcp-server"} / container_spec_memory_limit_bytes{container="mcp-server"}) > 0.9
        for: 10m
        labels:
          severity: warning
          category: infrastructure
        annotations:
          summary: "High memory usage in mcp-server container"
          description: "mcp-server memory usage > 90% of limit for 10m."

      - alert: MCPContainerMemoryCritical
        expr: |
          (container_memory_usage_bytes{container="mcp-server"} / container_spec_memory_limit_bytes{container="mcp-server"}) > 0.95
        for: 10m
        labels:
          severity: critical
          category: infrastructure
        annotations:
          summary: "Critical memory usage in mcp-server container"
          description: "mcp-server memory usage > 95% of limit for 10m."

  - name: node-infrastructure
    rules:
      - alert: NodeHighCPU
        expr: 1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) > 0.8
        for: 10m
        labels:
          severity: warning
          category: infrastructure
        annotations:
          summary: "High CPU on {{ $labels.instance }}"
          description: "CPU usage > 80% for 10m."

      - alert: NodeLowMemoryAvailable
        expr: (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) < 0.2
        for: 10m
        labels:
          severity: warning
          category: infrastructure
        annotations:
          summary: "Low memory available on {{ $labels.instance }}"
          description: "Available memory < 20% for 10m."

  - name: prometheus-self
    rules:
      - alert: PrometheusRuleEvaluationErrors
        expr: rate(prometheus_rule_evaluation_failures_total[5m]) > 0
        for: 5m
        labels:
          severity: warning
          category: observability
        annotations:
          summary: "Prometheus rule evaluation errors"
          description: "Rule evaluation failures observed over 5m."

  # Optional (enable if breaker metric exists):
  # - name: mcp-circuit-breaker
  #   rules:
  #     - alert: MCPCircuitBreakerOpenLabeled
  #       expr: mcp_circuit_breaker_state{state="open"} == 1
  #       for: 5m
  #       labels:
  #         severity: critical
  #         category: reliability
  #       annotations:
  #         summary: "Circuit breaker OPEN for {{ $labels.tool }}"
  #         description: "Breaker has been OPEN for 5m for tool {{ $labels.tool }}."
  #
  #     - alert: MCPCircuitBreakerOpenNumeric
  #       expr: mcp_circuit_breaker_state >= 2
  #       for: 5m
  #       labels:
  #         severity: critical
  #         category: reliability
  #       annotations:
  #         summary: "Circuit breaker OPEN (numeric) for {{ $labels.tool }}"
  #         description: "Breaker numeric state indicates OPEN for 5m."
```

---

## Validation pass and assumptions

- **Expressions use confirmed metric names:** mcp_tool_execution_total, mcp_tool_errors_total, mcp_tool_execution_seconds_bucket, mcp_tool_active.
- **Label usage validated:** Aggregations and selectors rely on tool, success, timed_out, error_type — aligned with record_tool_execution and .labels usage you revealed.
- **Division safety:** clamp_min avoids division by zero in low-traffic windows.
- **Absent metrics safety:** Optional circuit breaker group is commented out; if you enable it but the metric doesn’t exist, alerts simply won’t fire (no errors).
- **Infra metrics:** node_* and container_* match node-exporter and cAdvisor for Docker setups. If your cAdvisor exposes working_set instead of usage, swap to container_memory_working_set_bytes in both numerators.

---

## Tuning guidance

- **Latency thresholds:** Start with 5s p95 (warning) and 10s p99 (critical), then adjust per tool based on baselines.
- **Failure/timeout ratios:** 20%/10% are conservative early-warning thresholds; raise/lower based on acceptable SLOs.
- **Concurrency thresholds:** 4/8 are generic; align with MCP_DEFAULT_CONCURRENCY and your hardware limits once observed.

If you want, share a short /metrics sample after a few runs and I’ll tailor thresholds and, if present, enable precise circuit breaker alerts.

https://copilot.microsoft.com/shares/dpNzLJXWt1uGN6yLnJoRP
