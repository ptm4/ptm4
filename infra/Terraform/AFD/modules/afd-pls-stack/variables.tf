# ──────────────────────────────────────────────
# Naming
# ──────────────────────────────────────────────
variable "app_name" {
  type        = string
  description = "Short application/service name. Drives naming: lbr-<name>, pls-<name>, frontend IP AFD-<name>."
}

# ──────────────────────────────────────────────
# Location
# ──────────────────────────────────────────────
variable "location" {
  type        = string
  description = "Azure region for the Private Link Service."
  default     = "eastus2"
}

# ──────────────────────────────────────────────
# Existing ILB (NorthSouth)
# ──────────────────────────────────────────────
variable "ilb_resource_group_name" {
  type        = string
  description = "Resource group containing the existing NorthSouth ILB."
  default     = "rg-network-prod"
}

variable "ilb_name" {
  type        = string
  description = "Name of the existing NorthSouth Internal Load Balancer."
  default     = "FGHA-NorthSouth-internalloadbalancer"
}

# ──────────────────────────────────────────────────────────────────────────────
# ILB Frontend IP — naming and resource ID are auto-derived from app_name.
#
# The frontend IP "AFD-<app_name>" must be pre-created on the ILB before apply:
#   1. In the Azure Portal or CLI, add a new frontend IP configuration to
#      FGHA-NorthSouth-internalloadbalancer (rg-network-prod).
#   2. Name:    AFD-<app_name>   (e.g. AFD-weconnect-qa)
#   3. Type:    Private / Static
#   4. VNet:    vnet-hub-prod-eus2
#   5. Subnet:  snet-afd-prod
#   6. IP:      allocate from network tracker — record in the intake Excel
#               sheet (ilb_private_ip column) for reference. This IP is not
#               a Terraform variable; it is documentation only.
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────
# Existing ILB components (referenced by the LBR)
# ──────────────────────────────────────────────
variable "backend_pool_name" {
  type        = string
  description = "Name of the existing ILB backend address pool."
  default     = "FGHA-NorthSouth-ILB-snet-internal-prod-backend"
}

variable "health_probe_name" {
  type        = string
  description = "Name of the existing ILB health probe (TCP:8008)."
  default     = "lbprobe"
}

# ──────────────────────────────────────────────
# VNet / Subnet (for PLS NAT config)
# ──────────────────────────────────────────────
variable "vnet_resource_group_name" {
  type        = string
  description = "Resource group containing the hub VNet."
  default     = "rg-network-prod"
}

variable "vnet_name" {
  type        = string
  description = "Name of the hub VNet."
  default     = "vnet-hub-prod-eus2"
}

variable "internal_subnet_name" {
  type        = string
  description = "Name of the subnet used for the PLS NAT IP configuration."
  default     = "snet-afd-prod"
}

# ──────────────────────────────────────────────
# Private Link Service
# ──────────────────────────────────────────────
variable "pls_resource_group_name" {
  type        = string
  description = "Resource group where the Private Link Service will be created."
  default     = "rg-JLB-Hub-FrontDoor"
}

# ──────────────────────────────────────────────
# Tags
# ──────────────────────────────────────────────
variable "tags" {
  type        = map(string)
  description = "Tags applied to all resources created by this module."
  default     = {}
}
