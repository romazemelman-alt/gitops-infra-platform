# 7. Cloud production design

**Cloud provider:** AWS, `eu-central-1`. This isn't a hypothetical choice — it's what `gitops-infra-platform/terraform` already provisions: a VPC per environment, an EKS cluster via `terraform-aws-modules/eks/aws`, IRSA-based add-ons, ECR, and a Route 53 zone per domain (`dev.terasky.com`, `staging.terasky.com`, `prod.terasky.com`). The sections below describe that design as built, and are explicit about where it's a real production posture versus where it's a deliberate simplification (cross-referenced against `docs/TRADEOFFS.md` and `docs/KNOWN_LIMITATIONS.md`, which already inventory these honestly).

## Cluster architecture

Amazon EKS (`~> 20.0` of the community module), one cluster per environment, both public and private API endpoint access enabled. Each cluster has a single EKS-managed node group, sized per environment (`dev`: 1–3 × `t3.medium` SPOT; `staging`: same shape as dev; `prod`: 3–10 × `m5.large` on-demand). The node IAM role is hand-built in the `iam` module rather than left to the EKS module's defaults (`create_iam_role = false`), so the trust policy and attached policies are explicit and auditable.

**Gap:** the node group is tagged for cluster-autoscaler discovery (`k8s.io/cluster-autoscaler/enabled`), but no autoscaler — Cluster Autoscaler or Karpenter — is actually deployed anywhere in the codebase. Those tags are currently inert; a production rollout needs one of the two installed and reading them, and a real production design would likely add Karpenter for node-level scaling instead of a single fixed-shape managed node group.

## Public/private networking model

One VPC per environment (`terraform-aws-modules/vpc/aws`), spanning 3 AZs, with public and private subnets in each. EKS nodes run in the private subnets only (`subnet_ids = private_subnet_ids`); public subnets exist for the ALB and NAT gateways. NAT is deliberately asymmetric by environment: `single_nat_gateway = true` for dev/staging (one shared NAT, cheaper, single point of failure accepted for lower environments), and one NAT gateway per AZ for prod (`single_nat_gateway = false`, full HA, higher cost). Subnets are tagged for ELB/internal-ELB auto-discovery so the AWS Load Balancer Controller can place the ALB correctly.

**Bug to flag, not just a design note:** the subnet tags in `terraform/modules/network/main.tf` are hardcoded to `kubernetes.io/cluster/dev-teraSky-gitops`, regardless of which environment is actually being deployed — so staging and prod subnets are currently mistagged for the dev cluster. This would break ELB subnet discovery outside dev until the tag is parameterized by `var.environment`.

## Ingress, DNS, and TLS

The AWS Load Balancer Controller is installed via Terraform's `helm` provider (not Flux) in the same apply as the rest of the cluster infra, using an IRSA role built in the `iam` module and scoped via `sts:AssumeRoleWithWebIdentity` to `system:serviceaccount:kube-system:aws-load-balancer-controller`. It provisions an internet-facing ALB from the app's `Ingress` resource. ExternalDNS is wired the same way — its own IRSA role, scoped to `route53:ChangeResourceRecordSets` on exactly the environment's hosted zone ID (created by the `dns` module) plus read-only `ListHostedZones`/`ListResourceRecordSets` — so DNS records sync automatically as Ingresses change.

**Real gap, present in every environment today, including prod:** the ACM certificate annotation in `charts/k8s-node-app/templates/ingress.yaml` is present but commented out. Traffic to the ALB is plain HTTP by default. Closing this is listed as the top item in `docs/PRODUCTION_RECOMMENDATIONS.md`: issue an ACM cert per domain (the Route 53 zone Terraform already creates is what it would validate against), uncomment the `certificate-arn` annotation, and add an HTTP→HTTPS redirect. Separately, `kubernetes.io/ingress.class: alb` is the legacy annotation style — current AWS Load Balancer Controller versions expect `spec.ingressClassName` with an `IngressClass` resource instead.

## IAM and workload identity

Two identity paths:

- **CI → AWS**: a one-time bootstrap script (`bootstrap/bootstrap.py`, run by a human with admin rights — not automated) creates a single GitHub OIDC provider shared across environments, plus two roles per environment: `github-actions-infra-role-<env>` (used by the Terraform pipeline) and `github-actions-ecr-push-<env>` (used by the app pipeline, scoped to ECR push only). No long-lived AWS keys anywhere in either repo.
- **Pod → AWS**: IRSA via the EKS cluster's OIDC provider. The Load Balancer Controller and ExternalDNS both get narrowly-scoped IRSA roles, trusted only by their specific `system:serviceaccount:` subject — a correct pattern, applied consistently for those two add-ons.

