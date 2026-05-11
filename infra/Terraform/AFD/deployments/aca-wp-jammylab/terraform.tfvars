# ──────────────────────────────────────────────────────────────────────────────
# terraform.tfvars#
# Each section below maps to a group of columns in the AFD site intake Excel sheet.
# Copy this file to deployments/<site-name>/terraform.tfvars and fill in values.
# ──────────────────────────────────────────────────────────────────────────────

# ── Subscription ─────────────────────────────────────────────────────────────
subscription_id = "a1b2c3d4-1111-4000-8000-111111111111"     # sub-JLB-hub

# ── Site Identity ─────────────────────────────────────────────────────────────
app_name                = "aca-wp-jammylab"
frontdoor_endpoint_name = "dev"    # prod | test | dev | prod-api | test-api | dev-api

# ── Origin ────────────────────────────────────────────────────────────────────
backend_host_name  = "aca-wp-jammylab.focalfossa-1a2b3c4d.eastus2.azurecontainerapps.io"
origin_host_header = "aca-wp-jammylab.jammylab.dev"

# ── Custom Domain & DNS ───────────────────────────────────────────────────────
custom_domain_hostname = "aca-wp-jammylab.jammylab.dev"
dns_zone_name          = "jammylab.dev"
dns_subdomain          = "aca-wp-jammylab"    # leave "" for apex/root domain

# ── Health Probe ──────────────────────────────────────────────────────────────
# [Excel: health_probe_enabled, health_probe_path, health_probe_method]
health_probe_enabled      = true
health_probe_path         = "/healthchecks-api"
health_probe_request_type = "GET"    # HEAD or GET

# ── ILB / PLS ─────────────────────────────────────────────────────────────────
pls_request_message  = "AFD"

# ── Caching ───────────────────────────────────────────────────────────────────
cache_enabled                        = true
cache_query_string_caching_behavior  = "IgnoreSpecifiedQueryStrings"
cache_query_strings                  = ["ver", "_", "nocache"]
cache_compression_enabled            = true
wordpress_cache_bypass               = true

# ── Tags ──────────────────────────────────────────────────────────────────────
tags = {
  "App Owner" = "UGd-org:SHC.IT.Infra"
  Application = "Front Door"
  Environment = "Dev"
  Purpose     = "ACA-WP-SHCCARES TEST SITE"
}
