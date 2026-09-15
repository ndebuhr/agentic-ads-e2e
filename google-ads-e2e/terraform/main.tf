terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Required Google Cloud APIs
locals {
  services = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "run.googleapis.com",
    "googleads.googleapis.com",
    "orgpolicy.googleapis.com"
  ])
}

resource "google_project_service" "services" {
  for_each                   = local.services
  project                    = var.project_id
  service                    = each.key
  disable_on_destroy         = false
  disable_dependent_services = false
}

# Artifact Registry Docker Repository
resource "google_artifact_registry_repository" "mcp_repo" {
  project       = var.project_id
  location      = var.region
  repository_id = var.repository_id
  description   = "Docker repository for MCP servers"
  format        = "DOCKER"

  depends_on = [
    google_project_service.services["artifactregistry.googleapis.com"]
  ]
}

# Cloud Build runs as the Compute Engine default service account, which new
# projects no longer grant Editor. It needs the builder role to read the
# source bucket and push to Artifact Registry.
data "google_project" "project" {
  project_id = var.project_id
}

resource "google_project_iam_member" "cloudbuild_builder" {
  project = var.project_id
  role    = "roles/cloudbuild.builds.builder"
  member  = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"

  depends_on = [
    google_project_service.services["cloudbuild.googleapis.com"]
  ]
}

# Cloud Run Service for Google Ads MCP
resource "google_cloud_run_v2_service" "google_ads_mcp" {
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${var.repository_id}/${var.service_name}:${var.image_tag}"

      ports {
        container_port = 8080
      }

      env {
        name  = "GOOGLE_PROJECT_ID"
        value = var.project_id
      }

      env {
        name  = "FASTMCP_HOST"
        value = "0.0.0.0"
      }

      dynamic "env" {
        for_each = var.google_ads_developer_token != "" ? [1] : []
        content {
          name  = "GOOGLE_ADS_DEVELOPER_TOKEN"
          value = var.google_ads_developer_token
        }
      }

      dynamic "env" {
        for_each = var.oauth_client_id != "" ? [1] : []
        content {
          name  = "GOOGLE_ADS_MCP_OAUTH_CLIENT_ID"
          value = var.oauth_client_id
        }
      }

      dynamic "env" {
        for_each = var.oauth_client_secret != "" ? [1] : []
        content {
          name  = "GOOGLE_ADS_MCP_OAUTH_CLIENT_SECRET"
          value = var.oauth_client_secret
        }
      }

      dynamic "env" {
        for_each = var.google_ads_login_customer_id != "" ? [1] : []
        content {
          name  = "GOOGLE_ADS_LOGIN_CUSTOMER_ID"
          value = var.google_ads_login_customer_id
        }
      }

      dynamic "env" {
        for_each = var.base_url != "" ? [1] : []
        content {
          name  = "GOOGLE_ADS_MCP_BASE_URL"
          value = var.base_url
        }
      }
    }
  }

  depends_on = [
    google_project_service.services["run.googleapis.com"],
    google_artifact_registry_repository.mcp_repo
  ]
}

# The organization enforces domain restricted sharing, which rejects allUsers.
# Override it for this project only so the Cloud Run service can be public.
resource "google_org_policy_policy" "allow_public_members" {
  name   = "projects/${var.project_id}/policies/iam.allowedPolicyMemberDomains"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      allow_all = "TRUE"
    }
  }

  depends_on = [
    google_project_service.services["orgpolicy.googleapis.com"]
  ]
}

# Allow unauthenticated access (FastMCP handles OAuth proxy authentication)
resource "google_cloud_run_v2_service_iam_member" "invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.google_ads_mcp.name
  role     = "roles/run.invoker"
  member   = "allUsers"

  depends_on = [google_org_policy_policy.allow_public_members]
}
