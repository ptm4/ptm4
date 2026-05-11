terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }

  # Partial backend configuration — all values are supplied by the pipeline
  # (TerraformTaskV4 backendAzureRm* inputs) or via -backend-config flags for
  # local runs. Terraform does not allow var.* references inside backend blocks.
  backend "azurerm" {}
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}
