import argparse
import json
import sys
import boto3
import botocore.exceptions

# --- GLOBAL CONFIGURATION ---
REGION = "eu-central-1"
GITHUB_ORG_OR_USER = "romazemelman-alt"

BASE_BUCKET_NAME = "roman-terasky-tf-state"
BASE_DYNAMODB_TABLE = "roman-terasky-tf-locks"
BASE_ECR_REPO_NAME = "k8s-node-app"
BASE_INFRA_ROLE_NAME = "github-actions-infra-role"
BASE_APP_ROLE_NAME = "github-actions-ecr-push"
# ----------------------------

parser = argparse.ArgumentParser(description="Bootstrap/Teardown AWS infrastructure for Terraform Backend & GitHub OIDC per environment.")
parser.add_argument("environment", choices=["dev", "stage", "prod"], help="Target environment (dev, stage, prod)")
parser.add_argument("--destroy", action="store_true", help="Activate destroy mode for the specified environment")
args = parser.parse_args()

ENV = args.environment

BUCKET_NAME = f"{BASE_BUCKET_NAME}-{ENV}"
DYNAMODB_TABLE = f"{BASE_DYNAMODB_TABLE}-{ENV}"
ECR_REPO_NAME = f"{ENV}-{BASE_ECR_REPO_NAME}"
INFRA_ROLE_NAME = f"{BASE_INFRA_ROLE_NAME}-{ENV}"
APP_ROLE_NAME = f"{BASE_APP_ROLE_NAME}-{ENV}"

session = boto3.Session(region_name=REGION)
s3_client = session.client('s3')
s3_resource = session.resource('s3', region_name=REGION)
dynamodb_client = session.client('dynamodb')
ecr_client = session.client('ecr')
iam_client = session.client('iam')
sts_client = session.client('sts')

ACCOUNT_ID = sts_client.get_caller_identity()['Account']
OIDC_PROVIDER_ARN = f"arn:aws:iam::{ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"

# ==================== BOOTSTRAP / APPLY SECTION ====================

def create_s3():
    print(f"[*] Checking/Creating S3 bucket: {BUCKET_NAME}...")
    try:
        s3_client.create_bucket(Bucket=BUCKET_NAME, CreateBucketConfiguration={'LocationConstraint': REGION})
        s3_client.put_bucket_versioning(Bucket=BUCKET_NAME, VersioningConfiguration={'Status': 'Enabled'})
        s3_client.put_public_access_block(
            Bucket=BUCKET_NAME,
            PublicAccessBlockConfiguration={
                'BlockPublicAcls': True, 'IgnorePublicAcls': True,
                'BlockPublicPolicy': True, 'RestrictPublicBuckets': True
            }
        )
        print(f"[+] S3 bucket {BUCKET_NAME} successfully created and secured.")
    except s3_client.exceptions.BucketAlreadyOwnedByYou:
        print(f"[?] S3 bucket {BUCKET_NAME} is already owned by you.")
    except s3_client.exceptions.BucketAlreadyExists:
        print(f"[ERROR] Bucket name {BUCKET_NAME} is globally taken. Choose another BASE_BUCKET_NAME.")
        sys.exit(1)

