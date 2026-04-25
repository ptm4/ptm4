variable "aci_configs" {
  description = "ACI config for multiple Vnets"
  type = map(object({
    subnet_id           = string
    location            = string
    resource_group_name = string
    provider_alias      =  string
  }))
  default = {
    aci-Prod-IT = {
      subnet_id           = "/subscriptions/41e0ec94-b403-48ef-bcac-3dbfce01f217/resourceGroups/rg-JLB-Lab-LFS-Network-Spoke/providers/Microsoft.Network/virtualNetworks/vnet-JLB-Lab-LFS-Network-Spoke/subnets/snet-JLB-Lab-LFS-Network-Spoke-ContainerInstances"
      location            = "eastus2"
      resource_group_name = "rg-JLB-Lab-LFS-Network-Spoke"
      provider_alias      = "sub-JLB-Prod-IT"
    }
  }
}
