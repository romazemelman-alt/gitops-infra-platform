# Assumptions

These are the assumptions this implementation is built on. Where an assumption doesn't hold in your actual environment, treat the corresponding part of the design as something to revisit before relying on it.

## Account & environment structure
- A single AWS account hosts all three environments (dev, staging, prod), differentiated by naming prefixes and separate Terraform state — not by separate AWS accounts. Multi-account isolation was assumed to be out of scope.
- All infrastructure lives in `eu-central-1`. No multi-region or DR requirement was assumed.
- Three environments (dev, staging, prod) is a fixed, known set — the pipeline and module structure are not designed to add a fourth without duplicating a full environment directory.

## Access & identity
- GitHub Actions is the only CI/CD system in play, and OIDC federation (not long-lived AWS keys) is an acceptable and expected authentication method for both repositories.
- The person running `bootstrap.py` has, and is trusted with, IAM/S3/DynamoDB/OIDC-provider admin permissions in the target account — this is a manual, human-run step, not something automated CI does.
- A GitHub PAT with cross-repo write access (`GITHUB_TOKEN_PATCH`) is an acceptable mechanism for the app repo's CI to commit into the infra repo. A GitHub App or fine-grained token was assumed out of scope for this exercise.
- Granting `AdministratorAccess` to the infra pipeline's IAM role is acceptable for the environments this targets (i.e., these are not regulated/production-grade AWS accounts where least-privilege CI roles would be mandatory).

## Domain & DNS
- A domain (`terasky.com`) is already owned and its registrar allows delegating subdomains (`dev.`, `stage.`, `prod.`) to Route53 name servers that Terraform creates. Terraform creates the *hosted zone*, not the domain registration itself, and NS delegation at the registrar is a manual step outside this codebase.

## Secrets & configuration
- Application secrets (`DATABASE_URL`, `JWT_SECRET_KEY`) already exist in AWS Secrets Manager at the paths referenced (`<env>/k8s-node-app/secrets`) before Flux reconciles — nothing in this codebase creates them.
- A database exists somewhere reachable from the cluster; provisioning it was assumed out of scope, since no database infrastructure appears in Terraform.

## Application
- The Flask app is a demo/reference workload (its only real function is listing nodes) rather than a production service with its own data model, migrations, or persistence layer.
- Horizontal scaling needs are modest and predictable enough that fixed `replicaCount` per environment (no HPA) is sufficient for the stated scope.

## CI/CD & GitOps
- Manual review before infrastructure changes reach the cloud is desired: `terraform apply` is intentionally not automated in CI (currently commented out), on the assumption a human approves applies out-of-band for now.
- Flux CD is already bootstrapped into each cluster (i.e., `flux bootstrap` or equivalent has been run separately) — the manifests in this repo assume Flux is already watching it, since nothing here installs Flux itself.
- Direct pushes to `main`/`dev` triggering builds is acceptable; branch protection, required reviews, or a merge-queue gate were assumed to be handled at the GitHub repo-settings level, outside this code.
