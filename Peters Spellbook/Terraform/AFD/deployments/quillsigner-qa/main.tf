# ──────────────────────────────────────────────────────────────────────────────
# DEPLOYMENT: quillsigner
#
# Copy this folder to deployments/<your-site-name>/ and fill in terraform.tfvars.
# All SHC AFD sites use the PLS path — both modules always run.
#
# PREREQUISITE before terraform apply:
#   1. Create ILB frontend IP "AFD-<app_name>" on FGHA-NorthSouth-internalloadbalancer.
#      Type: Private / Static  |  Subnet: snet-afd-prod
#      IP: allocate from the network allocation tracker and record in the intake
#          Excel sheet (ilb_private_ip column). This IP is not a Terraform input.
#   2. The module auto-derives the frontend IP name (AFD-<app_name>) and full
#      resource ID — no manual ID entry required.
# ──────────────────────────────────────────────────────────────────────────────

locals {
  tags = merge(var.tags, {
    CreationDate = ""
  })
}

# ──────────────────────────────────────────────────────────────────────────────
# PLS Stack — ILB load balancing rule + Private Link Service
# ──────────────────────────────────────────────────────────────────────────────
module "pls_stack" {
  source = "../../modules/afd-pls-stack"

  app_name = var.app_name

  # Defaults are hardwired to the shared NorthSouth ILB and hub VNet.
  # Override below only if targeting a different ILB or subnet.
  # ilb_resource_group_name = "rg-network-prod"
  # ilb_name                = "FGHA-NorthSouth-internalloadbalancer"
  # vnet_name               = "vnet-hub-prod-eus2"
  # internal_subnet_name    = "snet-afd-prod"
  # pls_resource_group_name = "rg-JLB-Hub-FrontDoor"

  tags = local.tags
}

# ──────────────────────────────────────────────────────────────────────────────
# AFD Site — origin group, origin (PLS-backed), custom domain, DNS records,
#            route, WAF policy (bot protection), security policy
# ──────────────────────────────────────────────────────────────────────────────
module "afd_site" {
  source = "../../modules/afd-site"

  # ── AFD Profile (existing — constant for all SHC deployments) ───────────────
  frontdoor_profile_name        = "fd-JLB-Hub-FrontDoor"
  frontdoor_resource_group_name = "rg-JLB-Hub-FrontDoor"
  frontdoor_endpoint_name       = var.frontdoor_endpoint_name

  # ── Site Identity ────────────────────────────────────────────────────────────
  app_name = var.app_name

  # ── Origin ───────────────────────────────────────────────────────────────────
  backend_host_name  = var.backend_host_name
  origin_host_header = var.origin_host_header

  # ── Custom Domain & DNS ──────────────────────────────────────────────────────
  custom_domain_hostname       = var.custom_domain_hostname
  dns_zone_name                = var.dns_zone_name
  dns_zone_resource_group_name = "rg-JLB-Hub-Public_DNS_Zones"
  dns_subdomain                = var.dns_subdomain

  # ── Private Link (PLS ID sourced from pls_stack output) ─────────────────────
  private_link_service_id = module.pls_stack.pls_id
  private_link_location   = "eastus2"
  pls_request_message     = var.pls_request_message

  # ── Health Probe ─────────────────────────────────────────────────────────────
  health_probe_enabled      = var.health_probe_enabled
  health_probe_path         = var.health_probe_path
  health_probe_request_type = var.health_probe_request_type
  # health_probe_protocol   = "Http"   # default — override if origin requires HTTPS probe
  # health_probe_interval   = 100      # default

  # ── Route ────────────────────────────────────────────────────────────────────
  # Default ["Https"]. Change to ["Http","Https"] only if this route needs a
  # redirect rule set that receives plain HTTP.
  # supported_protocols = ["Http", "Https"]

  # ── Caching ──────────────────────────────────────────────────────────────────
  cache_enabled                       = var.cache_enabled
  cache_query_string_caching_behavior = var.cache_query_string_caching_behavior
  cache_query_strings                 = var.cache_query_strings
  cache_compression_enabled           = var.cache_compression_enabled
  cache_content_types_to_compress     = var.cache_content_types_to_compress

  # ── WAF ──────────────────────────────────────────────────────────────────────
  waf_mode = "Prevention"

  tags = local.tags

  depends_on = [module.pls_stack]
}
