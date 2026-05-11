# ──────────────────────────────────────────────────────────────────────────────
# Data Sources — existing AFD infrastructure
# ──────────────────────────────────────────────────────────────────────────────
data "azurerm_cdn_frontdoor_profile" "profile" {
  name                = var.frontdoor_profile_name
  resource_group_name = var.frontdoor_resource_group_name
}

data "azurerm_cdn_frontdoor_endpoint" "endpoint" {
  name                = var.frontdoor_endpoint_name
  profile_name        = var.frontdoor_profile_name
  resource_group_name = var.frontdoor_resource_group_name
}

data "azurerm_dns_zone" "zone" {
  name                = var.dns_zone_name
  resource_group_name = var.dns_zone_resource_group_name
}

# ──────────────────────────────────────────────────────────────────────────────
# Naming locals — keep consistent with SHC conventions
# ──────────────────────────────────────────────────────────────────────────────
locals {
  origin_group_name    = "og-${var.app_name}"
  origin_name          = "o-${var.app_name}"
  route_name           = "rt-${var.app_name}"
  security_policy_name = "waf-${var.app_name}"
  # WAF policy names must be alphanumeric only (no dashes)
  waf_policy_name = "waf${replace(lower(var.app_name), "-", "")}"

  # Fall back to standard web content types when caller passes empty list
  effective_content_types_to_compress = length(var.cache_content_types_to_compress) > 0 ? var.cache_content_types_to_compress : [
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

# ──────────────────────────────────────────────────────────────────────────────
# Origin Group  (og-<app_name>)
# ──────────────────────────────────────────────────────────────────────────────
resource "azurerm_cdn_frontdoor_origin_group" "origin_group" {
  name                     = local.origin_group_name
  cdn_frontdoor_profile_id = data.azurerm_cdn_frontdoor_profile.profile.id
  session_affinity_enabled = false

  load_balancing {
    sample_size                        = 4
    successful_samples_required        = 3
    additional_latency_in_milliseconds = 50
  }

  dynamic "health_probe" {
    for_each = var.health_probe_enabled ? [1] : []
    content {
      path                = var.health_probe_path
      request_type        = var.health_probe_request_type
      protocol            = var.health_probe_protocol
      interval_in_seconds = var.health_probe_interval
    }
  }
}

# ──────────────────────────────────────────────────────────────────────────────
# Origin  (o-<app_name>) — one per origin group per SHC standard
# All SHC AFD sites are PLS-backed; private_link is always configured.
# ──────────────────────────────────────────────────────────────────────────────
resource "azurerm_cdn_frontdoor_origin" "origin" {
  name                          = local.origin_name
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.origin_group.id
  enabled                       = true

  host_name          = var.backend_host_name
  http_port          = 80
  https_port         = 443
  origin_host_header = coalesce(var.origin_host_header, var.backend_host_name)
  priority           = 1
  weight             = 1000

  certificate_name_check_enabled = true

  private_link {
    request_message        = var.pls_request_message
    location               = var.private_link_location
    private_link_target_id = var.private_link_service_id
  }
}

# ──────────────────────────────────────────────────────────────────────────────
# Custom Domain — AFD-managed cert, TLS 1.2, Azure DNS zone association
# ──────────────────────────────────────────────────────────────────────────────
resource "azurerm_cdn_frontdoor_custom_domain" "domain" {
  # Resource name derived from hostname with dots replaced (AFD naming requirement)
  name                     = replace(var.custom_domain_hostname, ".", "-")
  cdn_frontdoor_profile_id = data.azurerm_cdn_frontdoor_profile.profile.id
  dns_zone_id              = data.azurerm_dns_zone.zone.id
  host_name                = var.custom_domain_hostname

  tls {
    certificate_type = "ManagedCertificate"
  }
}

# ──────────────────────────────────────────────────────────────────────────────
# DNS — domain validation TXT record (_dnsauth.<subdomain> or _dnsauth for apex)
# Token is automatically available from the custom domain resource output.
# ──────────────────────────────────────────────────────────────────────────────
resource "azurerm_dns_txt_record" "domain_validation" {
  name                = var.dns_subdomain != "" ? "_dnsauth.${var.dns_subdomain}" : "_dnsauth"
  zone_name           = data.azurerm_dns_zone.zone.name
  resource_group_name = var.dns_zone_resource_group_name
  ttl                 = 3600

  record {
    value = azurerm_cdn_frontdoor_custom_domain.domain.validation_token
  }
}

# ──────────────────────────────────────────────────────────────────────────────
# DNS — CNAME record routing traffic to the AFD endpoint
# Skipped for apex/root domains (dns_subdomain = ""). For apex, create an
# alias A record manually or via a separate azurerm_dns_a_record with target_resource_id.
# ──────────────────────────────────────────────────────────────────────────────
resource "azurerm_dns_cname_record" "domain_cname" {
  count               = var.dns_subdomain != "" ? 1 : 0
  name                = var.dns_subdomain
  zone_name           = data.azurerm_dns_zone.zone.name
  resource_group_name = var.dns_zone_resource_group_name
  ttl                 = 3600
  record              = data.azurerm_cdn_frontdoor_endpoint.endpoint.host_name
}

# ──────────────────────────────────────────────────────────────────────────────
# Route  (rt-<app_name>)
# HTTPS-only by default; set supported_protocols = ["Http","Https"] for sites
# that also need to receive HTTP (e.g. when a redirect rule set is attached).
# ──────────────────────────────────────────────────────────────────────────────
resource "azurerm_cdn_frontdoor_route" "route" {
  name                          = local.route_name
  cdn_frontdoor_endpoint_id     = data.azurerm_cdn_frontdoor_endpoint.endpoint.id
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.origin_group.id
  cdn_frontdoor_origin_ids      = [azurerm_cdn_frontdoor_origin.origin.id]

  cdn_frontdoor_custom_domain_ids = [azurerm_cdn_frontdoor_custom_domain.domain.id]
  cdn_frontdoor_rule_set_ids      = var.wordpress_cache_bypass ? [azurerm_cdn_frontdoor_rule_set.wordpress_bypass[0].id] : []

  supported_protocols    = var.supported_protocols
  patterns_to_match      = var.route_patterns_to_match
  forwarding_protocol    = "MatchRequest"
  link_to_default_domain = false
  https_redirect_enabled = true
  enabled                = true

  dynamic "cache" {
    for_each = var.cache_enabled ? [1] : []
    content {
      query_string_caching_behavior = var.cache_query_string_caching_behavior
      query_strings                 = var.cache_query_strings
      compression_enabled           = var.cache_compression_enabled
      content_types_to_compress     = var.cache_compression_enabled ? local.effective_content_types_to_compress : []
    }
  }

  depends_on = [
    azurerm_cdn_frontdoor_custom_domain.domain,
    azurerm_dns_txt_record.domain_validation,
    azurerm_cdn_frontdoor_rule_set.wordpress_bypass,
    azurerm_cdn_frontdoor_rule.wordpress_admin_bypass,
    azurerm_cdn_frontdoor_rule.wordpress_loggedin_bypass,
  ]
}

# ──────────────────────────────────────────────────────────────────────────────
# WordPress Cache Bypass Rule Set (opt-in via wordpress_cache_bypass)
# Bypasses AFD cache for wp-admin, wp-login, and logged-in users so that
# admin pages always hit the origin fresh — no stale nonces or broken AJAX.
# ──────────────────────────────────────────────────────────────────────────────
resource "azurerm_cdn_frontdoor_rule_set" "wordpress_bypass" {
  count                    = var.wordpress_cache_bypass ? 1 : 0
  name                     = "wpbypass${replace(lower(var.app_name), "-", "")}"
  cdn_frontdoor_profile_id = data.azurerm_cdn_frontdoor_profile.profile.id
}

# Rule 1 — bypass cache for wp-admin/* and wp-login.php
resource "azurerm_cdn_frontdoor_rule" "wordpress_admin_bypass" {
  count                     = var.wordpress_cache_bypass ? 1 : 0
  name                      = "WPAdminBypass"
  cdn_frontdoor_rule_set_id = azurerm_cdn_frontdoor_rule_set.wordpress_bypass[0].id
  order                     = 1
  behavior_on_match         = "Continue"

  conditions {
    url_path_condition {
      operator         = "BeginsWith"
      negate_condition = false
      match_values     = ["/wp-admin", "/wp-login.php"]
      transforms       = ["Lowercase"]
    }
  }

  actions {
    route_configuration_override_action {
      cache_behavior = "Disabled"
    }
  }
}

# Rule 2 — bypass cache for logged-in WordPress users (cookie-based)
resource "azurerm_cdn_frontdoor_rule" "wordpress_loggedin_bypass" {
  count                     = var.wordpress_cache_bypass ? 1 : 0
  name                      = "WPLoggedInBypass"
  cdn_frontdoor_rule_set_id = azurerm_cdn_frontdoor_rule_set.wordpress_bypass[0].id
  order                     = 2
  behavior_on_match         = "Continue"

  conditions {
    request_header_condition {
      header_name      = "Cookie"
      operator         = "Contains"
      negate_condition = false
      match_values     = ["wordpress_logged_in", "wordpress_sec_"]
    }
  }

  actions {
    route_configuration_override_action {
      cache_behavior = "Disabled"
    }
  }

  depends_on = [azurerm_cdn_frontdoor_rule.wordpress_admin_bypass]
}

# ──────────────────────────────────────────────────────────────────────────────
# WAF Policy  (waf<appnamenodashes>) — Premium SKU, bot protection enabled
# ──────────────────────────────────────────────────────────────────────────────
resource "azurerm_cdn_frontdoor_firewall_policy" "waf" {
  name                = local.waf_policy_name
  resource_group_name = var.frontdoor_resource_group_name
  sku_name            = "Premium_AzureFrontDoor"
  enabled             = true
  mode                = var.waf_mode

  managed_rule {
    type    = "Microsoft_BotManagerRuleSet"
    version = "1.0"
    action  = "Block"
  }

  tags = var.tags

  lifecycle {
    ignore_changes = [tags]
  }
}

# ──────────────────────────────────────────────────────────────────────────────
# Security Policy  (waf-<app_name>) — binds WAF policy to the custom domain
# ──────────────────────────────────────────────────────────────────────────────
resource "azurerm_cdn_frontdoor_security_policy" "security_policy" {
  name                     = local.security_policy_name
  cdn_frontdoor_profile_id = data.azurerm_cdn_frontdoor_profile.profile.id

  security_policies {
    firewall {
      cdn_frontdoor_firewall_policy_id = azurerm_cdn_frontdoor_firewall_policy.waf.id

      association {
        patterns_to_match = ["/*"]

        domain {
          cdn_frontdoor_domain_id = azurerm_cdn_frontdoor_custom_domain.domain.id
        }
      }
    }
  }
}
