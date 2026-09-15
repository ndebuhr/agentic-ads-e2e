variable "project_id" {
  type        = string
  description = "The Google Cloud project ID."
}

variable "region" {
  type        = string
  description = "The Google Cloud region to deploy resources to."
  default     = "us-central1"
}

variable "repository_id" {
  type        = string
  description = "The Artifact Registry repository ID for container images."
  default     = "mcp-servers"
}

variable "service_name" {
  type        = string
  description = "The Cloud Run service name."
  default     = "google-ads-mcp"
}

variable "image_tag" {
  type        = string
  description = "The container image tag."
  default     = "latest"
}

variable "google_ads_developer_token" {
  type        = string
  description = "The Google Ads API Developer Token."
  default     = ""
  sensitive   = true
}

variable "oauth_client_id" {
  type        = string
  description = "The OAuth 2.0 Client ID for FastMCP OAuth proxy."
  default     = ""
  sensitive   = true
}

variable "oauth_client_secret" {
  type        = string
  description = "The OAuth 2.0 Client Secret for FastMCP OAuth proxy."
  default     = ""
  sensitive   = true
}

variable "google_ads_login_customer_id" {
  type        = string
  description = "The Google Ads Manager Account (MCC) Customer ID, if applicable."
  default     = ""
}

variable "base_url" {
  type        = string
  description = "The base URL where the Cloud Run service is accessible (for OAuth proxy redirect). Set after initial deploy or with custom domain."
  default     = ""
}

