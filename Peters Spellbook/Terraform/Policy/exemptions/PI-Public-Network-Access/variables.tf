variable "subscription_id" {
  description = "Azure subscription ID used for provider authentication."
  type        = string
}

variable "policy_assignment_id" {
  description = "Full resource ID of the policy initiative assignment."
  type        = string
}

variable "exemptions" {
  type = map(object({
    scope_id                        = string
    category                        = string
    display_name                    = optional(string)
    description                     = optional(string)
    expires_on                      = optional(string)
    policy_definition_reference_ids = optional(list(string))
  }))
  default = {}
}
