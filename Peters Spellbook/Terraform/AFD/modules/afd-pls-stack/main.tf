# ──────────────────────────────────────────────────────────────────────────────
# Data Sources — existing ILB, network resources, and current subscription
# ──────────────────────────────────────────────────────────────────────────────
data "azurerm_subscription" "current" {}

data "azurerm_lb" "ilb" {
  name                = var.ilb_name
  resource_group_name = var.ilb_resource_group_name
}

data "azurerm_subnet" "internal" {
  name                 = var.internal_subnet_name
  virtual_network_name = var.vnet_name
  resource_group_name  = var.vnet_resource_group_name
}

data "azurerm_lb_backend_address_pool" "backend_pool" {
  name            = var.backend_pool_name
  loadbalancer_id = data.azurerm_lb.ilb.id
}

# ──────────────────────────────────────────────────────────────────────────────
# Naming locals
# Frontend IP name and resource ID are fully derived from app_name + known
# constants. No caller input required beyond app_name.
# ──────────────────────────────────────────────────────────────────────────────
locals {
  frontend_ip_name = "AFD-${var.app_name}"
  frontend_ip_id   = "/subscriptions/${data.azurerm_subscription.current.subscription_id}/resourceGroups/${var.ilb_resource_group_name}/providers/Microsoft.Network/loadBalancers/${var.ilb_name}/frontendIPConfigurations/AFD-${var.app_name}"
}

# ──────────────────────────────────────────────────────────────────────────────
# ILB Load Balancing Rule  (lbr-<app_name>)
#
# HA Ports (protocol=All, port=0) — floating IP on, TCP reset off,
# session persistence none. Uses the existing lbprobe health probe (TCP:8008).
#
# PREREQUISITE: Before terraform apply, create frontend IP "AFD-<app_name>" on
# FGHA-NorthSouth-internalloadbalancer with a static private IP from
# snet-afd-prod. Record the allocated IP in the intake Excel sheet
# (ilb_private_ip column) for tracking — it is not a Terraform input.
# ──────────────────────────────────────────────────────────────────────────────
resource "azurerm_lb_rule" "ha_ports" {
  name            = "lbr-${var.app_name}"
  loadbalancer_id = data.azurerm_lb.ilb.id

  frontend_ip_configuration_name = local.frontend_ip_name
  backend_address_pool_ids       = [data.azurerm_lb_backend_address_pool.backend_pool.id]

  # Probe ID constructed from the known LB resource ID + probe name
  probe_id = "${data.azurerm_lb.ilb.id}/probes/${var.health_probe_name}"

  protocol        = "All" # HA Ports
  frontend_port   = 0     # HA Ports
  backend_port    = 0     # HA Ports

  floating_ip_enabled     = true
  disable_outbound_snat   = false
  idle_timeout_in_minutes = 4
  tcp_reset_enabled       = false
  load_distribution       = "Default" # Session persistence = None
}

# ──────────────────────────────────────────────────────────────────────────────
# Private Link Service  (pls-<app_name>)
#
# Fronts the ILB frontend IP "AFD-<app_name>" created as a prerequisite.
# Source NAT uses snet-afd-prod with dynamic IP allocation.
# ──────────────────────────────────────────────────────────────────────────────
resource "azurerm_private_link_service" "pls" {
  name                = "pls-${var.app_name}"
  location            = var.location
  resource_group_name = var.pls_resource_group_name

  auto_approval_subscription_ids = []
  visibility_subscription_ids    = []
  proxy_protocol_enabled          = false

  load_balancer_frontend_ip_configuration_ids = [local.frontend_ip_id]

  nat_ip_configuration {
    name                       = "${var.internal_subnet_name}-1"
    primary                    = true
    private_ip_address_version = "IPv4"
    subnet_id                  = data.azurerm_subnet.internal.id
  }

  tags = var.tags

  lifecycle {
    ignore_changes = [tags]
  }
}
