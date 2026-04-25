locals {
  aci_providers = {
    "sub-JLB-Lab-LFS"                 = azurerm.sub-JLB-Lab-LFS
    "sub-JLB-Dev-ELMER-Back_Office"   = azurerm.sub-JLB-Dev-ELMER-Back_Office
    "sub-JLB-Dev-ELMER-Client"        = azurerm.sub-JLB-Dev-ELMER-Client
    "sub-JLB-Dev-ELMER-Platform"      = azurerm.sub-JLB-Dev-ELMER-Platform
    "sub-JLB-Dev-ELMER-Recruitment"   = azurerm.sub-JLB-Dev-ELMER-Recruitment
    "sub-JLB-Dev-ELMER-WeConnect"     = azurerm.sub-JLB-Dev-ELMER-WeConnect
    "sub-JLB-Lab-FRobertson"          = azurerm.sub-JLB-Lab-FRobertson
    "sub-JLB-Test-IT"                 = azurerm.sub-JLB-Test-IT
    "sub-JLB-Test-lab"                = azurerm.sub-JLB-Test-lab
    "sub-JLB-Test-SQL"                = azurerm.sub-JLB-Test-SQL
    "sub-JLB-Prod-Legacy"             = azurerm.sub-JLB-Prod-Legacy
    "sub-JLB-Prod-WeConnect"          = azurerm.sub-JLB-Prod-WeConnect
    "sub-JLB-Test-DATA"               = azurerm.sub-JLB-Test-DATA
    "sub-JLB-Test-Legacy"             = azurerm.sub-JLB-Test-Legacy
    "sub-JLB-QA-ELMER-WeConnect"      = azurerm.sub-JLB-QA-ELMER-WeConnect
    "sub-JLB-UAT-ELMER-WeConnect"     = azurerm.sub-JLB-UAT-ELMER-WeConnect
  }
}

variable "subscription_id" {
  type = string
}

variable "tenant_id" {
  type = string
}

provider "azurerm" {
  alias           = "dynamic"
  features        = {}
  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id
}

resource "azurerm_container_group" "aci" {
  provider            = azurerm.dynamic
  name                = var.aci_config.name
  location            = var.aci_config.location
  resource_group_name = var.aci_config.resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_config.subnet_id]
  restart_policy      = "Never"

  lifecycle {
    ignore_changes = [tags]
  }

  container {
    name   = "netshoot"
    image  = "nicolaka/netshoot"
    cpu    = "0.5"
    memory = "1.0"

    ports {
      port     = 1433
      protocol = "TCP"
    }

    ports {
      port     = 5033
      protocol = "TCP"
    }

    commands = [
      "/bin/sh",
      "-c",
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ${var.aci_config.name} 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ${var.aci_config.name} 5033' & sleep 28800"
    ]
  }
}
