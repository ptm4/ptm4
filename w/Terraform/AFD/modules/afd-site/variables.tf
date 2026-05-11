# ──────────────────────────────────────────────────────────────────────────────
# EXCEL COLUMN MAPPING NOTE
# Variables in this module map 1-to-1 with columns in the AFD site intake sheet.
# All inputs are simple primitives (string / bool / number) to allow direct
# generation of tfvars files from a spreadsheet row with no transformation.
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────
# AFD Profile (existing — constant across all deployments)
# ──────────────────────────────────────────────
variable "frontdoor_profile_name" {
  type        = string
  description = "Name of the existing Azure Front Door profile. [Excel: afd_profile_name]"
  default     = "fd-JLB-Hub-FrontDoor"
}

variable "frontdoor_resource_group_name" {
  type        = string
  description = "Resource group containing the AFD profile and WAF policies. [Excel: afd_resource_group]"
  default     = "rg-JLB-Hub-FrontDoor"
}

variable "frontdoor_endpoint_name" {
  type        = string
  description = "Existing AFD endpoint to attach the route to. Valid values: prod | test | dev | prod-api | test-api | dev-api. [Excel: afd_endpoint]"
}

# ──────────────────────────────────────────────
# Site Identity
# ──────────────────────────────────────────────
variable "app_name" {
  type        = string
  description = "Short application/service name. Drives all resource naming: og-<name>, o-<name>, rt-<name>, waf-<name>, waf<name_nodashes>. [Excel: app_name]"
}

# ──────────────────────────────────────────────
# Origin
# ──────────────────────────────────────────────
variable "backend_host_name" {
  type        = string
  description = "Hostname of the origin backend (e.g. app.azurewebsites.net). [Excel: backend_host_name]"
}

variable "origin_host_header" {
  type        = string
  description = "Host header forwarded to the origin. Leave null to use backend_host_name. [Excel: origin_host_header]"
  default     = null
}

# ──────────────────────────────────────────────
# Custom Domain & DNS
# ──────────────────────────────────────────────
variable "custom_domain_hostname" {
  type        = string
  description = "Full custom domain hostname registered on AFD (e.g. api-weconnect.jammylab.com). [Excel: custom_domain_hostname]"
}

variable "dns_zone_name" {
  type        = string
  description = "Azure DNS zone containing the domain (e.g. jammylab.com or jammylab.dev). [Excel: dns_zone_name]"
}

variable "dns_zone_resource_group_name" {
  type        = string
  description = "Resource group containing the Azure DNS zone. [Excel: dns_zone_rg]"
  default     = "rg-JLB-Hub-Public_DNS_Zones"
}

variable "dns_subdomain" {
  type        = string
  description = "Subdomain label for the CNAME record (e.g. 'api-weconnect'). Leave empty string for apex/root domains — CNAME is skipped, alias A record required manually. [Excel: dns_subdomain]"
  default     = ""
}

# ──────────────────────────────────────────────
# Private Link (required — all SHC AFD sites are PLS-backed)
# ──────────────────────────────────────────────
variable "private_link_service_id" {
  type        = string
  description = "Resource ID of the Private Link Service for this site. Output from afd-pls-stack module. [Excel: pls_resource_id]"
}

variable "private_link_location" {
  type        = string
  description = "Azure region where the Private Link Service is deployed. [Excel: pls_location]"
  default     = "eastus2"
}

variable "pls_request_message" {
  type        = string
  description = "Approval request message sent to the PLS owner. [Excel: pls_request_message]"
  default     = "AFD"
}

# ──────────────────────────────────────────────
# Health Probe
# ──────────────────────────────────────────────
variable "health_probe_enabled" {
  type        = bool
  description = "Enable health probe on the origin group. Disable only for origins with no health endpoint. [Excel: health_probe_enabled]"
  default     = true
}

variable "health_probe_path" {
  type        = string
  description = "URL path for the health probe request. [Excel: health_probe_path]"
  default     = "/"
}

