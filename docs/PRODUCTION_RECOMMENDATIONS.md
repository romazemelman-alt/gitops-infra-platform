# Production Recommendations

Concrete, prioritized changes to make before treating this as a production system, grouped by urgency.

## Do before any real production traffic

1. **Move Secrets Manager access to IRSA, off the node role.** Create a dedicated pod-level IAM role (mirroring the existing `lb_controller`/`external_dns` pattern in the `iam` module) trusted only by the app's own service account, and remove `secrets_manager` from the node group's attached policies. This closes the current gap where any pod on a node can read the app's secrets.
2. **Terminate TLS at the ALB.** Provision an ACM certificate per domain (`dev.terasky.com`, etc. — Terraform already creates the Route53 zone these can validate against) and uncomment/wire the `alb.ingress.kubernetes.io/certificate-arn` annotation. Redirect HTTP→HTTPS.
3. **Fix the network module's hardcoded cluster tag** so staging and prod subnets are tagged for their own cluster name, not `dev-teraSky-gitops`.
4. **Fix or replace `checkov.yaml`'s `check:` list** with `skip-check:` (or remove the file and run Checkov's full default rule set), and actually gate CI on its output rather than running it uninspected.
5. **Scope the infra CI role down from `AdministratorAccess`** to a policy covering only the AWS services this project touches (EKS, EC2/VPC, IAM role/policy management for the specific role name patterns used, Route53, ECR, S3/DynamoDB for its own state). Full admin in a CI-triggered role is the single largest blast-radius risk in this stack.

## Do before treating this as team-scale / continuously delivered

6. **Re-enable `terraform apply` in CI**, gated behind a GitHub Environment with required reviewers for staging/prod (dev can auto-apply on merge if desired). This closes the drift risk between what's merged and what's actually deployed.
7. **Build a real promotion pipeline.** Decide explicitly how an image gets from dev → staging → prod (e.g., a manual `workflow_dispatch` that bumps the target `HelmRelease`, or Flux `ImagePolicy`/`ImageUpdateAutomation` with promotion gates) rather than leaving staging/prod `HelmRelease` files untouched by any automation.
8. **Replace the PAT-based cross-repo push with a GitHub App installation token**, scoped to only the specific paths it needs to write (`flux/apps/environments/<env>/helm-release.yaml`), with a short-lived token minted per workflow run.
9. **Add branch protection on `gitops-infra-platform`'s `main`**, or route the automated tag update through a PR (even an auto-merged one) so there's an audit trail and a place a human could intervene before Flux reconciles.

## Reliability hardening

10. **Add `PodDisruptionBudget` and consider `HorizontalPodAutoscaler`** for the app, especially given dev/staging run on SPOT capacity. At minimum, set `maxUnavailable: 0` or `1` depending on `replicaCount` so a node drain can't take the whole app down at once.
11. **Install a cluster autoscaler (Karpenter is the modern default for EKS) that actually reads the tags already being set** on the managed node group — currently those tags are inert.
12. **Add resource-based alerting/monitoring** (CloudWatch Container Insights, or a Prometheus/Grafana stack) — nothing observes cluster or app health today beyond Kubernetes' own liveness/readiness probes.
13. **Fail CI on ECR scan findings above a defined severity**, rather than only recording scan results with no gate.

## Consistency and maintainability

14. **Standardize on one Flux `HelmRelease` API version** (`v2`) across all three environments.
15. **Move the RBAC-scoped node-reading pattern out of production paths**, or replace `/nodes` with a real health/business endpoint before this chart is used for anything beyond demonstrating IRSA/RBAC — a cluster-wide `list nodes` permission is unusual for an application workload and should be justified or removed.
16. **Translate remaining non-English comments** in the `iam` and `network` modules for team consistency, and add a `CONTRIBUTING.md` documenting the module conventions used (naming, tagging, variable patterns) so new modules stay consistent.
17. **Pin Terraform's `required_version` to match CI exactly** (or use a tilde constraint bounded on both sides, e.g. `~> 1.8.5`) to eliminate local/CI version drift.
18. **Migrate S3 backend locking from DynamoDB (`dynamodb_table`) to native S3 locking (`use_lockfile`)** once your Terraform version supports it, to drop the DynamoDB table and its associated IAM permissions as a maintained dependency.

## Cost

19. Reassess whether prod truly needs `m5.large` on-demand at `min_size = 3` continuously, or whether a mix of on-demand + SPOT (with PodDisruptionBudgets and topology spread constraints to tolerate interruption) is acceptable even in prod, depending on the app's actual availability requirements.
20. Set ECR lifecycle `max_image_count` per environment based on actual rollback-window needs rather than the current flat 20/20/50 — untagged/superseded images older than your realistic rollback window are pure storage cost.
