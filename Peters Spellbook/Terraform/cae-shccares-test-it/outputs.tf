# outputs.tf

output "mysql_fqdn" {
  value       = azurerm_mysql_flexible_server.wordpress.fqdn
  description = "The FQDN for the MySQL flexible server"
}

output "mysql_private_ip" {
  value       = azurerm_private_endpoint.cae_pe.private_service_connection[0].private_ip_address
  description = "Private IP assigned via private endpoint"
}