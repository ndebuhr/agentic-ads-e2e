# Google Ads E2E Automation

This directory contains the infrastructure, git submodule, and configuration to run Google Ads campaigns end-to-end via the official Google Ads Model Context Protocol (MCP) server hosted on **Google Cloud Run** using **Artifact Registry** in your Google Cloud project.

## Architecture

```
google-ads-e2e/
├── google-ads-mcp/       # Official Google Ads MCP server (Git Submodule)
└── terraform/            # Infrastructure as Code (GCP APIs, Artifact Registry, Cloud Run)
    ├── main.tf
    ├── variables.tf
    ├── outputs.tf
    └── terraform.tfvars.example
```

---

## Deployment Walkthrough

### 1. Prerequisites
- A Google Cloud project
- `gcloud` authenticated (`gcloud auth login`)
- `terraform` (v1.5+)
- Google Cloud OAuth 2.0 Web Client ID & Secret (for FastMCP OAuth proxy)
  - 

Terraform uses Application Default Credentials, not the active `gcloud` account. To use the active account instead, export its token before running Terraform (the token expires after about an hour):

```bash
export GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token)
```

### 2. Configure Terraform Variables
Copy the template and fill in your credentials:

```bash
cd google-ads-e2e/terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:
```hcl
project_id          = ""
region              = "us-central1"
oauth_client_id     = "YOUR_CLIENT_ID.apps.googleusercontent.com"
oauth_client_secret = "YOUR_CLIENT_SECRET"
```

### 3. Provision Artifact Registry & APIs
Initialize, create the Artifact Registry repository, and grant Cloud Build's service account the builder role:

```bash
terraform init
terraform apply \
  -target=google_artifact_registry_repository.mcp_repo \
  -target=google_project_iam_member.cloudbuild_builder
```

### 4. Build and Push Container Image
Build the container image using Cloud Build directly from the submodule (no local Docker daemon required):

```bash
PROJECT_ID=<same project_id as terraform.tfvars>
gcloud builds submit \
  --tag us-central1-docker.pkg.dev/$PROJECT_ID/mcp-servers/google-ads-mcp:latest \
  ../google-ads-mcp \
  --project=$PROJECT_ID
```

### 5. Deploy Cloud Run Service
Deploy the Cloud Run service and permissions using Terraform:

```bash
terraform apply
```

Terraform outputs will display:
- `cloud_run_service_url`: The HTTPS endpoint of the deployed Cloud Run service
- `mcp_endpoint`: `${cloud_run_service_url}/mcp`
- `agy_mcp_command`: Ready-to-run CLI command to register with Antigravity

### 5a. Feed the Cloud Run URL Back into OAuth
The Cloud Run URL is only known after the first deploy, and the OAuth proxy needs it in two places:

1. In the OAuth 2.0 Web Client (Google Cloud Console > APIs & Services > Credentials), add:
   - Authorized JavaScript origin: `https://<cloud-run-service-url>`
   - Authorized redirect URI: `https://<cloud-run-service-url>/auth/callback`
2. In `terraform.tfvars`, set `base_url = "https://<cloud-run-service-url>"`, then re-run `terraform apply` to redeploy with `GOOGLE_ADS_MCP_BASE_URL`.

### 6. Configure Antigravity MCP Client
Register the Cloud Run endpoint with the Antigravity CLI:

```bash
agy mcp add google-ads-mcp https://<cloud-run-service-url>/mcp
```

Verify it is registered:
```bash
agy mcp list
```

### 7. Interactive Authentication
When Antigravity initiates requests to the Cloud Run server, FastMCP's OAuth proxy prompts for Google authorization in your browser. Once authorized, Antigravity has full access to the Google Ads MCP tools.
