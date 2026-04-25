resource "azurerm_container_group" "aci_Lab_LFS" {
  provider            = azurerm.sub-JLB-Lab-LFS
  name                = "aci-Lab-LFS"
  location            = var.aci_configs["aci-Lab-LFS"].location
  resource_group_name = var.aci_configs["aci-Lab-LFS"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-Lab-LFS"].subnet_id]
  restart_policy      = "Never"

    lifecycle {
    ignore_changes = [
      tags
    ]
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
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ACI 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ACI 5033' & sleep 28800"
    ]
  }
}

resource "azurerm_container_group" "aci_Dev_Back_Office" {
  provider            = azurerm.sub-JLB-Dev-ELMER-Back_Office
  name                = "aci-DEV-Back_Office"
  location            = var.aci_configs["aci-DEV-Back_Office"].location
  resource_group_name = var.aci_configs["aci-DEV-Back_Office"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-DEV-Back_Office"].subnet_id]
  restart_policy      = "Never"

    lifecycle {
    ignore_changes = [
      tags
    ]
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
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ACI 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ACI 5033' & sleep 28800"
    ]
  }
}

resource "azurerm_container_group" "aci_Dev_Client" {
  provider            = azurerm.sub-JLB-Dev-ELMER-Client
  name                = "aci-DEV-Client"
  location            = var.aci_configs["aci-DEV-Client"].location
  resource_group_name = var.aci_configs["aci-DEV-Client"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-DEV-Client"].subnet_id]
  restart_policy      = "Never"

    lifecycle {
    ignore_changes = [
      tags
    ]
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
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ACI 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ACI 5033' & sleep 28800"
    ]
  }
}

resource "azurerm_container_group" "aci_Dev_Platform" {
  provider            = azurerm.sub-JLB-Dev-ELMER-Platform
  name                = "aci-DEV-Platform"
  location            = var.aci_configs["aci-DEV-Platform"].location
  resource_group_name = var.aci_configs["aci-DEV-Platform"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-DEV-Platform"].subnet_id]
  restart_policy      = "Never"

    lifecycle {
    ignore_changes = [
      tags
    ]
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
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ACI 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ACI 5033' & sleep 28800"
    ]
  }
}

resource "azurerm_container_group" "aci_Dev_Recruitment" {
  provider            = azurerm.sub-JLB-Dev-ELMER-Recruitment
  name                = "aci-DEV-Recruitment"
  location            = var.aci_configs["aci-DEV-Recruitment"].location
  resource_group_name = var.aci_configs["aci-DEV-Recruitment"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-DEV-Recruitment"].subnet_id]
  restart_policy      = "Never"

    lifecycle {
    ignore_changes = [
      tags
    ]
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
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ACI 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ACI 5033' & sleep 28800"
    ]
  }
}

resource "azurerm_container_group" "aci_Dev_WeConnect" {
  provider            = azurerm.sub-JLB-Dev-ELMER-WeConnect
  name                = "aci-DEV-WeConnect"
  location            = var.aci_configs["aci-DEV-WeConnect"].location
  resource_group_name = var.aci_configs["aci-DEV-WeConnect"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-DEV-WeConnect"].subnet_id]
  restart_policy      = "Never"

    lifecycle {
    ignore_changes = [
      tags
    ]
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
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ACI 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ACI 5033' & sleep 28800"
    ]
  }
}

resource "azurerm_container_group" "aci_Lab_Frank" {
  provider            = azurerm.sub-JLB-Lab-FRobertson
  name                = "aci_Lab_Frank"
  location            = var.aci_configs["aci-Lab-Frank"].location
  resource_group_name = var.aci_configs["aci-Lab-Frank"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-Lab-Frank"].subnet_id]
  restart_policy      = "Never"

    lifecycle {
    ignore_changes = [
      tags
    ]
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
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ACI 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ACI 5033' & sleep 28800"
    ]
  }
}

resource "azurerm_container_group" "aci_Test_IT" {
  provider            = azurerm.sub-JLB-Test-IT
  name                = "aci-Test-IT"
  location            = var.aci_configs["aci-Test-IT"].location
  resource_group_name = var.aci_configs["aci-Test-IT"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-Test-IT"].subnet_id]
  restart_policy      = "Never"

    lifecycle {
    ignore_changes = [
      tags
    ]
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
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ACI 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ACI 5033' & sleep 28800"
    ]
  }
}

resource "azurerm_container_group" "aci_Test_lab" {
  provider            = azurerm.sub-JLB-Test-lab
  name                = "aci_Test_lab"
  location            = var.aci_configs["aci-Test-lab"].location
  resource_group_name = var.aci_configs["aci-Test-lab"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-Test-lab"].subnet_id]
  restart_policy      = "Never"

    lifecycle {
    ignore_changes = [
      tags
    ]
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
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ACI 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ACI 5033' & sleep 28800"
    ]
  }
}

