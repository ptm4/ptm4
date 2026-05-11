output "aci_names_and_ips" {
  description = "Name, resource group, and private IP of each Azure Container Instance"
  value = {
    aci_Lab_LFS = {
      name       = azurerm_container_group.aci_Lab_LFS.name
      rg         = azurerm_container_group.aci_Lab_LFS.resource_group_name
      ip_address = try(azurerm_container_group.aci_Lab_LFS.ip_address, "not-assigned")
    }
    aci_Dev_Back_Office = {
      name       = azurerm_container_group.aci_Dev_Back_Office.name
      rg         = azurerm_container_group.aci_Dev_Back_Office.resource_group_name
      ip_address = try(azurerm_container_group.aci_Dev_Back_Office.ip_address, "not-assigned")
    }
    aci_Dev_Client = {
      name       = azurerm_container_group.aci_Dev_Client.name
      rg         = azurerm_container_group.aci_Dev_Client.resource_group_name
      ip_address = try(azurerm_container_group.aci_Dev_Client.ip_address, "not-assigned")
    }
    aci_Dev_Platform = {
      name       = azurerm_container_group.aci_Dev_Platform.name
      rg         = azurerm_container_group.aci_Dev_Platform.resource_group_name
      ip_address = try(azurerm_container_group.aci_Dev_Platform.ip_address, "not-assigned")
    }
    aci_Dev_Recruitment = {
      name       = azurerm_container_group.aci_Dev_Recruitment.name
      rg         = azurerm_container_group.aci_Dev_Recruitment.resource_group_name
      ip_address = try(azurerm_container_group.aci_Dev_Recruitment.ip_address, "not-assigned")
    }
    aci_Dev_WeConnect = {
      name       = azurerm_container_group.aci_Dev_WeConnect.name
      rg         = azurerm_container_group.aci_Dev_WeConnect.resource_group_name
      ip_address = try(azurerm_container_group.aci_Dev_WeConnect.ip_address, "not-assigned")
    }
    aci_Lab_Frank = {
      name       = azurerm_container_group.aci_Lab_Frank.name
      rg         = azurerm_container_group.aci_Lab_Frank.resource_group_name
      ip_address = try(azurerm_container_group.aci_Lab_Frank.ip_address, "not-assigned")
    }
    aci_Test_IT = {
      name       = azurerm_container_group.aci_Test_IT.name
      rg         = azurerm_container_group.aci_Test_IT.resource_group_name
      ip_address = try(azurerm_container_group.aci_Test_IT.ip_address, "not-assigned")
    }
    aci_Test_lab = {
      name       = azurerm_container_group.aci_Test_lab.name
      rg         = azurerm_container_group.aci_Test_lab.resource_group_name
      ip_address = try(azurerm_container_group.aci_Test_lab.ip_address, "not-assigned")
    }
    aci_rgweconnect_dev = {
      name       = azurerm_container_group.aci_rgweconnect_dev.name
      rg         = azurerm_container_group.aci_rgweconnect_dev.resource_group_name
      ip_address = try(azurerm_container_group.aci_rgweconnect_dev.ip_address, "not-assigned")
    }
  }
}
