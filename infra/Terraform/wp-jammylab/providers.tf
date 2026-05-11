# providers.tf

terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "4.58.0"
    }
  }

  backend "azurerm" {}
}

provider "azurerm" {
  features {}
  subscription_id = "b2c3d4e5-2222-4000-8000-222222222222"
}

provider "azurerm" {
  alias           = "dns_sub"
  features        {}
  subscription_id = "a1b2c3d4-1111-4000-8000-111111111111"
}
