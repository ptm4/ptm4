# ──────────────────────────────────────────────────────────────────────────────
# terraform.tfvars
# Each section below maps to a group of columns in the AFD site intake Excel sheet.
# Copy this file to deployments/<site-name>/terraform.tfvars and fill in values.
# ──────────────────────────────────────────────────────────────────────────────

# ── Subscription ─────────────────────────────────────────────────────────────
subscription_id = "a1b2c3d4-1111-4000-8000-111111111111"     # sub-JLB-hub

# ── Site Identity ─────────────────────────────────────────────────────────────
app_name                = "quillsigner-qa"
frontdoor_endpoint_name = "test"    # prod | test | dev | prod-api | test-api | dev-api

# ── Origin ────────────────────────────────────────────────────────────────────
backend_host_name  = "quillsigner-qa.azurewebsites.net"
origin_host_header = "quillsigner-qa.jammylab.dev"

# ── Custom Domain & DNS ───────────────────────────────────────────────────────
custom_domain_hostname = "quillsigner-qa.jammylab.dev"
dns_zone_name          = "jammylab.dev"
dns_subdomain          = "quillsigner-qa"    # leave "" for apex/root domain

# ── Health Probe ──────────────────────────────────────────────────────────────
# [Excel: health_probe_enabled, health_probe_path, health_probe_method]
health_probe_enabled      = true
health_probe_path         = "/health"
health_probe_request_type = "GET"    # HEAD or GET

# ── ILB / PLS ─────────────────────────────────────────────────────────────────
pls_request_message = "AFD"

# ── Caching (opt-in — disabled by default) ────────────────────────────────────
# cache_query_string_caching_behavior options:
#   IgnoreQueryString             — same cached response regardless of query string (default)
#   UseQueryString                — unique cache entry per distinct query string
#   IgnoreSpecifiedQueryStrings   — ignore listed query strings, cache on the rest
#   IncludeSpecifiedQueryStrings  — cache on listed query strings only
cache_enabled                       = false
cache_query_string_caching_behavior = "IgnoreQueryString"
cache_query_strings                 = []     # populate when using Ignore/IncludeSpecified behaviors
cache_compression_enabled           = false  # set true to compress cached responses (gzip/brotli)
cache_content_types_to_compress     = []     # leave empty to use the module's built-in default MIME type list

# ── Tags ──────────────────────────────────────────────────────────────────────
tags = {
  "App Owner" = "UGd-org:SHC.IT.Infra"
  Application = "Front Door"
  Environment = "QA"
  Purpose     = "quillsigner-qa"
}
