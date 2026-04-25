output "origin_group_id" {
  description = "Resource ID of the AFD origin group (og-<app_name>)."
  value       = azurerm_cdn_frontdoor_origin_group.origin_group.id
}

output "origin_id" {
  description = "Resource ID of the AFD origin (o-<app_name>)."
  value       = azurerm_cdn_frontdoor_origin.origin.id
}

output "custom_domain_id" {
  description = "Resource ID of the AFD custom domain."
  value       = azurerm_cdn_frontdoor_custom_domain.domain.id
}

output "custom_domain_validation_token" {
  description = "Domain validation token — written to the _dnsauth TXT record automatically by this module."
  value       = azurerm_cdn_frontdoor_custom_domain.domain.validation_token
}

output "route_id" {
  description = "Resource ID of the AFD route (rt-<app_name>)."
  value       = azurerm_cdn_frontdoor_route.route.id
}

output "waf_policy_id" {
  description = "Resource ID of the AFD WAF firewall policy (waf<app_name_no_dashes>)."
  value       = azurerm_cdn_frontdoor_firewall_policy.waf.id
}

output "security_policy_id" {
  description = "Resource ID of the AFD security policy (waf-<app_name>)."
  value       = azurerm_cdn_frontdoor_security_policy.security_policy.id
}
