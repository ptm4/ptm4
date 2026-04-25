variable "resource_group_name" {
  type    = string
  default = "rg-JLB-Test-IT-WordPress"
}

variable "location" {
  type    = string
  default = "eastus2"
 # default = "centralus"
}

variable "container_app_environment_name" {
  type    = string
  default = "cae-test-it-jammylab"
}

variable "container_app_name" {
  type    = string
  default = "aca-jammylab-test"
}

variable "container_image" {
  type    = string
  default = "docker.io/wordpress:php8.2-apache"
}

variable "container_cpu" {
  type    = number
  default = 1
}

variable "container_memory" {
  type    = string
  default = "2Gi"
}

variable "min_replicas" {
  type    = number
  default = 1
}

variable "max_replicas" {
  type    = number
  default = 1
}

variable "revision_mode" {
  type    = string
  default = "Single"
}

variable "workload_profile_name" {
  type    = string
  default = "Consumption"
}

variable "vnet_name" {
  type    = string
  default = "vnet-JLB-Test-IT-Network-Spoke"
  #default = "vnet-JLB-Test-IT-Network-Spoke-Central"
}

variable "vnet_subnet_name" {
  type    = string
  default = "snet-JLB-Test-IT-serverFarms"
  #default = "snet-JLB-Test-IT-Network-Spoke-Central"
}

variable "vnet_resource_group_name" {
  type    = string
 default = "rg-JLB-Test-IT-Network-Spoke"
 #default = "rg-JLB-Test-IT-WordPress-Central"
}

variable "vnet_sql_name" {
  type    = string
 default = "vnet-JLB-Test-IT-Network-Spoke"
 #default = "vnet-JLB-Test-IT-Network-Spoke-Central"
}

variable "vnet_sql_subnet_name" {
  type    = string
  default = "snet-JLB-Test-IT-mysql"
  #default = "snet-JLB-Test-IT-Network-Spoke-mysqlflexible"
}

variable "vnet_sql_resource_group_name" {
  type    = string
  default = "rg-JLB-Test-IT-Network-Spoke"
  #default = "rg-JLB-Test-IT-WordPress-Central"
}

variable "log_analytics_workspace_name" {
  type    = string
  default = "law-shc-test-it-wordpress"
}

variable "log_analytics_workspace_resource_group" {
  type    = string
  default = "rg-JLB-Test-IT-WordPress"
}
variable "mysql_admin_password" {
  sensitive = true
  default = "Bu88le-Wr4p24"
}
