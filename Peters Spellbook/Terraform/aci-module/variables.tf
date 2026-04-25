variable "aci_configs" {
  description = "ACI config for multiple Vnets"
  type = map(object({
    subnet_id           = string
    location            = string
    resource_group_name = string
  }))
  default = {
    aci-Lab-LFS = {
      subnet_id           = "/subscriptions/41e0ec94-b403-48ef-bcac-3dbfce01f217/resourceGroups/rg-JLB-Lab-LFS-Network-Spoke/providers/Microsoft.Network/virtualNetworks/vnet-JLB-Lab-LFS-Network-Spoke/subnets/snet-JLB-Lab-LFS-Network-Spoke-ContainerInstances"
      location            = "eastus2"
      resource_group_name = "rg-JLB-Lab-LFS-Network-Spoke"

    }
    aci-DEV-Back_Office = {
      subnet_id           = "/subscriptions/e8bed035-44e0-415b-a80c-054502b15188/resourceGroups/rg-JLB-DEV-ELMER-Back_Office-Network-Spoke/providers/Microsoft.Network/virtualNetworks/vnet-JLB-DEV-ELMER-Back_Office-Network-Spoke/subnets/snet-JLB-DEV-ELMER-Back_Office-ContainerInstances"
      location            = "eastus2"
      resource_group_name = "rg-JLB-DEV-ELMER-Back_Office-Network-Spoke"
   
    }
    aci-DEV-Client = {
      subnet_id           = "/subscriptions/54b323b0-e4e0-4692-adec-a4c4dc33fbc7/resourceGroups/rg-JLB-Dev-ELMER-Client-Network-Spoke/providers/Microsoft.Network/virtualNetworks/vnet-JLB-Dev-ELMER-Client-Network-Spoke/subnets/snet-JLB-DEV-ELMER-Client-ContainerInstances"
      location            = "eastus2"
      resource_group_name = "rg-JLB-Dev-ELMER-Client-Network-Spoke"

    }
    aci-DEV-Platform = {
      subnet_id           = "/subscriptions/a8de1922-6b87-4c86-8fd6-98fc2ae45289/resourceGroups/rg-JLB-Dev-ELMER-Platform-Network-Spoke/providers/Microsoft.Network/virtualNetworks/vnet-JLB-Dev-ELMER-Platform-Network-Spoke/subnets/snet-JLB-DEV-ELMER-Platform-ACI"
      location            = "eastus2"
      resource_group_name = "rg-JLB-Dev-ELMER-Platform-Network-Spoke"

    }
    aci-DEV-Recruitment = {
      subnet_id           = "/subscriptions/6aabb8fe-c76b-4f3e-b6a5-cec0cc51eb05/resourceGroups/rg-JLB-Dev-ELMER-Recruitment-Network-Spoke/providers/Microsoft.Network/virtualNetworks/vnet-JLB-Dev-ELMER-Recruitment-Network-Spoke/subnets/snet-JLB-DEV-ELMER-Recruitment-Microsoft.ContainerInstance_containerGroups"
      location            = "eastus2"
      resource_group_name = "rg-JLB-Dev-ELMER-Recruitment-Network-Spoke"

    }
    aci-DEV-WeConnect = {
      subnet_id           = "/subscriptions/30af05a1-5356-4a75-be60-f49be8713e9b/resourceGroups/rg-JLB-Dev-ELMER-WeConnect-Network-Spoke/providers/Microsoft.Network/virtualNetworks/vnet-JLB-Dev-ELMER-WeConnect-Network-Spoke/subnets/snet-JLB-DEV-ELMER-WeConnect-ContainerInstances"
      location            = "eastus2"
      resource_group_name = "rg-JLB-Dev-ELMER-WeConnect-Network-Spoke"

    }
    aci-Lab-Frank = {
      subnet_id           = "/subscriptions/00e33571-13fe-4d90-b98c-9bff53f3a650/resourceGroups/rg-JLB-Lab-Frank-Network/providers/Microsoft.Network/virtualNetworks/vnet-JLB-Lab-Frank-Network-Spoke/subnets/snet-JLB-Lab-Frank-Network-Spoke-ContainerInstances"
      location            = "eastus2"
      resource_group_name = "rg-JLB-Lab-Frank-Network"

    }
    aci-Test-IT = {
      subnet_id           = "/subscriptions/b2c3d4e5-2222-4000-8000-222222222222/resourceGroups/rg-JLB-Test-IT-Network-Spoke/providers/Microsoft.Network/virtualNetworks/vnet-JLB-Test-IT-Network-Spoke/subnets/snet-JLB-Test-IT-ContainerInstances"
      location            = "eastus2"
      resource_group_name = "rg-JLB-Test-IT-Network-Spoke"

    }
    aci-Test-lab = {
      subnet_id           = "/subscriptions/1f79794a-9bd8-4fc2-91c1-fafb8a1b8a0a/resourceGroups/rg-JLB-Test-Lab-Network-Spoke/providers/Microsoft.Network/virtualNetworks/vnet-JLB-Test-Lab-Network-Spoke/subnets/snet-JLB-Test-Lab-ContainerInstances"
      location            = "eastus2"
      resource_group_name = "rg-JLB-Test-Lab-Network-Spoke"

    }
    aci-rgweconnect-dev = {
      subnet_id           = "/subscriptions/30af05a1-5356-4a75-be60-f49be8713e9b/resourceGroups/rg-weconnect-dev/providers/Microsoft.Network/virtualNetworks/vnet-weconnect-dev/subnets/snet-ContainerInstance"
      location            = "eastus2"
      resource_group_name = "rg-weconnect-dev"

    }
    aci-test-sql = {
      subnet_id           = "/subscriptions/a7d4157f-9a07-405e-a544-aebc89cb6c6e/resourceGroups/rg-JLB-Test-SQL-Network-Spoke/providers/Microsoft.Network/virtualNetworks/vnet-JLB-Test-SQL-Network-Spoke/subnets/snet-JLB-Test-SQL-ContainerInstance"
      location            = "eastus2"
      resource_group_name = "rg-JLB-Test-SQL-Network-Spoke"

    }
    aci-prod-legacy = {
      subnet_id           = "/subscriptions/d9cbc00b-b383-45d2-b4bf-e3051a2d2411/resourceGroups/rg-JLB-Prod-Legacy-Network-Spoke/providers/Microsoft.Network/virtualNetworks/vnet-JLB-Prod-Legacy-Network-Spoke/subnets/snet-JLB-Prod-Legacy-ContainerInstance"
      location            = "eastus2"
      resource_group_name = "rg-JLB-Prod-Legacy-Network-Spoke"

    }
    aci-prod-weconnect = {
      subnet_id           = "/subscriptions/8a374d1a-427f-4516-b5ad-4581798f6af0/resourceGroups/rg-JLB-Prod-WeConnect-Network-Spoke/providers/Microsoft.Network/virtualNetworks/vnet-JLB-Prod-WeConnect-Network-Spoke/subnets/snet-JLB-Prod-WeConnect-ContainerInstance"
      location            = "eastus2"
      resource_group_name = "rg-JLB-Prod-WeConnect-Network-Spoke"

    }
    aci-test-data = {
      subnet_id           = "/subscriptions/d4e5f6a7-4444-4000-8000-444444444444/resourceGroups/rg-JLB-Test-Data-Network-Spoke/providers/Microsoft.Network/virtualNetworks/vnet-JLB-Test-Data-Network-Spoke/subnets/snet-JLB-Test-Data-ContainerInstance"
      location            = "eastus2"
      resource_group_name = "rg-JLB-Test-Data-Network-Spoke"

    }
    aci-test-legacy = {
      subnet_id           = "/subscriptions/1050472d-dfee-4e88-86d0-acad685923cf/resourceGroups/rg-JLB-Test-Legacy-Network-Spoke/providers/Microsoft.Network/virtualNetworks/vnet-JLB-Test-Legacy-Network-Spoke/subnets/snet-JLB-Test-Legacy-ContainerInstance"
      location            = "eastus2"
      resource_group_name = "rg-JLB-Test-Legacy-Network-Spoke"

    }
    aci-qa-elmer-weconnect = {
      subnet_id           = "/subscriptions/4b2c63b0-24ea-4d24-b3d8-fa40917df039/resourceGroups/rg-qa-weconnect/providers/Microsoft.Network/virtualNetworks/vnet-weconnect-qa/subnets/snet-ContainerInstance"
      location            = "eastus2"
      resource_group_name = "rg-qa-weconnect"

    }
    aci-uat-elmer-weconnect = {
      subnet_id           = "/subscriptions/738a09c9-eee9-435c-b9c0-45db1373ad4e/resourceGroups/rg-uat-WeConnect/providers/Microsoft.Network/virtualNetworks/vnet-weconnect-uat/subnets/snet-ContainerInstance"
      location            = "eastus2"
      resource_group_name = "rg-uat-WeConnect"

    }
    aci-dev-elmer-backoffice = {
      subnet_id           = "/subscriptions/e8bed035-44e0-415b-a80c-054502b15188/resourceGroups/rg-JLB-DEV-ELMER-Back_Office-Network-Spoke/providers/Microsoft.Network/virtualNetworks/vnet-JLB-DEV-ELMER-Back_Office-Network-Spoke/subnets/snet-JLB-DEV-ELMER-Back_Office-ContainerInstances"
      location            = "eastus2"
      resource_group_name = "rg-JLB-DEV-ELMER-Back_Office-Network-Spoke"

    }
  }
}
