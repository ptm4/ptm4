# ──────────────────────────────────────────────────────────────────────────────
# terraform.tfvars
# Each section below maps to a group of columns in the AFD site intake Excel sheet.
# Copy this file to deployments/<site-name>/terraform.tfvars and fill in values.
# ──────────────────────────────────────────────────────────────────────────────

# ── Subscription ─────────────────────────────────────────────────────────────
subscription_id = "a1b2c3d4-1111-4000-8000-111111111111"     # sub-JLB-hub

# ── Site Identity ─────────────────────────────────────────────────────────────
app_name                = "quillsigner"
frontdoor_endpoint_name = "dev"    # prod | test | dev | prod-api | test-api | dev-api

# ── Origin ────────────────────────────────────────────────────────────────────
backend_host_name  = "quillsigner-dev.azurewebsites.net"
origin_host_header = "quillsigner.jammylab.dev"

# ── Custom Domain & DNS ───────────────────────────────────────────────────────
custom_domain_hostname = "quillsigner.jammylab.dev"
dns_zone_name          = "jammylab.dev"
dns_subdomain          = "quillsigner"    # leave "" for apex/root domain

# ── Health Probe ──────────────────────────────────────────────────────────────
# [Excel: health_probe_enabled, health_probe_path, health_probe_method]
health_probe_enabled      = true
health_probe_path         = "/healthchecks-api"
health_probe_request_type = "GET"    # HEAD or GET

# ── ILB / PLS ─────────────────────────────────────────────────────────────────
pls_request_message  = "AFD"

# ── Tags ──────────────────────────────────────────────────────────────────────
tags = {
  "App Owner" = "UGd-org:SHC.IT.Infra"
  Application = "Front Door"
  Environment = "Dev"
  Purpose     = "quillsigner"
}
