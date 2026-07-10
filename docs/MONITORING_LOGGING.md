# 6. Monitoring and Logging (Datadog)

This document describes a production-suitable monitoring, logging, and alerting
strategy for the platform, built around **Datadog** as the single observability
tool. It covers both repositories in the project:

- **`k8s-node-app`** — the Flask/Kubernetes-client application, its Dockerfile,
  Helm chart, and CI/CD pipeline.
- **`gitops-infra-platform`** — Terraform (EKS, VPC, IAM, ECR, DNS), Flux CD
  GitOps manifests, and the AWS bootstrap scripts.

No monitoring stack is deployed as part of this exercise; instead, this
document specifies exactly what would be deployed, where it lives in each
repo, and how it operates in production.

---

## 6.1 Overview / Why Datadog

Datadog is used as a **unified platform** for the four core observability
pillars, replacing what would otherwise be four separate tools
(Prometheus + Grafana, Loki/ELK, Alertmanager, and a tracing backend):

| Pillar | Datadog Component |
|---|---|
| Application metrics | Datadog APM (`ddtrace`) + DogStatsD custom metrics |
| Kubernetes workload monitoring | Datadog Cluster Agent + Autodiscovery |
| Cluster-level monitoring | Datadog Agent (node checks) + AWS integration |
| Centralized logging | Datadog Log Agent + Log Pipelines |
| Alerting | Datadog Monitors (defined as code via Terraform) |
| Incident investigation | Datadog Dashboards, APM Traces, Notebooks |

### Where each piece lives

| Component | Repository | Location |
|---|---|---|
| Datadog Agent + Cluster Agent Helm release | `gitops-infra-platform` | `flux/apps/base/datadog/` (new `HelmRelease`, deployed by Flux to every cluster) |
| Datadog API/APP keys | AWS Secrets Manager → `ExternalSecret` | `flux/apps/environments/<env>/datadog-secret.yaml` |
| Monitors, dashboards, notification channels (as code) | `gitops-infra-platform` | `terraform/modules/datadog-monitors/` using the official `datadog` Terraform provider |
| AWS integration (CloudWatch metrics, EKS control-plane logs) | `gitops-infra-platform` | `terraform/modules/datadog-aws-integration/` |
| Application instrumentation (`ddtrace`, log format, pod annotations) | `k8s-node-app` | `app/requirements.txt`, `Dockerfile/Dockerfile`, `charts/k8s-node-app/templates/deployment.yaml` |

---

## 6.2 Application Metrics

The `k8s-node-app` Flask service currently exposes no metrics endpoint. The
production-suitable approach is:

1. **Auto-instrumentation with `ddtrace`**
   Add `ddtrace` to `app/requirements.txt` and change the container entrypoint:

   ```dockerfile
   # Dockerfile/Dockerfile
   RUN pip install --no-cache-dir --user ddtrace
   CMD ["ddtrace-run", "python", "app.py"]
   ```

   This automatically instruments Flask and the `kubernetes` client library,
   producing out-of-the-box **APM traces**, and derives the "golden signal"
   metrics for free:
   - `trace.flask.request.hits` — request rate (throughput)
   - `trace.flask.request.errors` — error rate
   - `trace.flask.request.duration` — latency (p50/p95/p99)

2. **Custom business metrics via DogStatsD**
   For anything domain-specific (e.g. number of nodes returned by `/nodes`,
   count of `NotReady` nodes seen), the app sends StatsD metrics to the
   Datadog Agent running as a DaemonSet on the same node:

   ```python
   from datadog import statsd
   statsd.gauge("k8s_node_app.cluster.nodes_total", total_nodes_count)
   statsd.gauge("k8s_node_app.cluster.nodes_not_ready", not_ready_count)
   statsd.increment("k8s_node_app.nodes_endpoint.errors")
   ```

3. **Unified Service Tagging**
   Every metric/trace/log is tagged with `env`, `service`, `version` via pod
   labels/env vars, so Datadog can correlate the three signals automatically:

   ```yaml
   env:
     - name: DD_ENV
       value: {{ .Values.environment }}
     - name: DD_SERVICE
       value: k8s-node-app
     - name: DD_VERSION
       value: "{{ .Values.image.tag }}"
   ```

---

## 6.3 Kubernetes Workload Monitoring

