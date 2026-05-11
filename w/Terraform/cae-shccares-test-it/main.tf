# main.tf

#data
data "azurerm_resource_group" "rg" {
  name = var.resource_group_name
}

data "azurerm_log_analytics_workspace" "law" {
  name                = var.log_analytics_workspace_name
  resource_group_name = var.log_analytics_workspace_resource_group
}

data "azurerm_subnet" "vnet_subnet" {
  name                 = var.vnet_subnet_name
  virtual_network_name = var.vnet_name
  resource_group_name  = var.vnet_resource_group_name
}

data "azurerm_private_dns_zone" "mysql_dns" {
  provider           = azurerm.dns_sub
  name                = "privatelink.mysql.database.azure.com"
  resource_group_name = "rg-JLB-Hub-Private_Azure_DNS_Zones"
}

data "azurerm_subnet" "vnet_sql_subnet" {
  name                 = var.vnet_sql_subnet_name
  virtual_network_name = var.vnet_sql_name
  resource_group_name  = var.vnet_sql_resource_group_name
}

#sql
resource "azurerm_private_endpoint" "mysql_pe" {
  name                = "pep-mysql-wp-test-it"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.rg.name
  subnet_id           = data.azurerm_subnet.vnet_sql_subnet.id

  private_service_connection {
    name                           = "psc-mysql-wp-test-it"
    private_connection_resource_id = azurerm_mysql_flexible_server.wordpress.id
    subresource_names              = ["mysqlServer"]
    is_manual_connection           = false
  }
}


resource "azurerm_mysql_flexible_server" "wordpress" {
  name                   = "mysql-wp-test-it"
  resource_group_name    = data.azurerm_resource_group.rg.name
  location               = var.location
  administrator_login    = "wpadmin"
  administrator_password = var.mysql_admin_password

  #sku_name   = "B_Standard_B1ms"
  sku_name = "GP_Standard_D2ds_v4"
  version    = "8.0.21"

  
  #delegated_subnet_id = data.azurerm_subnet.vnet_sql_subnet.id

  private_dns_zone_id = data.azurerm_private_dns_zone.mysql_dns.id

  backup_retention_days = 7
}

#sqldb
resource "azurerm_mysql_flexible_database" "wordpress_db" {
  name                = "db-wp-jammylab"
  resource_group_name = data.azurerm_resource_group.rg.name
  server_name         = azurerm_mysql_flexible_server.wordpress.name
  charset             = "utf8"
  collation           = "utf8_general_ci"
}



#cae
resource "azurerm_container_app_environment" "cae" {
  name                = var.container_app_environment_name
  location            = var.location
  resource_group_name = data.azurerm_resource_group.rg.name

  log_analytics_workspace_id = data.azurerm_log_analytics_workspace.law.id

  infrastructure_subnet_id = data.azurerm_subnet.vnet_subnet.id

  internal_load_balancer_enabled = true

}

#cae pe
resource "azurerm_private_endpoint" "cae_pe" {
  name                = "pep-test-it-jammylab"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.rg.name
  subnet_id           = data.azurerm_subnet.vnet_subnet.id

  private_service_connection {
    name                           = "psc-test-it-jammylab"
    private_connection_resource_id = azurerm_container_app_environment.cae.id
    is_manual_connection           = false
    subresource_names              = ["environment"]
  }

}

#aca
resource "azurerm_container_app" "wordpress" {
  name                         = var.container_app_name
  resource_group_name          = data.azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.cae.id
  revision_mode                = var.revision_mode

  template {
    min_replicas = 1
    max_replicas = 10
    container {
      name   = var.container_app_name
      image  = var.container_image
      cpu    = var.container_cpu
      memory = var.container_memory

      env {
        name  = "WORDPRESS_DB_HOST"
        value = azurerm_mysql_flexible_server.wordpress.fqdn
      }

      env {
        name  = "WORDPRESS_DB_USER"
        value = "wpadmin"
      }

      env {
        name  = "WORDPRESS_DB_PASSWORD"
        value = var.mysql_admin_password
      }

      env {
        name  = "WORDPRESS_DB_NAME"
        value = "db-wp-jammylab"
      }
    }
  }

}