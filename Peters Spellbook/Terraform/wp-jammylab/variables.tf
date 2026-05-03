# variables.tf
# RESOURCE GROUP

variable "resource_group_name" {
  type    = string
  default = "rg-JLB-Test-IT-WP-jammylab"
}

variable "location" {
  type    = string
  default = "eastus2"
}

# TAGS

variable "tags" {
  type = map(string)
  default = {
    "App Owner"  = "Noble Numbat"
    Application  = "WordPress"
    Environment  = "Test"
    Purpose      = "Shccares com Testing"
  }
}

# LOG ANALYTICS WORKSPACE

variable "log_analytics_workspace_name" {
  type    = string
  default = "law-wp-jammylab"
}

# STORAGE

variable "storage_account_name" {
  type    = string
  default = "stgwpjammylab"
}

variable "storage_share_name" {
  type    = string
  default = "stgwpjammylab"
}

# File shares used after custom-image cutover (mount uploads and cache only).

variable "storage_share_uploads_name" {
  type        = string
  description = "Azure Files share name for wp-content/uploads."
  default     = "wp-uploads"
}

variable "storage_share_cache_name" {
  type        = string
  description = "Azure Files share name for wp-content/cache."
  default     = "wp-cache"
}

variable "storage_share_split_quota_gb" {
  type        = number
  description = "Quota in GiB for each uploads/cache share."
  default     = 100
}

variable "acr_name" {
  type        = string
  description = "ACR name (globally unique, alphanumeric, 5–50 characters)."
  default     = "acrwpjammylabeus2"
}

variable "acr_sku" {
  type        = string
  description = "ACR SKU (Basic is typical for a single application)."
  default     = "Basic"
}

# NETWORKING 

variable "vnet_name" {
  type    = string
  default = "vnet-JLB-Test-IT-Network-Spoke"
}

variable "vnet_subnet_name" {
  type    = string
  default = "snet-JLB-Test-IT-serverFarms"
}

variable "vnet_resource_group_name" {
  type    = string
  default = "rg-JLB-Test-IT-Network-Spoke"
}

variable "vnet_sql_name" {
  type    = string
  default = "vnet-JLB-Test-IT-Network-Spoke"
}

variable "vnet_sql_subnet_name" {
  type    = string
  default = "snet-JLB-Test-IT-mysql"
}

variable "vnet_default_subnet_name" {
  type    = string
  default = "snet-JLB-Test-IT-Default"
}

variable "vnet_sql_resource_group_name" {
  type    = string
  default = "rg-JLB-Test-IT-Network-Spoke"
}

# MYSQL

variable "mysql_admin_password" {
  type      = string
  sensitive = true
}

# CONTAINER APP ENVIRONMENT

variable "container_app_environment_name" {
  type    = string
  default = "cae-wp-jammylab"
}

# CONTAINER APP

variable "container_app_name" {
  type    = string
  default = "aca-wp-jammylab"
}

variable "container_image" {
  type    = string
  default = "acrwpjammylabeus2.azurecr.io/wp-jammylab:latest"
}

variable "container_cpu" {
  type    = number
  default = 4
}

variable "container_memory" {
  type    = string
  default = "8Gi"
}

variable "min_replicas" {
  type    = number
  default = 1
}

variable "max_replicas" {
  type    = number
  default = 10
}

variable "http_scale_concurrent_requests" {
  type    = number
  default = 25
}

variable "cpu_scale_threshold" {
  type    = number
  default = 70
}

variable "revision_mode" {
  type    = string
  default = "Single"
}

# WORDPRESS

variable "wordpress_table_prefix" {
  type    = string
  default = "wp_"
  # Set to "wf1_" only if restoring from the Kinsta database export.
}

variable "wordpress_debug" {
  type    = string
  default = "0"
}

# RESOURCE NAMES

variable "mysql_server_name" {
  type    = string
  default = "mysql-wp-jammylab"
}

variable "mysql_pe_name" {
  type    = string
  default = "pep-wp-jammylab"
}

variable "cae_pe_name" {
  type    = string
  default = "pep-cae-wp-jammylab"
}
