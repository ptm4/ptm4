output "pls_id" {
  description = "Resource ID of the Private Link Service (pls-<app_name>)."
  value       = module.pls_stack.pls_id
}

output "custom_domain_id" {
  description = "Resource ID of the AFD custom domain."
  value       = module.afd_site.custom_domain_id
}

output "waf_policy_id" {
  description = "Resource ID of the AFD WAF firewall policy."
  value       = module.afd_site.waf_policy_id
}

output "route_id" {
  description = "Resource ID of the AFD route."
  value       = module.afd_site.route_id
}