**The one significant IAM gap in the current design:** Secrets Manager access is *not* IRSA-scoped. The `secrets_manager` IAM policy (`secretsmanager:GetSecretValue`/`DescribeSecret` on `<env>/<cluster>/*`) is attached to the shared node-group role, not to a pod-level role. In practice that means any pod scheduled on that node — not just the app pod that's supposed to read its own secret — can reach the instance metadata service and read every secret under that path. `PRODUCTION_RECOMMENDATIONS.md` item #1 is exactly this: build a dedicated IRSA role for the app's service account (mirroring the LB-controller/ExternalDNS pattern that already exists) and remove `secrets_manager` from the node role's attached policies.

The infra CI role is also currently `AdministratorAccess` with no permission boundary — the single largest blast-radius risk in the stack, and the top scoping item in the same recommendations doc.

## Container registry

Amazon ECR, one repository per environment (`dev-k8s-node-app`, etc.), `image_tag_mutability = "MUTABLE"`, `scan_on_push` enabled, `AES256` (SSE-S3-managed) encryption at rest, and a lifecycle policy that expires everything beyond a flat count (`max_image_count`: 20 dev, 20 staging, 50 prod — worth tuning to an actual rollback-window need rather than a flat number per `PRODUCTION_RECOMMENDATIONS.md` #19).

**Gaps for a real production bar:** scan results are recorded but nothing in CI gates a deploy on critical/high findings; and tags are mutable, so a production tag like `stable-v1.0.0` (the pinning scheme actually used in `flux/apps/environments/prod/helm-release.yaml`) can in principle be overwritten. Enabling scan-based CI gating and tag immutability for the prod repo are both cheap, high-value additions.

## Secrets-management integration

This is one of the stronger parts of the current design. A Kyverno `ClusterPolicy` (`restrict-manual-secrets.yaml`) denies `CREATE` on any `Secret` object in the `k8s-node-app` namespace except from the External Secrets Operator's own service account — so raw secrets can't land in a manifest or be `kubectl apply`'d by hand, only synced from AWS Secrets Manager. Each environment has its own `SecretStore` (pointing at Secrets Manager in `eu-central-1`) and `ExternalSecret`, pulling `DATABASE_URL` and `JWT_SECRET_KEY` from `<env>/k8s-node-app/secrets` and materializing them into the exact `k8s-node-app-live-secret` object the Helm chart already expects, refreshed hourly. The application and Helm chart needed zero changes for this — it slots in underneath what's already there.

The one thing that undercuts it, as noted above, is that the *access path* to Secrets Manager still runs through the node role instead of IRSA — the policy-as-code enforcement (Kyverno) is solid, but the AWS-side permission boundary isn't yet pod-scoped.

## Environment separation

Three environments — dev, staging, prod — in a **single AWS account**, isolated by naming convention and separate Terraform state (each has its own S3 state bucket + DynamoDB lock table, its own VPC CIDR block — `10.0.0.0/16` dev vs `10.20.0.0/16` prod — and its own EKS cluster). This was a deliberate trade-off for setup speed and cost at small scale, documented explicitly in `docs/TRADEOFFS.md`: the given-up part is that a misconfigured IAM policy or a `terraform destroy` run in the wrong directory has no hard AWS account boundary stopping it from reaching another environment — only naming and state separation do. Combined with the infra role's `AdministratorAccess`, a compromised or careless infra pipeline run has account-wide blast radius, not just single-environment. Account-per-environment (via AWS Organizations) is the natural next step if this moved toward a regulated or team-scale production system.

Per-environment differences are real and visible in the `HelmRelease` values, not just infrastructure: dev runs 1 replica on a floating `dev-v1.0` tag, staging runs 2 replicas on `rc-latest`, prod runs 3 replicas with resources roughly double dev/staging's and a strictly pinned tag (`stable-v1.0.0`) — a sensible promotion-maturity gradient even though the promotion itself is still manual (see below).

## Audit logging

Not yet implemented in the Terraform given here — this is a genuine gap rather than a documented trade-off. The monitoring design (`docs/06-monitoring-and-logging.md`) does plan for it as part of the Datadog rollout: a `terraform/modules/datadog-aws-integration` module intended to pull EKS control-plane logs and CloudWatch metrics into Datadog. For a cloud-native alternative (or in addition), production should also enable native EKS control-plane logging (API server + audit + authenticator) to CloudWatch Logs directly, and turn on CloudTrail for the account so API-level changes to IAM, Secrets Manager, and ECR are independently recoverable even if the Datadog pipeline has an outage.

## Encryption

- **In transit**: not yet enforced end-to-end — see the TLS gap under Ingress above. Once the ACM cert is wired in, client→ALB traffic is encrypted; ALB→pod traffic inside the private subnet stays plain HTTP unless a mesh is introduced later.
- **At rest**: ECR uses `AES256` (SSE-S3-managed keys), not a customer-managed KMS key. Terraform state in S3 has `encrypt = true`. Secrets Manager encrypts with the AWS-managed key by default (no explicit `kms_key_id` is set in the given modules) — `terraform/checkov.yaml` actually has a check (`CKV_AWS_149`) that's *meant* to enforce a custom KMS key for Secrets Manager, but see the note below: the way that file is written, this check silently never runs against non-exempted resources.
- **A configuration bug worth calling out directly**: `checkov.yaml`'s `check:` key is a Checkov *allow-list* — it makes CI run only those two named checks and skip everything else, which is the inverse of what the comments in the file ("will be encrypted", "will be logged") clearly intend. This should be `skip-check:`. As written, essentially the entire default Checkov ruleset is not being evaluated in CI today.

## Backup and restore

Not built out in the current Terraform/Flux — there's no Velero, no database (the app's database is assumed to already exist elsewhere; `docs/ASSUMPTIONS.md` states provisioning one was out of scope), so there's nothing stateful in-cluster to back up yet beyond the GitOps repo itself. What already functions as a backup mechanism: since Flux reconciles the cluster's app layer entirely from the `gitops-infra-platform` repo, and Terraform state is versioned in S3 with locking, both "what should be running" and "what infrastructure exists" can be reconstructed from source control and state rather than from a cluster-side backup. If a real stateful component (e.g. an RDS instance) is added, automated snapshots + PITR would need to be added explicitly — nothing here does that today.

