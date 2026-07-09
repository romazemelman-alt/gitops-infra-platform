# Trade-offs

Every design choice here traded something away. This lists the main ones explicitly, so they can be revisited deliberately rather than discovered by accident.

## Single AWS account vs. account-per-environment
**Chosen:** one account, isolated by naming and Terraform state.
**Gained:** faster setup, no cross-account IAM/networking complexity, cheaper for a small project.
**Given up:** a misconfigured IAM policy or a runaway `terraform destroy` in the wrong directory can, in principle, reach across environments (only naming and state separation prevent it, not a hard AWS boundary). Blast radius for a compromised CI role is the whole account, not just one environment.

## `AdministratorAccess` for the infra CI role vs. least-privilege
**Chosen:** the infra pipeline's IAM role has full admin rights.
**Gained:** no need to enumerate/maintain a fine-grained policy as Terraform's resource footprint grows.
**Given up:** a compromised token, a malicious PR that gets auto-approved, or a mistake in a `.tf` file has no permission boundary — it can do anything in the account, including deleting the state backend or other unrelated resources.

## Hand-built IAM/IRSA roles vs. upstream module defaults
**Chosen:** custom `iam` module, `create_iam_role = false` on the EKS module.
**Gained:** precise control over trust policies and exactly which managed/custom policies attach where.
**Given up:** this logic doesn't benefit from upstream fixes (e.g., to `terraform-aws-modules/eks/aws`'s IAM handling) and has to be kept in sync manually — evident already in this codebase (see Known Limitations re: the node group's overly-broad managed policies and lack of any IRSA constraint on the node role itself).

## Manual `terraform apply` vs. full CI/CD automation
**Chosen:** CI stops at `plan`; a human runs `apply` locally (or the commented step must be manually re-enabled).
**Gained:** a human reviews every infrastructure change before it's live — cheap insurance against a bad `plan` output going straight to `apply`.
**Given up:** infra changes aren't actually continuously delivered — they depend on someone remembering to apply, which can drift from what's merged to `main`, and doesn't scale as a team grows.

## Cross-repo push via PAT vs. a purpose-built promotion mechanism
**Chosen:** the app pipeline's `gitops-update` job clones the infra repo with a PAT, patches YAML with `yq`, and pushes directly to `main`.
**Gained:** simple, no extra controller to run or CRDs to learn; promotion logic is fully visible in one workflow file.
**Given up:** no review step for the automated commit (it pushes straight to `main`, which is also what triggers Flux), a long-lived PAT is a standing credential to protect and rotate, and there's no built-in protection against two pipeline runs racing on the same file.

## SPOT instances for dev/staging vs. on-demand everywhere
**Chosen:** SPOT for dev/staging, on-demand for prod.
**Gained:** meaningful compute cost savings in the environments used most often for iteration.
**Given up:** dev/staging nodes can be reclaimed with 2 minutes' notice, so those environments are not reliable for anything time-sensitive (e.g., a demo mid-interruption) unless workloads tolerate node churn gracefully (the app's `replicaCount: 1`/`2` and lack of PodDisruptionBudgets mean brief downtime is likely on interruption).

## No TLS termination at the ALB (by default)
**Chosen:** the ACM certificate annotation in `ingress.yaml` is present but commented out; traffic is HTTP-only until someone uncomments it and supplies a cert ARN.
**Gained:** one less prerequisite (an issued ACM cert) to have ready before the first deploy works end-to-end.
**Given up:** unencrypted traffic to the ALB by default, including for staging/prod unless explicitly fixed per environment.

## Terraform-managed cluster add-on (LB Controller) vs. GitOps-managed
**Chosen:** the AWS Load Balancer Controller is installed via Terraform's `helm` provider, in the same apply as the AWS infrastructure, while everything app-related goes through Flux.
**Gained:** the controller (needed for the cluster to be usable at all) is guaranteed present as part of cluster provisioning, without depending on Flux being bootstrapped first.
**Given up:** two different reconciliation systems now manage cluster state (Terraform for add-ons, Flux for apps), which means two different places to look when something in-cluster is wrong, and Terraform state now has a runtime dependency on the cluster being reachable (fragile if the cluster endpoint changes or access is briefly lost during an apply).
