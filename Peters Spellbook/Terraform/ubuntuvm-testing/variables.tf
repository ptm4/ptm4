variable "subscription_id" {
  description = "Azure Subscription ID"
  type        = string
}

variable "tenant_id" {
  description = "Azure Tenant ID"
  type        = string
}

variable "resource_group_name" {
  description = "Resource group where the VM will be deployed"
  type        = string
}

variable "location" {
  description = "Azure region to deploy into"
  type        = string
  default     = "eastus2"
}

variable "vm_name" {
  description = "Name of the VM"
  type        = string
}

variable "admin_username" {
  description = "Admin username for the VM"
  type        = string
  default     = "shcvmadmin"
}

variable "admin_password" {
  description = "Admin password for the VM"
  type        = string
  sensitive   = true
  default     = "YymtGVhgh8sso!"
}

variable "subnet_id" {
  description = "Subnet ID for the VM NIC"
  type        = string
}
