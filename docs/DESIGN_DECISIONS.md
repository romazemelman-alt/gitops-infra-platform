# Design Decisions

## Two-repository split (app vs. infra)
Application code/chart and infrastructure/GitOps config live in separate repositories (`k8s-node-app`, `gitops-infra-platform`). This keeps blast radius and permissions separate: the app's CI role only needs ECR push access, while the infra role needs broad AWS access. It also matches how Flux expects to consume a GitOps repo independently of application source.

## Environment isolation via directory + state, not AWS account
Dev/staging/prod are separate Terraform root modules with separate backends (`terraform/environments/<env>/backend.tf`), rather than separate AWS accounts or a single root module parameterized by workspace. This was chosen for simplicity and fast iteration at small scale, at the cost of the isolation guarantees a full account-per-environment model gives (see Trade-offs).

## Bootstrap script owns backend + OIDC, not Terraform
The S3 bucket, DynamoDB table, and GitHub OIDC provider/roles are created by a standalone Python script rather than a Terraform "bootstrap" root module. This resolves the standard chicken-and-egg problem of "Terraform needs a backend before it can create a backend," and keeps the one-time, rarely-changed, high-privilege setup separate from routine infrastructure changes. The cost is that this part of the stack isn't tracked in Terraform state.

## IAM roles hand-built in a custom `iam` module, not left to `create_iam_role` defaults
The EKS module's `create_iam_role = false` and node role, LB Controller role, and ExternalDNS role are all defined explicitly in `terraform/modules/iam`, rather than using the upstream EKS module's built-in IAM role creation, or a third-party IRSA module. This gives explicit control over trust policies and which policies attach to which role, at the cost of maintaining that logic manually instead of inheriting upstream module updates/fixes.

## GitOps push-to-infra-repo instead of a Kubernetes-native tag updater
The app pipeline patches the image tag directly into `HelmRelease` YAML via `yq` and pushes, rather than using Flux's `ImageUpdateAutomation`/`ImagePolicy` CRDs, ArgoCD Image Updater, or a similar in-cluster tag-tracking controller. This keeps all promotion logic visible in the CI YAML and doesn't require running an extra controller in-cluster, at the cost of coupling the app repo's pipeline to the infra repo's file layout and needing a PAT with cross-repo write access.

## `terraform apply` deliberately not automated
All three Terraform CI workflows stop at `plan`; `apply` is commented out rather than gated behind a manual-approval GitHub Environment or similar. This was a conscious choice to force a manual step before any real AWS changes happen, given this is early-stage/demo infrastructure. It also avoids the need to configure GitHub Environment protection rules as part of this exercise.

## RBAC scoped narrowly to node read
The app's `ClusterRole` only grants `get`/`list` on `nodes` — nothing else — even though it runs cluster-wide (a `ClusterRole`, not a namespaced `Role`, since node objects aren't namespaced). This keeps the demo endpoint functional while avoiding a broad service account.

## Secrets enforced through External Secrets Operator, not raw manifests
A Kyverno policy denies manual `Secret` creation in the app namespace, forcing all secrets through `ExternalSecret` → AWS Secrets Manager. This was chosen to guarantee secrets never live in Git in any form, and to centralize secret rotation/audit in AWS rather than in cluster manifests.

## SPOT capacity for dev/staging, on-demand for prod
`capacity_type` is `SPOT` for dev and staging and `ON_DEMAND` for prod (visible in the respective `.tfvars`), trading cost savings against interruption risk in the lower environments where availability matters less.