## Scaling and node provisioning

Node-level scaling exists in shape only right now: `min_size`/`max_size`/`desired_size` are set per environment and `capacity_type` is `SPOT` for dev/staging, `ON_DEMAND` for prod — but as noted under Cluster architecture, no autoscaler is deployed to actually act on demand, so today the node count sits at whatever `desired_size` was on the last apply. Pod-level scaling is similarly static: `replicaCount` is a fixed number per environment (1 / 2 / 3) with no `HorizontalPodAutoscaler`, and — more importantly for availability — no `PodDisruptionBudget` either. That combination is a real risk specifically because dev and staging run on SPOT: a 2-minute-notice reclaim or a routine node drain can currently take the whole app down in those environments (`docs/TRADEOFFS.md` calls this out explicitly). Adding a `PodDisruptionBudget` (`maxUnavailable: 0` or `1`) is cheap and should happen before an autoscaler is even installed.

## Cost considerations

The cost/reliability trade-offs here are already deliberate and documented, not accidental:

- SPOT for dev/staging vs. on-demand for prod — real savings in the environments iterated on most, accepted interruption risk where availability matters least.
- Single shared NAT gateway for dev/staging vs. one per AZ in prod — same trade-off applied to networking cost.
- ECR lifecycle policies cap storage growth, though the current limits (20/20/50 images) are round numbers rather than derived from an actual rollback-window requirement.
- Worth reassessing per `PRODUCTION_RECOMMENDATIONS.md` #18: whether prod genuinely needs `m5.large` on-demand at `min_size = 3` continuously, or whether prod could also take a partial-SPOT mix once `PodDisruptionBudget`s and topology spread constraints exist to absorb interruptions safely.

## Disaster recovery considerations

Explicitly out of scope for the current design — `docs/ASSUMPTIONS.md` states plainly that no multi-region or DR requirement was assumed, and everything lives in a single AWS account and single region (`eu-central-1`). Within that scope, the design still gets AZ-level resilience for free: the EKS control plane spans 3 AZs (AWS-managed), and prod's node group and multi-NAT setup are already spread across AZs. What a real DR posture would add on top, if the requirement changed: cross-region ECR replication, a warm-standby cluster in a second region with Flux pointed at the same GitOps repo (rebuilding the app layer is largely "point Flux at it," since the repo is the source of truth), Route 53 health-check-based failover, and — once a real database exists — cross-region replication/PITR for it specifically, since that's the one piece a git-replay of manifests can't reconstruct. None of this is built today; it's the honest answer to "what's next" rather than a description of what exists.
