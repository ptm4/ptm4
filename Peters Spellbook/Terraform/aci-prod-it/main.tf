resource "azurerm_container_group" "aci-Prod-IT" {
  provider            = azurerm.sub-JLB-Prod-IT
  name                = "aci-Prod-IT"
  location            = var.aci_configs["aci-Prod-IT"].location
  resource_group_name = var.aci_configs["aci-Prod-IT"].resource_group_name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [var.aci_configs["aci-Prod-IT"].subnet_id]
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
      port     = 445
      protocol = "TCP"
    }
    ports {
      port     = 443
      protocol = "TCP"
    }

    commands = [
      "/bin/sh",
      "-c",
      "apk add --no-cache socat && socat TCP-LISTEN:445,fork EXEC:'/bin/echo Hello from ACI 445' & socat TCP-LISTEN:443,fork EXEC:'/bin/echo Hello from ACI 443' & sleep 28800"
    ]
  }
}