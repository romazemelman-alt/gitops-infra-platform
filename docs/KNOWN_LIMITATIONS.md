# Known Limitations

This is an honest inventory of gaps and bugs found in the current codebase — not hypothetical edge cases, but things actually present in the repos today.

## Correctness bugs

- **Network module mistags non-dev subnets.** `terraform/modules/network/main.tf` hardcodes `"kubernetes.io/cluster/dev-teraSky-gitops" = "shared"` on both public and private subnet tags, regardless of which environment is being deployed. Staging and prod subnets get tagged for the *dev* cluster, which can break the AWS Load Balancer Controller/ELB subnet auto-discovery in those environments.
- **`checkov.yaml` likely does the opposite of what's intended.** The `check:` key is an *allow-list* — Checkov will run **only** the two listed checks and skip everything else, rather than skipping those two and running the full default rule set (which the comments — "will be encrypted", "will be logged" — suggest was the intent). This should almost certainly be `skip-check:`.
- **Inconsistent Flux `HelmRelease` API versions.** `flux/apps/environments/dev/helm-release.yaml` uses `helm.toolkit.fluxcd.io/v2beta1`; staging and prod use `v2`. Both may currently work depending on the installed Flux version, but this is a latent break waiting for the beta API to be removed.
- **`ci-cd.yaml`'s AWS role ARN is hardcoded to the dev role**, even though the same workflow builds and tags `prod-*` images from `main`. There's no per-environment role selection, so prod-tagged builds still authenticate as the dev pipeline identity.
- **Lint job doesn't actually lint.** The `flake8` install step is present, but the command that runs it is commented out (`# flake8 app/ ...`). CI currently does nothing to catch Python lint errors.

## Security

- **Node IAM role, not IRSA, grants Secrets Manager access.** The `secrets_manager` policy is attached to the shared node group role (via `custom_policies`), not to a pod-scoped IRSA role. Every pod scheduled on a node — not just the intended workload — can assume node-level credentials to read secrets under `<env>/<cluster>/*` in Secrets Manager via the instance metadata service.
- **Infra CI role has full `AdministratorAccess`**, with no permission boundary. Any change merged (or any compromise of the PAT/OIDC trust) can affect anything in the AWS account, not just this project's resources.
- **No TLS at the ALB.** The ACM certificate annotation in `ingress.yaml` is present but commented out; the app is reachable over plain HTTP by default in every environment, including prod.
- **Cross-repo automation depends on a long-lived PAT** (`GITHUB_TOKEN_PATCH`) rather than a GitHub App installation token or fine-grained, expiring credential.
- **No branch protection or review gate visible on the automated GitOps commit** — the `gitops-update` job pushes straight to `main` of the infra repo, which is also the branch Flux watches, with no PR or approval step.

## Reliability & operations

- **No automated `terraform apply`.** All three environments stop CI at `plan`; infrastructure changes require a manual, out-of-band `apply`, so what's live can silently drift from what's merged.
- **No promotion path to staging/prod.** Only the `dev`/`main`→dev/stage image-tag patching is automated; nothing updates `flux/apps/environments/staging` or `.../prod` `HelmRelease` files. Promotion is entirely manual today.
- **No `PodDisruptionBudget` or `HorizontalPodAutoscaler`** for the application, despite `replicaCount` as low as 1 (dev) and SPOT capacity in dev/staging — a SPOT interruption or node drain can cause visible downtime.
- **Cluster-autoscaler tags exist but no autoscaler is installed.** `eks_managed_node_groups` sets `k8s.io/cluster-autoscaler/enabled` and `k8s.io/cluster-autoscaler/<cluster>` tags, but there's no Cluster Autoscaler or Karpenter deployment anywhere in this codebase reading them — the tags are currently inert.
- **Image scanning is enabled but not enforced.** ECR `scanOnPush` is on, but nothing in CI blocks a deploy on critical/high findings.
- **Terraform version drift risk.** `versions.tf` allows `>= 1.5.0`, while CI pins exactly `1.8.5` — a local `apply` on a newer/older Terraform than CI used for `plan` could behave differently.

## Maintainability

- **Mixed-language comments.** Several files in the `iam` and `network` modules contain Russian-language comments (e.g. `# Переменные скалирования`, `# Привязка политики к роли`, `# Зона в Route53`) alongside English ones, which will slow down onboarding for a non-Russian-speaking team.
- **Deprecated ingress annotation style.** `kubernetes.io/ingress.class: alb` is the legacy annotation; the AWS Load Balancer Controller and current Kubernetes versions expect `spec.ingressClassName` with an `IngressClass` resource instead.
- **`ingress.yaml` doesn't set `namespace`** explicitly (unlike every other template in the chart), relying entirely on release namespace at install time — easy to deploy into the wrong namespace if someone runs `helm install` without `-n`/`--namespace` pinned.
- **Deployment template hardcodes the secret name** (`k8s-node-app-live-secret`) rather than templating it from `values.yaml`, coupling the chart to one specific `ExternalSecret` target name.