def create_dynamodb():
    print(f"[*] Checking/Creating DynamoDB table: {DYNAMODB_TABLE}...")
    try:
        dynamodb_client.create_table(
            TableName=DYNAMODB_TABLE,
            KeySchema=[{'AttributeName': 'LockID', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'LockID', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST'
        )
        print(f"[+] DynamoDB table {DYNAMODB_TABLE} successfully created.")
    except dynamodb_client.exceptions.ResourceInUseException:
        print(f"[?] DynamoDB table {DYNAMODB_TABLE} already exists.")

def create_ecr():
    print(f"[*] Checking/Creating ECR repository: {ECR_REPO_NAME}...")
    try:
        ecr_client.create_repository(
            repositoryName=ECR_REPO_NAME,
            imageScanningConfiguration={'scanOnPush': True},
            encryptionConfiguration={'encryptionType': 'AES256'}
        )
        print(f"[+] ECR repository {ECR_REPO_NAME} successfully created.")
    except ecr_client.exceptions.RepositoryAlreadyExistsException:
        print(f"[?] ECR repository {ECR_REPO_NAME} already exists.")

def create_github_oidc():
    print("[*] Configuring OIDC Federation for GitHub Actions...")
    try:
        iam_client.create_open_id_connect_provider(
            Url="https://token.actions.githubusercontent.com",
            ClientIDList=["sts.amazonaws.com"],
            ThumbprintList=["69a88a474f6d01d5ce5da275582c54e7686506a5"]
        )
        print("[+] Global GitHub OIDC Provider created.")
    except iam_client.exceptions.EntityAlreadyExistsException:
        print("[?] Global GitHub OIDC Provider already exists (shared across environments).")

    # 1. INFRASTRUCTURE ROLE CONFIGURATION (gitops-infra-platform repository only)
    infra_trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Federated": OIDC_PROVIDER_ARN},
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                # Strict constraint: allow access only from infrastructure repository
                "StringLike": {"token.actions.githubusercontent.com:sub": f"repo:{GITHUB_ORG_OR_USER}/gitops-infra-platform:*"},
                "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"}
            }
        }]
    }

    try:
        iam_client.create_role(RoleName=INFRA_ROLE_NAME, AssumeRolePolicyDocument=json.dumps(infra_trust_policy))
        iam_client.attach_role_policy(RoleName=INFRA_ROLE_NAME, PolicyArn="arn:aws:iam::aws:policy/AdministratorAccess")
        print(f"[+] IAM Role {INFRA_ROLE_NAME} successfully created for Infrastructure pipeline.")
    except iam_client.exceptions.EntityAlreadyExistsException:
        print(f"[?] IAM Role {INFRA_ROLE_NAME} already exists.")

    # 2. APPLICATION ROLE CONFIGURATION (k8s-node-app repository only)
    app_trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Federated": OIDC_PROVIDER_ARN},
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                # Strict constraint: allow access only from application repository
                "StringLike": {"token.actions.githubusercontent.com:sub": f"repo:{GITHUB_ORG_OR_USER}/k8s-node-app:*"},
                "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"}
            }
        }]
    }

    try:
        iam_client.create_role(RoleName=APP_ROLE_NAME, AssumeRolePolicyDocument=json.dumps(app_trust_policy))
        # Restrict permissions to ECR registry operations only
        iam_client.attach_role_policy(RoleName=APP_ROLE_NAME, PolicyArn="arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser")
        print(f"[+] IAM Role {APP_ROLE_NAME} successfully created for App ECR push pipeline.")
    except iam_client.exceptions.EntityAlreadyExistsException:
        print(f"[?] IAM Role {APP_ROLE_NAME} already exists.")

    # Output final ARNs for easy copy-pasting to GitHub Variables/Workflows
    print("\n" + "="*50)
    print("🚀 USE THESE ARNs IN YOUR GITHUB REPOSITORIES:")
    print(f"1. For gitops-infra-platform (As GitHub Variable 'AWS_ROLE_ARN'):\n   arn:aws:iam::{ACCOUNT_ID}:role/{INFRA_ROLE_NAME}")
    print(f"2. For k8s-node-app (In env 'AWS_ROLE_ARN' inside workflow):\n   arn:aws:iam::{ACCOUNT_ID}:role/{APP_ROLE_NAME}")
    print("="*50 + "\n")

# ==================== TEARDOWN / DESTROY SECTION ====================

def destroy_s3():
    print(f"[*] Purging and deleting S3 bucket: {BUCKET_NAME}...")
    try:
        bucket = s3_resource.Bucket(BUCKET_NAME)
        bucket.object_versions.delete()
        s3_client.delete_bucket(Bucket=BUCKET_NAME)
        print(f"[-] S3 bucket {BUCKET_NAME} successfully deleted.")
    except s3_client.exceptions.NoSuchBucket:
        print(f"[?] S3 bucket {BUCKET_NAME} not found, skipping.")
    except Exception as e:
        print(f"[ERROR] Failed to delete S3 bucket: {e}")

