# main.tf
# RESOURCE GROUP

resource "azurerm_resource_group" "rg" {
  name     = var.resource_group_name
  location = var.location
  tags     = var.tags
  lifecycle {
    ignore_changes = [
      tags["CreationDate"]
    ]
  }
}

# DATA SOURCES 

data "azurerm_client_config" "current" {}

data "azurerm_subnet" "vnet_subnet" {
  name                 = var.vnet_subnet_name
  virtual_network_name = var.vnet_name
  resource_group_name  = var.vnet_resource_group_name
}

data "azurerm_subnet" "vnet_sql_subnet" {
  name                 = var.vnet_sql_subnet_name
  virtual_network_name = var.vnet_sql_name
  resource_group_name  = var.vnet_sql_resource_group_name
}

data "azurerm_private_dns_zone" "storage_dns" {
  provider            = azurerm.dns_sub
  name                = "privatelink.file.core.windows.net"
  resource_group_name = "rg-JLB-Hub-Private_Azure_DNS_Zones"
}

data "azurerm_private_dns_zone" "mysql_dns" {
  provider            = azurerm.dns_sub
  name                = "privatelink.mysql.database.azure.com"
  resource_group_name = "rg-JLB-Hub-Private_Azure_DNS_Zones"
}

data "azurerm_private_dns_zone" "kv_dns" {
  provider            = azurerm.dns_sub
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = "rg-JLB-Hub-Private_Azure_DNS_Zones"
}

data "azurerm_private_dns_zone" "cae_dns" {
  provider            = azurerm.dns_sub
  name                = "privatelink.eastus2.azurecontainerapps.io"
  resource_group_name = "rg-JLB-Hub-Private_Azure_DNS_Zones"
}

data "azurerm_subnet" "vnet_default_subnet" {
  name                 = var.vnet_default_subnet_name
  virtual_network_name = var.vnet_name
  resource_group_name  = var.vnet_resource_group_name
}

# LOG ANALYTICS WORKSPACE

resource "azurerm_log_analytics_workspace" "law" {
  name                = var.log_analytics_workspace_name
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30

  allow_resource_only_permissions         = true
  cmk_for_query_forced                    = false
  daily_quota_gb                          = -1
  immediate_data_purge_on_30_days_enabled = false
  internet_ingestion_enabled              = true
  internet_query_enabled                  = true

  tags = var.tags
    lifecycle {
    ignore_changes = [
      tags["CreationDate"]
    ]
  }
}

# KEY VAULT

resource "azurerm_key_vault" "wp" {
  name                = "kv-wp-jammylab"
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"
  public_network_access_enabled = false
  rbac_authorization_enabled = true

  tags = var.tags
  lifecycle {
    ignore_changes = [
      tags["CreationDate"]
    ]
  }
}

resource "azurerm_private_endpoint" "kv_pe" {
  name                = "pep-kv-wp-jammylab"
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  subnet_id           = data.azurerm_subnet.vnet_default_subnet.id

  private_service_connection {
    name                           = "pep-kv-wp-jammylab"
    private_connection_resource_id = azurerm_key_vault.wp.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "kv-dns-group"
    private_dns_zone_ids = [data.azurerm_private_dns_zone.kv_dns.id]
  }

  tags = var.tags
  lifecycle {
    ignore_changes = [
      tags["CreationDate"]
    ]
  }
}

# STORAGE ACCOUNT FILE SHARE 

resource "azurerm_storage_account" "wordpress" {
  name                     = var.storage_account_name
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = var.location
  account_tier             = "Premium"
  account_replication_type = "LRS"
  account_kind             = "FileStorage"

  https_traffic_only_enabled       = true
  min_tls_version                  = "TLS1_2"
  allow_nested_items_to_be_public  = false
  cross_tenant_replication_enabled = false
  shared_access_key_enabled        = true
  local_user_enabled               = true
  public_network_access_enabled    = false


  share_properties {
    retention_policy {
      days = 14
    }
    smb {
      multichannel_enabled = true
    }
  }

  tags = var.tags
  lifecycle {
    ignore_changes = [
      tags["CreationDate"]
    ]
  }
}

