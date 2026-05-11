# ──────────────────────────────────────────────────────────────────────────────
# EXCEL COLUMN MAPPING NOTE
# Each variable below corresponds to a column in the AFD site intake spreadsheet.
# One Excel row = one deployment folder + one tfvars file.
# Column names in [brackets] are the suggested Excel headers for each field.
# Backend configuration is supplied entirely by the pipeline — no backend
# variables exist here. Subscription is the only shared constant in tfvars.
# ──────────────────────────────────────────────────────────────────────────────

# ── Subscription (shared constant) ────────────────────────────────────────────
variable "subscription_id" {
  type        = string
  description = "Azure subscription ID used by the AzureRM provider. sub-JLB-hub = a1b2c3d4-1111-4000-8000-111111111111"
}

# ── Site Identity ─────────────────────────────────────────────────────────────
variable "app_name" {
  type        = string
  description = <<-EOT
    Short name for this AFD site. Drives all resource naming:
      og-<app_name>    origin group
      o-<app_name>     origin
      rt-<app_name>    route
      waf-<app_name>   security policy
      waf<name>        WAF policy (dashes stripped)
      lbr-<app_name>   ILB load balancing rule
      pls-<app_name>   Private Link Service
      AFD-<app_name>   ILB frontend IP (pre-created)
    [Excel: app_name]
  EOT
}

variable "frontdoor_endpoint_name" {
  type        = string
  description = "Existing AFD endpoint to place this site on. Valid: prod | test | dev | prod-api | test-api | dev-api [Excel: afd_endpoint]"
}

# ── Origin ────────────────────────────────────────────────────────────────────
variable "backend_host_name" {
  type        = string
  description = "Origin hostname (e.g. app.azurewebsites.net or static app URL). [Excel: backend_host_name]"
}

variable "origin_host_header" {
  type        = string
  description = "Host header sent to origin. Leave null to default to backend_host_name. [Excel: origin_host_header]"
  default     = null
}

# ── Custom Domain & DNS ───────────────────────────────────────────────────────
variable "custom_domain_hostname" {
  type        = string
  description = "Full custom domain hostname (e.g. weconnect-qa.jammylab.dev). [Excel: custom_domain]"
}

variable "dns_zone_name" {
  type        = string
  description = "Azure DNS zone containing the domain (e.g. jammylab.dev or jammylab.com). [Excel: dns_zone]"
}

variable "dns_subdomain" {
  type        = string
  description = "Subdomain label for CNAME record (e.g. 'weconnect-qa'). Leave empty string for apex/root domains. [Excel: dns_subdomain]"
  default     = ""
}

# ── Health Probe ──────────────────────────────────────────────────────────────
variable "health_probe_enabled" {
  type        = bool
  description = "Enable health probe. Set false only for origins with no health endpoint. [Excel: health_probe_enabled]"
  default     = true
}

variable "health_probe_path" {
  type        = string
  description = "Health probe URL path (e.g. / or /healthchecks-api). [Excel: health_probe_path]"
  default     = "/"
}

variable "health_probe_request_type" {
  type        = string
  description = "Health probe HTTP method: HEAD or GET. [Excel: health_probe_method]"
  default     = "HEAD"
}

# ── ILB / PLS (per-site) ─────────────────────────────────────────────────────
# The ILB frontend IP name (AFD-<app_name>) and full resource ID are
# auto-derived inside the afd-pls-stack module — no Terraform input needed here.
#
# PREREQUISITE: Before terraform apply, create "AFD-<app_name>" on
# FGHA-NorthSouth-internalloadbalancer with a static private IP from
# snet-afd-prod. Record the allocated IP in the intake Excel sheet
# (ilb_private_ip column) for documentation — it is not a tfvars field.

variable "pls_request_message" {
  type        = string
  description = "Approval request message sent with the PLS connection. [Excel: pls_request_message]"
  default     = "AFD"
}

# ── Tags (shared constant — same for all SHC AFD sites) ───────────────────────
variable "tags" {
  type        = map(string)
  description = "Resource tags. Typically kept constant across all AFD site deployments."
  default = {
    "App Owner" = "UGd-org:SHC.IT.Infra"
    Application = "Front Door"
    Environment = "Hub"
    Purpose     = "Public web application CDN, WAF, and gateway"
  }
}

# ── Caching (opt-in — disabled by default) ────────────────────────────────────
variable "cache_enabled" {
  type        = bool
  description = "Enable caching on the AFD route. [Excel: cache_enabled]"
  default     = false
}

variable "cache_query_string_caching_behavior" {
  type        = string
  description = "How query strings affect cache keys: IgnoreQueryString | IgnoreSpecifiedQueryStrings | IncludeSpecifiedQueryStrings | UseQueryString. [Excel: cache_qs_behavior]"
  default     = "IgnoreQueryString"
}

variable "cache_query_strings" {
  type        = list(string)
  description = "Query strings to include/exclude when using IgnoreSpecifiedQueryStrings or IncludeSpecifiedQueryStrings. [Excel: cache_query_strings]"
  default     = []
}

variable "cache_compression_enabled" {
  type        = bool
  description = "Enable compression for cached responses. [Excel: cache_compression_enabled]"
  default     = true
}

variable "cache_content_types_to_compress" {
  type        = list(string)
  description = "MIME types to compress. Uses module default (standard web types) if not set. [Excel: cache_content_types]"
  default     = []
}