def destroy_dynamodb():
    print(f"[*] Deleting DynamoDB table: {DYNAMODB_TABLE}...")
    try:
        dynamodb_client.delete_table(TableName=DYNAMODB_TABLE)
        print(f"[-] DynamoDB table {DYNAMODB_TABLE} successfully deleted.")
    except dynamodb_client.exceptions.ResourceNotFoundException:
        print(f"[?] DynamoDB table {DYNAMODB_TABLE} not found, skipping.")

def destroy_ecr():
    print(f"[*] Force deleting ECR repository: {ECR_REPO_NAME}...")
    try:
        ecr_client.delete_repository(repositoryName=ECR_REPO_NAME, force=True)
        print(f"[-] ECR repository {ECR_REPO_NAME} successfully deleted.")
    except ecr_client.exceptions.RepositoryNotFoundException:
        print(f"[?] ECR repository {ECR_REPO_NAME} not found, skipping.")

def destroy_github_oidc():
    print(f"[*] Tearing down IAM Roles for environment {ENV}...")

    # Delete infrastructure role
    try:
        iam_client.detach_role_policy(RoleName=INFRA_ROLE_NAME, PolicyArn="arn:aws:iam::aws:policy/AdministratorAccess")
        print(f"[-] AdministratorAccess policy detached from role {INFRA_ROLE_NAME}.")
    except iam_client.exceptions.NoSuchEntityException:
        pass
    try:
        iam_client.delete_role(RoleName=INFRA_ROLE_NAME)
        print(f"[-] IAM Role {INFRA_ROLE_NAME} successfully deleted.")
    except iam_client.exceptions.NoSuchEntityException:
        print(f"[?] IAM Role {INFRA_ROLE_NAME} not found, skipping.")

    # Delete application role
    try:
        iam_client.detach_role_policy(RoleName=APP_ROLE_NAME, PolicyArn="arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser")
        print(f"[-] AmazonEC2ContainerRegistryPowerUser policy detached from role {APP_ROLE_NAME}.")
    except iam_client.exceptions.NoSuchEntityException:
        pass
    try:
        iam_client.delete_role(RoleName=APP_ROLE_NAME)
        print(f"[-] IAM Role {APP_ROLE_NAME} successfully deleted.")
    except iam_client.exceptions.NoSuchEntityException:
        print(f"[?] IAM Role {APP_ROLE_NAME} not found, skipping.")

    print("[*] Note: Global GitHub OIDC Provider left intact to prevent breaking other environments.")

# ==================== ENTRYPOINT ====================

if __name__ == "__main__":
    if args.destroy:
        print(f"🚨 WARNING: DESTROY MODE ACTIVATED FOR ENVIRONMENT: {ENV.upper()} 🚨")
        print(f"This will wipe out: S3 ({BUCKET_NAME}), DynamoDB ({DYNAMODB_TABLE}), ECR ({ECR_REPO_NAME}) and IAM Roles ({INFRA_ROLE_NAME} & {APP_ROLE_NAME})")
        confirm = input(f"Are you sure you want to completely delete resources for {ENV}? (yes/no): ")
        if confirm.lower() == 'yes':
            destroy_ecr()
            destroy_s3()
            destroy_dynamodb()
            destroy_github_oidc()
            print(f"=== ALL BOOTSTRAP RESOURCES FOR {ENV.upper()} PURGED ===")
        else:
            print("[*] Destroy aborted.")
    else:
        print(f"=== STARTING INFRASTRUCTURE BOOTSTRAP FOR ENVIRONMENT: {ENV.upper()} ===")
        create_s3()
        create_dynamodb()
        # create_ecr()  # Managed via Terraform modules
        create_github_oidc()
        print(f"=== ALL BOOTSTRAP RESOURCES FOR {ENV.upper()} ARE READY ===")