variable "health_probe_protocol" {
  type        = string
  description = "Protocol for the health probe: Http or Https. [Excel: health_probe_protocol]"
  default     = "Http"

  validation {
    condition     = contains(["Http", "Https"], var.health_probe_protocol)
    error_message = "health_probe_protocol must be 'Http' or 'Https'."
  }
}

variable "health_probe_request_type" {
  type        = string
  description = "HTTP method for the health probe: HEAD or GET. [Excel: health_probe_method]"
  default     = "HEAD"

  validation {
    condition     = contains(["HEAD", "GET"], var.health_probe_request_type)
    error_message = "health_probe_request_type must be 'HEAD' or 'GET'."
  }
}

variable "health_probe_interval" {
  type        = number
  description = "Health probe interval in seconds. [Excel: health_probe_interval]"
  default     = 100
}

# ──────────────────────────────────────────────
# Route
# ──────────────────────────────────────────────
variable "supported_protocols" {
  type        = list(string)
  description = "Protocols accepted on the route. [Excel: route_protocols]"
  default     = ["Http","Https"]
}

variable "route_patterns_to_match" {
  type        = list(string)
  description = "URL path patterns the route matches. [Excel: route_patterns]"
  default     = ["/*"]
}

# ──────────────────────────────────────────────
# Caching (opt-in — disabled by default)
# ──────────────────────────────────────────────
variable "cache_enabled" {
  type        = bool
  description = "Enable caching on the route. When false (default) the cache block is omitted entirely. [Excel: cache_enabled]"
  default     = false
}

variable "cache_query_string_caching_behavior" {
  type        = string
  description = "How query strings affect cache keys: IgnoreQueryString | IgnoreSpecifiedQueryStrings | IncludeSpecifiedQueryStrings | UseQueryString. [Excel: cache_qs_behavior]"
  default     = "IgnoreQueryString"

  validation {
    condition     = contains(["IgnoreQueryString", "IgnoreSpecifiedQueryStrings", "IncludeSpecifiedQueryStrings", "UseQueryString"], var.cache_query_string_caching_behavior)
    error_message = "cache_query_string_caching_behavior must be one of: IgnoreQueryString, IgnoreSpecifiedQueryStrings, IncludeSpecifiedQueryStrings, UseQueryString."
  }
}

variable "cache_query_strings" {
  type        = list(string)
  description = "Query string names used with IgnoreSpecifiedQueryStrings or IncludeSpecifiedQueryStrings. Leave empty for IgnoreQueryString / UseQueryString. [Excel: cache_query_strings]"
  default     = []
}

variable "cache_compression_enabled" {
  type        = bool
  description = "Enable compression for cached responses. [Excel: cache_compression_enabled]"
  default     = true
}

variable "cache_content_types_to_compress" {
  type        = list(string)
  description = "MIME types to compress when cache_compression_enabled is true. Required by Azure when compression is on. [Excel: cache_content_types]"
  default = [
    "application/javascript",
    "application/json",
    "application/xml",
    "font/eot",
    "font/otf",
    "font/ttf",
    "image/svg+xml",
    "text/css",
    "text/html",
    "text/javascript",
    "text/plain",
    "text/xml",
  ]
}

# ──────────────────────────────────────────────
# WordPress Cache Bypass (opt-in)
# ──────────────────────────────────────────────
variable "wordpress_cache_bypass" {
  type        = bool
  description = "Create a rule set that bypasses AFD cache for wp-admin, wp-login, and logged-in WordPress users. Enable for WordPress sites. [Excel: wordpress_cache_bypass]"
  default     = false
}

# ──────────────────────────────────────────────
# WAF
# ──────────────────────────────────────────────
variable "waf_mode" {
  type        = string
  description = "WAF policy enforcement mode: Prevention or Detection. [Excel: waf_mode]"
  default     = "Prevention"

  validation {
    condition     = contains(["Prevention", "Detection"], var.waf_mode)
    error_message = "waf_mode must be 'Prevention' or 'Detection'."
  }
}

# ──────────────────────────────────────────────
# Tags
# ──────────────────────────────────────────────
variable "tags" {
  type        = map(string)
  description = "Tags applied to all resources created by this module. Typically a shared constant set from the deployment root."
  default     = {}
}