The **Datadog Cluster Agent** is deployed once per cluster (via Flux
`HelmRelease`, chart `datadog/datadog`) and provides workload-level visibility
without needing to run `kube-state-metrics` separately (it's bundled):

- Deployment/ReplicaSet/Pod status: desired vs. available vs. unavailable
  replicas (`kubernetes_state.deployment.replicas_available` vs
  `...desired`).
- Pod restart counts and reasons (`kubernetes.containers.restarts`,
  `kubernetes_state.container.status_report.count.waiting` with
  `reason:crashloopbackoff`).
- HPA state: `kubernetes_state.hpa.current_replicas` vs
  `kubernetes_state.hpa.desired_replicas`, and `...condition` for
  `ScalingLimited`/`AbleToScale`.
- **Autodiscovery**: the agent auto-detects the Flask container via pod
  annotations and starts log collection + a service check without manual
  agent configuration:

  ```yaml
  # charts/k8s-node-app/templates/deployment.yaml (annotations to add)
  annotations:
    ad.datadoghq.com/k8s-node-app.logs: '[{"source":"python","service":"k8s-node-app"}]'
  ```

---

## 6.4 Cluster-Level Monitoring

- **Node Agent (DaemonSet)**: collects CPU, memory, disk, and network
  metrics per EC2 worker node (`system.cpu.*`, `system.mem.*`,
  `system.disk.*`), plus kubelet metrics (`kubelet.*`).
- **Node conditions / pressure**: the agent surfaces
  `kubernetes_state.node.status` for conditions such as
  `MemoryPressure`, `DiskPressure`, `PIDPressure`.
- **EKS control plane**: since this is a managed EKS cluster, the API
  server/scheduler/controller-manager logs go to CloudWatch Logs.
  The `terraform/modules/datadog-aws-integration` module configures the
  **Datadog AWS integration** (cross-account IAM role, similar in shape to
  the existing `terraform/modules/iam` role pattern) so CloudWatch metrics
  and control-plane logs are forwarded into Datadog automatically — no
  agent needed for this layer.
- **Autoscaler visibility**: node group scaling activity (min/max/desired
  from `terraform/modules/eks`) is visible via
  `aws.autoscaling.group_desired_capacity` / `...in_service_instances`
  pulled through the same AWS integration, useful for correlating pod
  scheduling failures with node capacity limits.

---

## 6.5 Centralized Logging

- The Datadog Agent's log collection is enabled cluster-wide
  (`logs_enabled: true` in the Helm values) and uses **container log
  autodiscovery** — no sidecars, no Fluentd/Fluent Bit DaemonSet to
  maintain separately.
- **Log pipelines** parse the Flask app's stdout, extract `status_code`,
  `path`, and `latency`, and enrich logs with the `env`/`service`/`version`
  tags mentioned in 6.2, so a log line can be pivoted directly to its trace.
- **Sensitive data scrubbing**: Datadog Sensitive Data Scanner is enabled on
  the log pipeline to redact anything resembling the `DATABASE_URL` or
  `JWT_SECRET_KEY` values that are injected via `ExternalSecret`, in case
  they ever leak into stdout.
- **Retention**: 15-day full-text searchable retention in the hot tier,
  with logs older than that flushed to an S3-backed archive (reusing the
  same AWS account already used for the Terraform state bucket) for
  compliance/audit needs at a fraction of the cost.
- **CI/CD and GitOps logs**: GitHub Actions workflow results and Flux
  reconciliation events are not sent to Datadog by default; if needed,
  `flux logs` can be shipped by the same Agent (it runs in the same
  cluster as `flux-system`) using an extra Autodiscovery log-collection
  annotation on the Flux controller pods.

---

## 6.6 Alerting

Alerts are **defined as code** in `gitops-infra-platform` using the
`datadog` Terraform provider, so they're version-controlled, reviewed via
PR, and applied by the same `terraform plan`/`apply` pipeline used for the
rest of the infrastructure. Notification channels: **Slack** (`#platform-alerts`)
for warnings, **PagerDuty** for criticals/pages.

Below are 6 example alerts (2× the minimum requested), covering all six
suggested categories:

### 1. High error rate

```hcl
resource "datadog_monitor" "high_error_rate" {
  name    = "[k8s-node-app] High HTTP error rate (${var.environment})"
  type    = "metric alert"
  message = <<-EOT
    {{#is_alert}}Error rate above 5% for k8s-node-app in ${var.environment}.{{/is_alert}}
    @slack-platform-alerts @pagerduty-platform
  EOT

  query = <<-EOT
    sum(last_5m):sum:trace.flask.request.errors{env:${var.environment},service:k8s-node-app}.as_count()
    / sum:trace.flask.request.hits{env:${var.environment},service:k8s-node-app}.as_count() * 100 > 5
  EOT

  monitor_thresholds {
    warning  = 2
    critical = 5
  }

  notify_no_data    = true
  no_data_timeframe = 10
}
```

### 2. Pod crash looping

```hcl
resource "datadog_monitor" "pod_crash_loop" {
  name    = "[k8s-node-app] Pod in CrashLoopBackOff (${var.environment})"
  type    = "metric alert"
  message = "A pod is crash-looping in ${var.environment}. @slack-platform-alerts @pagerduty-platform"

  query = <<-EOT
    max(last_10m):max:kubernetes_state.container.status_report.count.waiting
    {reason:crashloopbackoff,kube_namespace:k8s-node-app,env:${var.environment}} > 0
  EOT

  monitor_thresholds {
    critical = 0
  }
}
```

### 3. Deployment unavailable

```hcl
resource "datadog_monitor" "deployment_unavailable" {
  name    = "[k8s-node-app] Deployment has 0 available replicas (${var.environment})"
  type    = "metric alert"
  message = "k8s-node-app has no healthy replicas in ${var.environment} — service is down. @pagerduty-platform"

  query = <<-EOT
    max(last_5m):avg:kubernetes_state.deployment.replicas_available
    {deployment:k8s-node-app,kube_namespace:k8s-node-app,env:${var.environment}} <= 0
  EOT

  monitor_thresholds {
    critical = 0
  }

  notify_no_data    = true
  no_data_timeframe = 5
}
```

### 4. HPA unable to scale

```hcl
resource "datadog_monitor" "hpa_scaling_limited" {
  name    = "[k8s-node-app] HPA unable to scale up (${var.environment})"
  type    = "metric alert"
  message = <<-EOT
    HPA wants more replicas but is blocked (resource quota, node capacity, or
    max replicas reached) in ${var.environment}. @slack-platform-alerts
  EOT

  query = <<-EOT
    max(last_10m):max:kubernetes_state.hpa.condition
    {condition:scalinglimited,status:true,kube_namespace:k8s-node-app,env:${var.environment}} >= 1
  EOT

  monitor_thresholds {
    critical = 1
  }
}
```

### 5. High CPU / memory usage (approaching limits)

```hcl
resource "datadog_monitor" "high_pod_cpu_mem" {
  name    = "[k8s-node-app] Pod CPU/Memory near resource limits (${var.environment})"
  type    = "metric alert"
  message = "Pod is close to its CPU or memory limit and may be throttled/OOMKilled. @slack-platform-alerts"

  query = <<-EOT
    avg(last_10m):avg:kubernetes.cpu.usage.total
    {kube_namespace:k8s-node-app,env:${var.environment}} / avg:kubernetes.cpu.limits{same by {pod_name}} * 100 > 85
  EOT

  monitor_thresholds {
    warning  = 70
    critical = 85
  }
}
```

### 6. Node pressure

```hcl
resource "datadog_monitor" "node_pressure" {
  name    = "[EKS] Node under Memory/Disk/PID pressure (${var.environment})"
  type    = "metric alert"
  message = "A worker node reports pressure and may start evicting pods. @slack-platform-alerts @pagerduty-platform"

  query = <<-EOT
    max(last_5m):max:kubernetes_state.node.status
    {condition:memorypressure,status:true,env:${var.environment}} >= 1
  EOT

  monitor_thresholds {
    critical = 1
  }
}
```

> All six monitors use tag-based scoping (`env`, `service`, `kube_namespace`)
> so the **same Terraform module** is reused across `dev`, `staging`, and
> `prod` by passing a different `var.environment`, exactly like the existing
> `terraform/environments/<env>` pattern in this repo.

---

## 6.7 Incident Investigation

When a monitor fires, the on-call engineer's workflow is:

1. **Alert → Dashboard**: each monitor links to a pre-built Datadog
   dashboard for `k8s-node-app` showing request rate, error rate, latency
   (APM), pod count/restarts (Kubernetes), and node CPU/memory
   side-by-side, scoped to the `env` tag that fired.
2. **Dashboard → Trace**: because of Unified Service Tagging (6.2), the
   engineer clicks from an error-rate spike straight into the specific
   **APM trace** that failed, seeing the exact request path (e.g.
   `/nodes`) and the exception stack trace.
3. **Trace → Logs**: from the trace, Datadog auto-correlates to the
   **log lines** emitted during that exact request (via injected
   `dd.trace_id`), showing the `[ERROR] Failed to query Kubernetes API`
   message already present in `app/app.py` alongside full context.
4. **Logs → Kubernetes events**: the Cluster Agent also ships Kubernetes
   events (e.g. `FailedScheduling`, `BackOff`) into the same log index,
   so a crash-loop alert can be traced back to an `OOMKilled` event
   without leaving Datadog or needing `kubectl` access.
5. **Root cause → Change correlation**: Datadog's **Deployment Tracking**
   is annotated by the CI/CD pipeline (a simple `curl` call to the
   Datadog Events API added as a final step in
   `.github/workflows/ci-cd.yaml`, marking `DD_VERSION` deploys), so
   engineers can immediately see "this regression started right after
   deploy `prod-<sha>`" and correlate incidents to the Flux
   `HelmRelease` update that triggered them.
6. **Postmortem**: Datadog Notebooks are used to snapshot the graphs and
   timeline for the incident write-up, attached to the retro ticket.

---

## 6.8 Summary

| Requirement | Datadog Answer |
|---|---|
| Application metrics | `ddtrace` auto-instrumentation + DogStatsD custom metrics |
| Kubernetes workload monitoring | Cluster Agent + Autodiscovery (deployments, pods, HPA) |
| Cluster-level monitoring | Node Agent + AWS integration (EKS control plane, ASG) |
| Centralized logging | Agent log collection + pipelines + Sensitive Data Scanner |
| Alerting | 6 Terraform-managed monitors → Slack/PagerDuty |
| Incident investigation | Dashboards → APM → Logs → K8s events → Deploy correlation |
