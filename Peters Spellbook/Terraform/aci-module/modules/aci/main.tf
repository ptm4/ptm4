resource "azurerm_container_group" "aci" {
  provider            = azurerm
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
