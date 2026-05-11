output "pls_id" {
  description = "Resource ID of the Private Link Service (pls-<app_name>)."
  value       = azurerm_private_link_service.pls.id
}

output "pls_name" {
  description = "Name of the Private Link Service."
  value       = azurerm_private_link_service.pls.name
}

output "lb_rule_id" {
  description = "Resource ID of the ILB load balancing rule (lbr-<app_name>)."
  value       = azurerm_lb_rule.ha_ports.id
}

output "frontend_ip_name" {
  description = "Derived ILB frontend IP configuration name (AFD-<app_name>). Use this to verify the pre-created frontend IP name matches."
  value       = local.frontend_ip_name
}

output "frontend_ip_id" {
  description = "Derived ILB frontend IP resource ID used by the PLS. Use this to verify the pre-created resource ID matches."
  value       = local.frontend_ip_id
}
