output "artifact_registry_repository" {
  description = "The Artifact Registry repository ID."
  value       = google_artifact_registry_repository.mcp_repo.id
}

output "artifact_registry_image_path" {
  description = "Base Docker image path in Artifact Registry."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${var.repository_id}/${var.service_name}:${var.image_tag}"
}

output "cloud_run_service_url" {
  description = "The URL of the deployed Cloud Run service."
  value       = google_cloud_run_v2_service.google_ads_mcp.uri
}

output "mcp_endpoint" {
  description = "The HTTP MCP endpoint URL to configure in Antigravity."
  value       = "${google_cloud_run_v2_service.google_ads_mcp.uri}/mcp"
}

output "agy_mcp_command" {
  description = "Run this command to register the MCP server with Antigravity."
  value       = "agy mcp add google-ads-mcp ${google_cloud_run_v2_service.google_ads_mcp.uri}/mcp"
}