resource "azurerm_container_group" "aci_rgweconnect_dev" {
  provider            = azurerm.sub-JLB-Dev-ELMER-WeConnect
  name                = "aci-rgweconnect-dev"
  location            = var.aci_configs["aci-rgweconnect-dev"].location
  resource_group_name = var.aci_configs["aci-rgweconnect-dev"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-rgweconnect-dev"].subnet_id]
  restart_policy      = "Never"

    lifecycle {
    ignore_changes = [
      tags
    ]
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
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ACI 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ACI 5033' & sleep 28800"
    ]
  }
}

resource "azurerm_container_group" "aci_test_sql" {
  provider            = azurerm.sub-JLB-Test-SQL
  name                = "aci-test-sql"
  location            = var.aci_configs["aci-test-sql"].location
  resource_group_name = var.aci_configs["aci-test-sql"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-test-sql"].subnet_id]
  restart_policy      = "Never"

    lifecycle {
    ignore_changes = [
      tags
    ]
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
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ACI 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ACI 5033' & sleep 28800"
    ]
  }
}

resource "azurerm_container_group" "aci_prod_legacy" {
  provider            = azurerm.sub-JLB-Prod-Legacy
  name                = "aci-prod-legacy"
  location            = var.aci_configs["aci-prod-legacy"].location
  resource_group_name = var.aci_configs["aci-prod-legacy"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-prod-legacy"].subnet_id]
  restart_policy      = "Never"

    lifecycle {
    ignore_changes = [
      tags
    ]
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
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ACI 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ACI 5033' & sleep 28800"
    ]
  }
}

resource "azurerm_container_group" "aci_prod_weconnect" {
  provider            = azurerm.sub-JLB-Prod-WeConnect
  name                = "aci-prod-weconnect"
  location            = var.aci_configs["aci-prod-weconnect"].location
  resource_group_name = var.aci_configs["aci-prod-weconnect"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-prod-weconnect"].subnet_id]
  restart_policy      = "Never"

    lifecycle {
    ignore_changes = [
      tags
    ]
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
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ACI 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ACI 5033' & sleep 28800"
    ]
  }
}

resource "azurerm_container_group" "aci_test_data" {
  provider            = azurerm.sub-JLB-Test-DATA
  name                = "aci-test-data"
  location            = var.aci_configs["aci-test-data"].location
  resource_group_name = var.aci_configs["aci-test-data"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-test-data"].subnet_id]
  restart_policy      = "Never"

    lifecycle {
    ignore_changes = [
      tags
    ]
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
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ACI 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ACI 5033' & sleep 28800"
    ]
  }
}

resource "azurerm_container_group" "aci_test_legacy" {
  provider            = azurerm.sub-JLB-Test-Legacy
  name                = "aci-test-legacy"
  location            = var.aci_configs["aci-test-legacy"].location
  resource_group_name = var.aci_configs["aci-test-legacy"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-test-legacy"].subnet_id]
  restart_policy      = "Never"

    lifecycle {
    ignore_changes = [
      tags
    ]
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
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ACI 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ACI 5033' & sleep 28800"
    ]
  }
}

resource "azurerm_container_group" "aci_qa_elmer_weconnect" {
  provider            = azurerm.sub-JLB-QA-ELMER-WeConnect
  name                = "aci-qa-elmer-weconnect"
  location            = var.aci_configs["aci-qa-elmer-weconnect"].location
  resource_group_name = var.aci_configs["aci-qa-elmer-weconnect"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-qa-elmer-weconnect"].subnet_id]
  restart_policy      = "Never"

    lifecycle {
    ignore_changes = [
      tags
    ]
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
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ACI 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ACI 5033' & sleep 28800"
    ]
  }
}

resource "azurerm_container_group" "aci_uat_elmer_weconnect" {
  provider            = azurerm.sub-JLB-UAT-ELMER-WeConnect
  name                = "aci-uat-elmer-weconnect"
  location            = var.aci_configs["aci-uat-elmer-weconnect"].location
  resource_group_name = var.aci_configs["aci-uat-elmer-weconnect"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-uat-elmer-weconnect"].subnet_id]
  restart_policy      = "Never"

    lifecycle {
    ignore_changes = [
      tags
    ]
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
      "apk add --no-cache socat && socat TCP-LISTEN:1433,fork EXEC:'/bin/echo Hello from ACI 1433' & socat TCP-LISTEN:5033,fork EXEC:'/bin/echo Hello from ACI 5033' & sleep 28800"
    ]
  }
}


