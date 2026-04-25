# PI-Public-Network-Access — Exemptions

## Add an exemption

1. Add a block to `terraform.tfvars` under `exemptions`:

```hcl
"exemption-name" = {
  scope_id     = "/subscriptions/<sub>/resourceGroups/<rg>/providers/<type>/<name>"
  category     = "Waiver"        # or "Mitigated"
  display_name = "Friendly name"
  description  = "Reason / ticket"
  expires_on   = "2027-12-31T00:00:00Z"  # optional
}
```

2. Commit and run `policy-pipeline.yml`.
