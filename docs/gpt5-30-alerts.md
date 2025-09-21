# Docker compose review and alert plan

Your compose stack is well-structured and lines up with your prometheus.yml assumptions. Key checks:

- Networks and reachability:
  - Prometheus joins mcp-internal, as do mcp-server, node-exporter, and cadvisor. Service discovery by DNS names in your prometheus.yml targets (mcp-server:9090, node-exporter:9100, cadvisor:8080) will work. No depends_on is required because scraping is tolerant of delayed targets.  
- Config mounts:
  - Prometheus mounts ./docker/prometheus.yml to /etc/prometheus/prometheus.yml:ro and ./docker/alerts.yml to /etc/prometheus/alerts.yml:ro, matching rule_files in your prometheus.yml.  
- Ports:
  - mcp-server exposes 9090 for metrics; mapped to host but scraping is internal via service name, which is fine. Prometheus is published on host 9091:9090 for UI.  
- Labels:
  - prometheus.io/* labels on services don’t affect scraping because you’re using static_configs, not docker_sd; harmless to keep.  
- Alerting delivery:
  - You haven’t deployed Alertmanager. Alerts will be visible in the Prometheus UI but not routed until Alertmanager is added and configured in alerting.alertmanagers.  
- Grafana metrics:
  - Your prometheus.yml scrapes grafana:3000/metrics. Grafana may require GF_METRICS_ENABLED=true; if you see 404 or empty scrape, either enable it or remove that job.  

The MCP server exposes Prometheus-friendly metrics such as mcp_tool_execution_total, mcp_tool_execution_seconds, mcp_circuit_breaker_state, and mcp_health_check_status, and implements circuit breakers and health checks; we’ll leverage those for targeted alerts.

---

# Proposed alert objectives

- Core availability:
  - Detect any target down and specifically mcp-server down.
- MCP-specific reliability:
  - Detect circuit breakers stuck open.
  - Catch elevated tool failure ratios and abnormal latency.
  - Surface degraded/unhealthy health checks.
- Infrastructure signals:
  - Node CPU/memory pressure from node-exporter.
  - Container resource pressure from cAdvisor (optional but useful).

These map directly to metrics the project documents emitting (tool executions, circuit breaker state, health checks) and standard node/cAdvisor metrics.

---

# docker/alerts.yml

Save the following as docker/alerts.yml. It’s safe to start with; tune thresholds once you see real traffic.

```yaml
groups:
  - name: general-availability
    rules:
      - alert: PrometheusTargetDown
        expr: up == 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Target down: {{ $labels.job }} on {{ $labels.instance }}"
          description: "Prometheus target {{ $labels.job }} ({{ $labels.instance }}) has been down for 2 minutes."

      - alert: MCPServerDown
        expr: up{job="mcp-server"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "MCP server metrics endpoint down"
          description: "The mcp-server metrics endpoint {{ $labels.instance }} is not reachable for 1 minute."

  - name: mcp-reliability
    rules:
      - alert: MCPCircuitBreakerOpen
        # If circuit breaker state is exported as labels (recommended)
        expr: mcp_circuit_breaker_state{state="open"} == 1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Circuit breaker OPEN for {{ $labels.tool }}"
          description: "Circuit breaker is OPEN for tool {{ $labels.tool }} for over 5 minutes. Persistent failures are blocking executions."

      - alert: MCPCircuitBreakerOpenNumeric
        # Fallback if state is exported as a numeric gauge (e.g., 0=closed,1=half_open,2=open)
        expr: mcp_circuit_breaker_state >= 2
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Circuit breaker OPEN (numeric) for {{ $labels.tool }}"
          description: "Circuit breaker metric indicates OPEN state for {{ $labels.tool }} for 5 minutes."

      - alert: MCPHealthDegraded
        # If health is exported with a status label; adjust label name/values to match implementation
        expr: mcp_health_check_status{status=~"degraded|unhealthy"} == 1
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "MCP health degraded on {{ $labels.check }}"
          description: "Health check {{ $labels.check }} reports {{ $labels.status }} for 3 minutes."

      - alert: MCPHighFailureRate
        # Failure ratio > 20% over 10m; requires success="true/false" label on counter
        expr: |
          sum by (tool)(
            rate(mcp_tool_execution_total{success="false"}[10m])
          )
          /
          sum by (tool)(
            rate(mcp_tool_execution_total[10m])
          ) > 0.2
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High failure rate for {{ $labels.tool }}"
          description: "Failure ratio > 20% for tool {{ $labels.tool }} over the last 10m."

      - alert: MCPLatencyP95High
        # p95 execution time > 5s across all tools; tune threshold for your environment
        expr: |
          histogram_quantile(
            0.95,
            sum by (le) (rate(mcp_tool_execution_seconds_bucket[5m]))
          ) > 5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High MCP execution latency (p95)"
          description: "The p95 execution time across tools exceeds 5s for 10m."

  - name: node-infrastructure
    rules:
      - alert: NodeHighCPU
        expr: 1 - avg by (instance)(rate(node_cpu_seconds_total{mode="idle"}[5m])) > 0.8
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High CPU on {{ $labels.instance }}"
          description: "CPU usage > 80% for 10 minutes."

      - alert: NodeLowMemoryAvailable
        expr: (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) < 0.2
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Low memory available on {{ $labels.instance }}"
          description: "Available memory < 20% for 10 minutes."

  - name: container-observability
    rules:
      - alert: ContainerMemoryThrottling
        expr: |
          (container_memory_usage_bytes{container!=""} / container_spec_memory_limit_bytes{container!=""})
            > 0.9
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High container memory usage: {{ $labels.container }}"
          description: "Container {{ $labels.container }} memory usage > 90% of limit for 10 minutes."

      - alert: MCPContainerHighCPU
        expr: |
          rate(container_cpu_usage_seconds_total{container="mcp-server"}[5m]) > 0.8
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage in mcp-server container"
          description: "mcp-server CPU usage > 80% core-seconds/s for 10 minutes. Consider resource tuning."

  - name: prometheus-self
    rules:
      - alert: PrometheusRuleEvaluationErrors
        expr: rate(prometheus_rule_evaluation_failures_total[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Prometheus rule evaluation errors"
          description: "Prometheus is encountering rule evaluation failures."
```

Notes:
- The MCP alerts assume the documented metrics exist: mcp_tool_execution_total (with success label), mcp_tool_execution_seconds_bucket, mcp_circuit_breaker_state, mcp_health_check_status. Adjust label names if your implementation differs; these names align with the project docs and metrics overview.
- If Grafana metrics scraping isn’t enabled, remove the Grafana job or set GF_METRICS_ENABLED=true to avoid noisy target-down alerts.

---

# Rollout checklist

- Place the file at ./docker/alerts.yml and keep your rule_files path as /etc/prometheus/alerts.yml.
- Reload Prometheus:
  - POST to http://localhost:9091/-/reload from your host, or restart the container. You’ve enabled --web.enable-lifecycle, so reload will work.
- Validate:
  - Prometheus UI > Status > Rules: confirm groups loaded.
  - Prometheus UI > Alerts: ensure alerts show as Inactive initially, then trigger a quick test (e.g., stop cadvisor) to see Pending/Firing.
- Next step (optional but recommended):
  - Add Alertmanager service and wire it via alerting.alertmanagers, plus routes/receivers for Slack/Email/PagerDuty to make these alerts actionable.

If you want, I can tailor the expressions precisely to your actual metric names by sampling /metrics from mcp-server and tightening the failure/latency thresholds based on observed baselines.

https://copilot.microsoft.com/shares/eCNwV4RfSfnxjgwayTsMG

---
Great question — let’s slow down and map this carefully. You want to know whether your `prometheus.yml` aligns with what the `docker-compose.yml` expects, especially in light of the alert rules mount you saw earlier.

---

## 🔍 Step 1: What `docker-compose.yml` usually does
In a typical Prometheus + Docker Compose setup, the compose file:

- Mounts your **Prometheus config** into the container:
  ```yaml
  - ./docker/prometheus.yml:/etc/prometheus/prometheus.yml
  ```
- Mounts your **alert rules file(s)** into the container:
  ```yaml
  - ./docker/alerts.yml:/etc/prometheus/alerts.yml
  ```
- Starts Prometheus with:
  ```yaml
  command:
    - '--config.file=/etc/prometheus/prometheus.yml'
    - '--storage.tsdb.path=/prometheus'
  ```

So the container expects:
- `/etc/prometheus/prometheus.yml` → your main config (the one you pasted).
- `/etc/prometheus/alerts.yml` → your rules file (referenced inside `prometheus.yml`).

---

## 🔍 Step 2: What your `prometheus.yml` does
Looking at your config:

- ✅ **Global config**: scrape/evaluation intervals, labels — fine.
- ✅ **Alertmanager block**: defined, though the target is commented out. That’s okay if you don’t have Alertmanager running yet.
- ✅ **Rule files**: you reference:
  ```yaml
  rule_files:
    - '/etc/prometheus/alerts.yml'
  ```
  This matches the mount path from `docker-compose.yml`.
- ✅ **Scrape configs**: you’ve defined jobs for Prometheus itself, MCP server, node-exporter, cadvisor, Grafana, etc. All consistent with a Docker Compose stack.
- ⚠️ **Optional jobs**: you’ve commented out Swarm and DNS discovery — harmless, but note they won’t run unless uncommented.

---

## 🔍 Step 3: Alignment check
- Your `prometheus.yml` **expects** `/etc/prometheus/alerts.yml` to exist.  
- The `docker-compose.yml` you saw earlier **mounts** `./docker/alerts.yml` into that exact path.  
- Therefore: **Yes, your `prometheus.yml` matches what `docker-compose.yml` expects.**

The only caveat:  
- If you don’t actually have an `alerts.yml` file yet, Prometheus will fail to start because it can’t find the file. That’s why the tutorial suggested either:
  - Removing the `rule_files` line, or
  - Mounting a dummy empty file.

---

## ✅ Recommendation
- If you **have alert rules**: keep `rule_files` as-is and ensure `./docker/alerts.yml` exists.
- If you **don’t need alerts yet**: either comment out the `rule_files` section in `prometheus.yml`, or mount an empty `alerts.yml`.

---

### Final Answer
Yes — your `prometheus.yml` is structured exactly as `docker-compose.yml` expects. The only dependency is that `/etc/prometheus/alerts.yml` must exist (even if empty), otherwise Prometheus will complain.

---

Would you like me to draft a **minimal `alerts.yml`** that won’t break anything (basically a safe empty placeholder), so you can run Prometheus without alerts until you’re ready?
