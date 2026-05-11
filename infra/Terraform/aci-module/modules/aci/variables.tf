variable "aci_config" {
  type = object({
    name                = string
    subnet_id           = string
    location            = string
    resource_group_name = string
  })
}

variable "aci_provider" {
  type = any
}
