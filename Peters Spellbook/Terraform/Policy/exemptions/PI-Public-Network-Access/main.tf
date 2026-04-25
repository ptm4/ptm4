resource "azurerm_resource_policy_exemption" "this" {
  for_each = var.exemptions

  name                            = each.key
  resource_id                     = each.value.scope_id
  policy_assignment_id            = var.policy_assignment_id
  exemption_category              = each.value.category
  display_name                    = each.value.display_name
  description                     = each.value.description
  expires_on                      = each.value.expires_on
  policy_definition_reference_ids = each.value.policy_definition_reference_ids
}
