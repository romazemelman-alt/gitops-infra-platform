# k8s-node-app — Deployment Guide

This project is split across two repositories that together implement a GitOps delivery pipeline for a small Flask/Kubernetes service on AWS EKS:

| Repository | Responsibility |
|---|---|
| `k8s-node-app` | Application source, Dockerfile, Helm chart, CI pipeline (build & push image) |
| `gitops-infra-platform` | Terraform for AWS infrastructure (VPC, EKS, IAM, ECR, Route53), Flux CD manifests, bootstrap script |

Deployment happens in three layers: **bootstrap** (one-time, per AWS account) → **Terraform** (infrastructure, per environment) → **CI/CD + Flux** (application, continuous).

---

## 1. Prerequisites

- AWS CLI configured with credentials that have administrative access (for the one-time bootstrap step only)
- Python 3.8+ with `boto3` installed
- Terraform `1.8.5` (pinned in CI; match locally to avoid state drift)
- `kubectl`, `helm` v3.12+, and `aws` CLI v2 on any machine used for manual verification
- A GitHub organization/user with both repositories, and permission to configure repository variables and secrets
- A registered domain (or delegated subdomain) per environment — `dev.terasky.com`, `stage.terasky.com`, `prod.terasky.com` — since Terraform creates a Route53 hosted zone but does not register the domain itself

## 2. One-time account bootstrap

Terraform state needs a backend and CI needs an OIDC-federated IAM role before either can run. `bootstrap/bootstrap.py` in `gitops-infra-platform` creates both:

```bash
cd bootstrap/
pip install -r requirements.txt   # boto3
python bootstrap.py dev           # or: stage | prod
```

This provisions, per environment:
- An S3 bucket for Terraform state (versioned, public access blocked)
- A DynamoDB table for state locking
- A GitHub OIDC identity provider (created once, shared across environments)
- Two IAM roles trusted only by GitHub Actions via OIDC, scoped by repository:
  - `github-actions-infra-role-<env>` — used by `gitops-infra-platform` CI, has `AdministratorAccess`
  - `github-actions-ecr-push-<env>` — used by `k8s-node-app` CI, scoped to ECR push only

After running this, copy the printed role ARNs into:
- `gitops-infra-platform` → repository variable `AWS_ROLE_ARN` (used by all three Terraform workflows)
- `k8s-node-app` → the `AWS_ROLE_ARN` value in `.github/workflows/ci-cd.yaml` (currently hardcoded — see Known Limitations)

To tear an environment's bootstrap resources down: `python bootstrap.py dev --destroy`. This does **not** touch the shared OIDC provider.

## 3. Provisioning infrastructure with Terraform

Each environment is a separate root module under `terraform/environments/<env>/`, with its own backend and `.tfvars` file. Modules (`network`, `eks`, `iam`, `dns`, `ecr`) are shared and parameterized per environment.

```bash
cd terraform/environments/dev
terraform init
terraform validate
terraform plan -var-file="dev.tfvars" -out=tfplan
terraform apply tfplan
```

Repeat for `staging` (var file `staging.tfvars`) and `prod` (`prod.tfvars`).

**Note:** the `terraform apply` step in all three GitHub Actions workflows (`terraform-dev.yaml`, `terraform-stage.yaml`, `terraform-prod.yaml`) is currently commented out. CI only runs `plan`. Applies must be run manually (as above) until that's re-enabled — see Known Limitations for the reasoning to consider before uncommenting it.

This stage creates, per environment:
- VPC with public/private subnets across 3 AZs (`network` module)
- EKS cluster with a managed node group using pre-created (not module-managed) IAM roles (`eks` + `iam` modules)
- Route53 hosted zone (`dns` module)
- ECR repository for application images (`ecr` module)
- IRSA roles for the AWS Load Balancer Controller and ExternalDNS, plus a Secrets Manager access policy for node workloads

After `apply`, install cluster add-ons that Terraform's `helm` provider manages in the same root module (AWS Load Balancer Controller). This runs automatically as part of `terraform apply` since it's defined in `helm.tf` alongside the AWS resources.

## 4. Deploying the application

Application delivery is push-based for the image, pull-based for the cluster (standard GitOps split):

1. A push to `k8s-node-app` on `main` or `dev` triggers `.github/workflows/ci-cd.yaml`:
   - Lints the Flask app and the Helm chart
   - Builds and pushes a Docker image to ECR, tagged `dev-<sha>` / `dev-latest` (from `dev` branch) or `prod-<sha>` / `main-latest` (from `main`)
   - Checks out `gitops-infra-platform` (using a PAT stored as `GITHUB_TOKEN_PATCH`) and patches the image tag into the relevant `flux/apps/environments/<env>/helm-release.yaml`, then commits and pushes
2. Flux CD, running inside each cluster, polls `gitops-infra-platform` (`GitRepository` source, 1-minute interval) and reconciles the updated `HelmRelease` (5-minute interval, or immediately on the next Git change), which installs/upgrades the app via the chart in `charts/k8s-node-app`

There is currently no automated promotion from `dev`/`main` pushes to `staging` or `prod` — those `HelmRelease` files are not touched by the pipeline and must be updated manually (or via a separate promotion process you add). See Known Limitations.

## 5. Verifying a deployment

```bash
aws eks update-kubeconfig --name <env>-teraSky-<env> --region eu-central-1
kubectl get pods -n k8s-node-app
kubectl get helmrelease -n k8s-node-app
curl http://<node-app-ingress-address>/health
```

## 6. Local development (application only)

```bash
cd app
pip install -r requirements.txt
python app.py
# GET http://localhost:8080/health
```

`GET /nodes` requires a working kubeconfig or in-cluster service account with the RBAC permissions defined in `charts/k8s-node-app/templates/rbac.yaml` (`get`/`list` on `nodes`).
