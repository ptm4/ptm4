# Container registry (custom WordPress image builds).

output "acr_login_server" {
  description = "ACR hostname for docker login and image references."
  value       = azurerm_container_registry.wp.login_server
}

output "acr_id" {
  description = "ACR resource ID."
  value       = azurerm_container_registry.wp.id
}

output "custom_image_example" {
  description = "Example image reference after pushing repository wp-jammylab."
  value       = "${azurerm_container_registry.wp.login_server}/wp-jammylab:latest"
}