resource "azurerm_storage_share" "wordpress" {
  name                 = var.storage_share_name
  storage_account_id   = azurerm_storage_account.wordpress.id
  quota                = 100
  enabled_protocol     = "SMB"
}

# ACR and uploads/cache file shares for the custom-image cutover (ACA unchanged until that apply).

resource "azurerm_container_registry" "wp" {
  name                = var.acr_name
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.location
  sku                 = var.acr_sku
  admin_enabled       = false

  tags = var.tags

  lifecycle {
    ignore_changes = [
      tags["CreationDate"]
    ]
  }
}

resource "azurerm_storage_share" "wordpress_uploads" {
  name               = var.storage_share_uploads_name
  storage_account_id = azurerm_storage_account.wordpress.id
  quota              = var.storage_share_split_quota_gb
  enabled_protocol   = "SMB"
}

resource "azurerm_storage_share" "wordpress_cache" {
  name               = var.storage_share_cache_name
  storage_account_id = azurerm_storage_account.wordpress.id
  quota              = var.storage_share_split_quota_gb
  enabled_protocol   = "SMB"
}

resource "azurerm_private_endpoint" "storage_pe" {
  name                = "pep-stg-wp-jammylab"
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  subnet_id           = data.azurerm_subnet.vnet_default_subnet.id

  private_service_connection {
    name                           = "pep-stg-wp-jammylab"
    private_connection_resource_id = azurerm_storage_account.wordpress.id
    subresource_names              = ["file"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "storage-dns-group"
    private_dns_zone_ids = [data.azurerm_private_dns_zone.storage_dns.id]
  }

  tags = var.tags
  lifecycle {
    ignore_changes = [
      tags["CreationDate"]
    ]
  }
}

# MYSQL FLEXIBLE SERVER

resource "azurerm_mysql_flexible_server" "wordpress" {
  name                   = var.mysql_server_name
  resource_group_name    = azurerm_resource_group.rg.name
  location               = var.location
  administrator_login    = "wpadmin"
  administrator_password = var.mysql_admin_password

  sku_name = "GP_Standard_D2ds_v4"
  version  = "8.0.21"

  private_dns_zone_id   = data.azurerm_private_dns_zone.mysql_dns.id
  backup_retention_days = 7
  #public_network_access_enabled = false 

  tags = var.tags

  lifecycle {
    ignore_changes = [
      private_dns_zone_id,
      zone,
      tags["CreationDate"]
    ]
  }
}

resource "azurerm_mysql_flexible_server_configuration" "ssl" {
  name                = "require_secure_transport"
  resource_group_name = azurerm_resource_group.rg.name
  server_name         = azurerm_mysql_flexible_server.wordpress.name
  value               = "ON"
}


resource "azurerm_mysql_flexible_database" "wordpress_db" {
  name                = "db-wp-jammylab"
  resource_group_name = azurerm_resource_group.rg.name
  server_name         = azurerm_mysql_flexible_server.wordpress.name
  charset             = "utf8mb4"
  collation           = "utf8mb4_0900_ai_ci"
}

resource "azurerm_private_endpoint" "mysql_pe" {
  name                = var.mysql_pe_name
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  subnet_id           = data.azurerm_subnet.vnet_default_subnet.id

  private_service_connection {
    name                           = var.mysql_pe_name
    private_connection_resource_id = azurerm_mysql_flexible_server.wordpress.id
    subresource_names              = ["mysqlServer"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "mysql-dns-group"
    private_dns_zone_ids = [data.azurerm_private_dns_zone.mysql_dns.id]
  }  
  
  tags = var.tags
  lifecycle {
    ignore_changes = [
      tags["CreationDate"]
    ]
  }
}

# CONTAINER APP ENVIRONMENT

resource "azurerm_container_app_environment" "cae" {
  name                = var.container_app_environment_name
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name

  log_analytics_workspace_id     = azurerm_log_analytics_workspace.law.id
  infrastructure_subnet_id       = data.azurerm_subnet.vnet_subnet.id
  internal_load_balancer_enabled = true

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags

  lifecycle {
    ignore_changes = [
      infrastructure_resource_group_name,
      workload_profile,
      tags["CreationDate"]
    ]
  }
}

resource "azurerm_container_app_environment_storage" "wordpress" {
  name                         = var.storage_share_name
  container_app_environment_id = azurerm_container_app_environment.cae.id
  account_name                 = azurerm_storage_account.wordpress.name
  share_name                   = azurerm_storage_share.wordpress.name
  access_key                   = azurerm_storage_account.wordpress.primary_access_key
  access_mode                  = "ReadWrite"
}

resource "azurerm_container_app_environment_storage" "wordpress_uploads" {
  name                         = var.storage_share_uploads_name
  container_app_environment_id = azurerm_container_app_environment.cae.id
  account_name                 = azurerm_storage_account.wordpress.name
  share_name                   = azurerm_storage_share.wordpress_uploads.name
  access_key                   = azurerm_storage_account.wordpress.primary_access_key
  access_mode                  = "ReadWrite"
}

resource "azurerm_container_app_environment_storage" "wordpress_cache" {
  name                         = var.storage_share_cache_name
  container_app_environment_id = azurerm_container_app_environment.cae.id
  account_name                 = azurerm_storage_account.wordpress.name
  share_name                   = azurerm_storage_share.wordpress_cache.name
  access_key                   = azurerm_storage_account.wordpress.primary_access_key
  access_mode                  = "ReadWrite"
}

resource "azurerm_role_assignment" "cae_kv_access" {
  scope                = azurerm_key_vault.wp.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_container_app_environment.cae.identity[0].principal_id

  depends_on = [azurerm_container_app_environment.cae]
}

resource "azurerm_role_assignment" "cae_kv_access_cert" {
  scope                = azurerm_key_vault.wp.id
  role_definition_name = "Key Vault Certificate User"
  principal_id         = azurerm_container_app_environment.cae.identity[0].principal_id

  depends_on = [azurerm_container_app_environment.cae]
}

resource "azurerm_private_endpoint" "cae_pe" {
  name                = var.cae_pe_name
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  subnet_id           = data.azurerm_subnet.vnet_default_subnet.id

  private_service_connection {
    name                           = var.cae_pe_name
    private_connection_resource_id = azurerm_container_app_environment.cae.id
    is_manual_connection           = false
    subresource_names              = ["managedEnvironments"]
  }

  private_dns_zone_group {
    name                 = "cae-dns-group"
    private_dns_zone_ids = [data.azurerm_private_dns_zone.cae_dns.id]
  }

  tags = var.tags
  lifecycle {
    ignore_changes = [
      tags["CreationDate"]
    ]
  }
}

# CONTAINER APP 

resource "azurerm_container_app" "wordpress" {
  name                         = var.container_app_name
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.cae.id
  revision_mode                = var.revision_mode

  workload_profile_name = "Consumption"

  identity {
    type = "SystemAssigned"
  }

  registry {
    server   = azurerm_container_registry.wp.login_server
    identity = "System"
  }

  ingress {
    allow_insecure_connections = false
    client_certificate_mode    = "ignore"
    external_enabled           = true
    target_port                = 80
    transport                  = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    # HTTP scale-out: additional replica when concurrent requests per instance exceed threshold.
    http_scale_rule {
      name                = "http-scaler"
      concurrent_requests = var.http_scale_concurrent_requests
    }

    # CPU scale-out: additional replica when average CPU utilization exceeds threshold.
    custom_scale_rule {
      name             = "cpu-scaler"
      custom_rule_type = "cpu"
      metadata = {
        type  = "Utilization"
        value = tostring(var.cpu_scale_threshold)
      }
    }

    container {
      # Do not set command: it overrides the image entrypoint and the container will exit.
      name   = var.container_app_name
      image  = var.container_image
      cpu    = var.container_cpu
      memory = var.container_memory

      # Database connection
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

      # MySQL SSL: require_secure_transport=ON; MYSQL_CLIENT_FLAGS must also be set in WORDPRESS_CONFIG_EXTRA.
      env {
        name  = "WORDPRESS_DB_SSL_CA"
        value = "/etc/ssl/certs/DigiCert_Global_Root_G2.pem"
      }

      # WORDPRESS_CONFIG_EXTRA: MySQL SSL, HTTPS, PHP limits, FS/umask for Azure Files.
      # Auth keys are generated once by entrypoint.sh on first start and persisted to the
      # uploads share — no manual key management needed across revisions or environments.

      env {
        name  = "WORDPRESS_CONFIG_EXTRA"
        value = "define('MYSQL_SSL_CA', '/etc/ssl/certs/DigiCert_Global_Root_G2.pem'); define('MYSQL_CLIENT_FLAGS', MYSQLI_CLIENT_SSL); define('FORCE_SSL_ADMIN', true); $_SERVER['HTTPS'] = 'on'; @ini_set('memory_limit', '6144M'); @ini_set('max_execution_time', '300'); @ini_set('max_input_time', '300'); define('FS_METHOD', 'direct'); define('FS_CHMOD_DIR', 0777); define('FS_CHMOD_FILE', 0666); umask(0000);"
      }
      env {
        name  = "WORDPRESS_TABLE_PREFIX"
        value = var.wordpress_table_prefix
      }
      env {
        name  = "WORDPRESS_DEBUG"
        value = var.wordpress_debug
      }

      # PHP_INI_SCAN_DIR removed — OPcache config is now baked into the image via docker/opcache.ini.

      liveness_probe {
        transport        = "TCP"
        port             = 80
        initial_delay    = 0
        interval_seconds = 10
        timeout          = 5
        failure_count_threshold = 30
      }
      readiness_probe {
        transport               = "TCP"
        port                    = 80
        initial_delay           = 0
        interval_seconds        = 5
        timeout                 = 5
        success_count_threshold = 1
        failure_count_threshold = 30
      }
      startup_probe {
        transport               = "TCP"
        port                    = 80
        initial_delay           = 1
        interval_seconds        = 10
        timeout                 = 3
        failure_count_threshold = 30
      }

      volume_mounts {
        name = var.storage_share_uploads_name
        path = "/var/www/html/wp-content/uploads"
      }
      volume_mounts {
        name = var.storage_share_cache_name
        path = "/var/www/html/wp-content/cache"
      }
    }

    volume {
      name         = var.storage_share_uploads_name
      storage_name = var.storage_share_uploads_name
      storage_type = "AzureFile"
    }

    volume {
      name         = var.storage_share_cache_name
      storage_name = var.storage_share_cache_name
      storage_type = "AzureFile"
    }
  }

  tags = var.tags

  lifecycle {
    ignore_changes = [
      tags["CreationDate"]
    ]
  }


  depends_on = [
    azurerm_container_app_environment_storage.wordpress,
    azurerm_container_app_environment_storage.wordpress_uploads,
    azurerm_container_app_environment_storage.wordpress_cache,
    azurerm_mysql_flexible_server_configuration.ssl,
    azurerm_private_endpoint.mysql_pe
  ]
}

# AcrPull: Container App system-assigned identity to this ACR.
resource "azurerm_role_assignment" "aca_acr_pull" {
  scope                = azurerm_container_registry.wp.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_container_app.wordpress.identity[0].principal_id

  depends_on = [
    azurerm_container_registry.wp,
    azurerm_container_app.wordpress,
  ]
}
