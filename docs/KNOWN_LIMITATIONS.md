# Known Limitations

This is an honest inventory of gaps and bugs found in the current codebase — not hypothetical edge cases, but things actually present in the repos today.

## Correctness bugs

## Security

- **Node IAM role, not IRSA, grants Secrets Manager access.** The `secrets_manager` policy is attached to the shared node group role (via `custom_policies`), not to a pod-scoped IRSA role. Every pod scheduled on a node — not just the intended workload — can assume node-level credentials to read secrets under `<env>/<cluster>/*` in Secrets Manager via the instance metadata service.
- **Infra CI role has full `AdministratorAccess`**, with no permission boundary. Any change merged (or any compromise of the PAT/OIDC trust) can affect anything in the AWS account, not just this project's resources.
- **Cross-repo automation depends on a long-lived PAT** (`GITHUB_TOKEN_PATCH`) rather than a GitHub App installation token or fine-grained, expiring credential.
- **No branch protection or review gate visible on the automated GitOps commit** — the `gitops-update` job pushes straight to `main` of the infra repo, which is also the branch Flux watches, with no PR or approval step.

## Reliability & operations

- **No automated `terraform apply`.** All three environments stop CI at `plan`; infrastructure changes require a manual, out-of-band `apply`, so what's live can silently drift from what's merged.
- **No promotion path to staging/prod.** Only the `dev`/`main`→dev/stage image-tag patching is automated; nothing updates `flux/apps/environments/staging` or `.../prod` `HelmRelease` files. Promotion is entirely manual today.
- **No `PodDisruptionBudget` or `HorizontalPodAutoscaler`** for the application, despite `replicaCount` as low as 1 (dev) and SPOT capacity in dev/staging — a SPOT interruption or node drain can cause visible downtime.
- **Cluster-autoscaler tags exist but no autoscaler is installed.** `eks_managed_node_groups` sets `k8s.io/cluster-autoscaler/enabled` and `k8s.io/cluster-autoscaler/<cluster>` tags, but there's no Cluster Autoscaler or Karpenter deployment anywhere in this codebase reading them — the tags are currently inert. (lack of time)
- **Image scanning is enabled but not enforced.** ECR `scanOnPush` is on, but nothing in CI blocks a deploy on critical/high findings.
- **Terraform version drift risk.** `versions.tf` allows `>= 1.5.0`, while CI pins exactly `1.8.5` — a local `apply` on a newer/older Terraform than CI used for `plan` could behave differently.

## Maintainability

- **Deprecated ingress annotation style.** `kubernetes.io/ingress.class: alb` is the legacy annotation; the AWS Load Balancer Controller and current Kubernetes versions expect `spec.ingressClassName` with an `IngressClass` resource instead.
- **`ingress.yaml` doesn't set `namespace`** explicitly (unlike every other template in the chart), relying entirely on release namespace at install time — easy to deploy into the wrong namespace if someone runs `helm install` without `-n`/`--namespace` pinned.
- **Deployment template hardcodes the secret name** (`k8s-node-app-live-secret`) rather than templating it from `values.yaml`, coupling the chart to one specific `ExternalSecret` target name.
