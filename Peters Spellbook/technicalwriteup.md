# **Technical Write-Up**
## Table of Contents

1. [Terraform — AFD (Azure Front Door) Module Suite](#1-terraform--afd-azure-front-door-module-suite)
2. [Terraform — WordPress on Azure Container Apps (`wp-jammylab`)](#2-terraform--wordpress-on-azure-container-apps-wp-jammylab)
3. [Terraform — ACI (Azure Container Instances) Testing Platform](#3-terraform--aci-azure-container-instances-testing-platform)
4. [Terraform — Policy Exemption Framework](#4-terraform--policy-exemption-framework)
5. [Terraform — CAE / Ubuntu VM Proof-of-Concepts](#5-terraform--cae--ubuntu-vm-proof-of-concepts)
6. [Azure DevOps Pipelines](#6-azure-devops-pipelines)
7. [PowerShell — Azure Networking Automation](#7-powershell--azure-networking-automation)
8. [PowerShell — Azure Pipelines (AMPLS + VNet Intake-Driven)](#8-powershell--azure-pipelines-ampls--vnet-intake-driven)
9. [PowerShell — Azure Policy Automation](#9-powershell--azure-policy-automation)
10. [PowerShell — Azure & M365 Misc Utilities](#10-powershell--azure--m365-misc-utilities)
11. [PowerShell WinForms App — GP Voucher Tool](#11-powershell-winforms-app--gp-voucher-tool)
12. [Tech Stack Summary](#12-tech-stack-summary)

---

## 1. Terraform — AFD (Azure Front Door) Module Suite

**Path:** `Terraform/AFD/`

A reusable, pipeline-driven Terraform module system for onboarding new sites onto the existing shared SHC Front Door profile (`fd-JLB-Hub-FrontDoor`). Every SHC AFD site uses the **Private Link Service (PLS) path** backed by an internal load balancer — this module abstracts away all of the underlying plumbing so new sites can be added with a single Excel row + one `terraform.tfvars` file.

### What it builds
- **`modules/afd-site/`** — AFD origin group, PLS-backed origin, custom domain (AFD-managed cert, TLS 1.2), DNS TXT validation record, DNS CNAME, route (HTTPS-only by default), WAF policy (`Microsoft_BotManagerRuleSet 1.0` in Prevention mode), security policy binding.
- **`modules/afd-pls-stack/`** — ILB HA-ports load balancing rule + Azure Private Link Service fronting the ILB frontend IP (with NAT IP configuration in `snet-afd-prod`).
- **`deployments/<site>/`** — per-site deployment folder (`main.tf` wires both modules, `terraform.tfvars` is populated from the intake sheet). Live deployments:
  - `aca-wp-jammylab`
  - `quillsigner`
  - `quillsigner-qa`
- **WordPress-aware cache-bypass rule set** — optional AFD rule set that disables caching on `wp-admin`, `wp-login.php`, and any request carrying `wordpress_logged_in` / `wordpress_sec_` cookies. Prevents stale nonces and broken AJAX in admin flows.
- **Apex-domain handling** — module conditionally skips CNAME creation for apex/root domains and leaves the operator to create the alias-A record manually.
- **Naming convention is fully derived from `app_name`** — `og-<app>`, `o-<app>`, `rt-<app>`, `waf<app>`, `waf-<app>`, `pls-<app>`, `lbr-<app>`, `AFD-<app>`.

### Intake automation
- **`New-AFDSiteIntake.ps1`** — PowerShell generator that rebuilds `intake/AFD-Site-Intake.xlsx` from scratch using the `ImportExcel` module. Produces a two-sheet workbook:
  - **Sites** sheet — one row per AFD site with columns that map 1:1 to `terraform.tfvars` fields, plus a `REVIEW` cell comment on `ilb_private_ip` reminding the operator to allocate from the network tracker first.
  - **Constants** sheet — shared subscription ID, ILB name, DNS zone RG, backend state storage, tag conventions.

### Documentation
- **`README.md`** — step-by-step onboarding runbook (7 steps): fill intake sheet → pre-create ILB frontend IP in portal → create deployment folder → trigger pipeline (Plan → Approval → Apply) → approve PLS connection → verify domain validation → end-to-end smoke test. Includes a full architecture diagram of the pipeline flow and exhaustive field-by-field mapping between the intake sheet, tfvars, and deployed resources.

---

## 2. Terraform — WordPress on Azure Container Apps (`wp-jammylab`)

**Path:** `Terraform/wp-jammylab/`

End-to-end Terraform build of a **fully private, HIPAA-appropriate WordPress platform on Azure Container Apps**, designed as the replacement for the legacy externally-hosted `jobs.jammylab.com` production site. All ingress is through Azure Front Door + Private Link Service — no public endpoints on any backing resource.

### Resources deployed
- Resource group, Log Analytics workspace (PerGB2018, 30d retention), full tag governance with `CreationDate` lifecycle ignores.
- **Azure Key Vault** (RBAC-auth, public access disabled) + private endpoint with DNS-zone group.
- **Azure Storage Account** (Premium FileStorage, LRS, TLS 1.2 min, public access disabled) with three SMB file shares: `wordpress`, `wordpress-uploads`, `wordpress-cache`. Private endpoint with DNS-zone group.
- **Azure Container Registry** (SKU-configurable, admin disabled — ACR pull granted via role assignment to the Container App identity).
- **MySQL Flexible Server** (`GP_Standard_D2ds_v4`, 8.0.21) with enforced TLS, 7-day backup retention, private DNS zone integration, private endpoint with DNS-zone group, and dedicated `azurerm_mysql_flexible_server_configuration` enforcing `require_secure_transport = ON`.
- **Container App Environment** (Consumption profile, internal load balancer, zone-redundant) + private endpoint wired to the hub `privatelink.eastus2.azurecontainerapps.io` DNS zone. Environment-level storage mounts for all three SMB shares.
- **RBAC** — Container App managed identity granted `Key Vault Secrets User` + `Key Vault Certificate User` and `AcrPull` role assignments.
- **Container App** running the custom WordPress image with the three file shares mounted, secret references from Key Vault, and `WORDPRESS_CONFIG_EXTRA` overrides baked in.

### Custom WordPress container image (`docker/`)
- **`Dockerfile`** — based on `wordpress:php8.2-apache`, adds OPcache config, and installs a custom entrypoint.
- **`opcache.ini`** — production-tuned PHP OPcache settings.
- **`entrypoint.sh`** — custom bash entrypoint that:
  1. On first run, generates all 8 WordPress auth keys/salts (`AUTH_KEY`, `SECURE_AUTH_KEY`, `LOGGED_IN_KEY`, `NONCE_KEY`, and corresponding salts) using PHP's `random_bytes(48)` and persists them to the uploads SMB share as an env file. On subsequent starts the same keys are reloaded — solving the "keys rotate on every deploy = everyone logged out" problem without any manual intervention.
  2. Auto-symlinks writable plugin subdirectories (`storage`, `data`, `cache`, `tmp`, `backups`, `logs`) from the read-only image layer onto the persistent uploads share, so plugins that write state at runtime survive container restarts and image redeploys.

### Operations runbook (`ProdDeployment.md`)
A detailed 312-line production cutover runbook covering:
- Copying the folder for the `prod-it` subscription and what specifically needs to change
- Adding the PHP `upload_max_filesize` override for large migration imports
- State storage, backend configuration, and pipeline updates
- AFD prod deployment folder creation
- Full cutover plan for moving the legacy production site onto Azure

---

## 3. Terraform — ACI (Azure Container Instances) Testing Platform

**Path:** `Terraform/aci-module/`, `Terraform/aci-prod-it/`, `Terraform/ACI-vnet-testing/`

A multi-subscription ACI fleet used for **network connectivity validation** across the hub-and-spoke topology. Each container runs `nicolaka/netshoot` and opens `socat` listeners on common ports (1433 SQL, 5033, 443, 445) so engineers can test firewall rules, NSG paths, peerings, and Private Endpoint DNS resolution from inside each spoke VNet.

### `aci-module/` — reusable module pattern
- Single `azurerm_container_group` resource parameterized via `aci_config` input.
- Uses a dynamic provider alias pattern (`azurerm.dynamic`) with `subscription_id` / `tenant_id` as inputs, enabling the module to be re-used across 16+ subscriptions without duplicating provider blocks.
- Hardcoded subscription alias map for all SHC subscriptions (Lab-LFS, Dev-ELMER-*, Test-IT, Test-lab, Test-SQL, Prod-Legacy, Prod-WeConnect, Test-DATA, Test-Legacy, QA/UAT ELMER-WeConnect).

### `ACI-vnet-testing/` — the deployed fleet
15+ container groups wired into the correct spoke VNets across: Lab-LFS, Dev Back_Office, Dev Client, Dev Platform, Dev Recruitment, Dev WeConnect, Lab Frank, Test-IT, Test-lab, rgweconnect-dev, test-sql, prod-legacy, prod-weconnect, test-data, test-legacy, QA-ELMER-WeConnect, UAT-ELMER-WeConnect. Each runs the netshoot image with ports 1433 + 5033, `Private` IP only, `Never` restart policy, and an 8-hour `sleep 28800` lifetime.

### `aci-prod-it/` — prod IT variant
Specialized deployment for the Prod-IT spoke using ports 443 / 445 for SMB + TLS connectivity testing.

---

## 4. Terraform — Policy Exemption Framework

**Path:** `Terraform/Policy/exemptions/`

A small, composable Terraform pattern for managing Azure Policy exemptions as code. Solves the recurring pain of tracking ad-hoc exemptions granted via the portal.

- **`PI-Public-Network-Access/`** — first production use of the pattern, applied against the `PI-Public-Network-Access` initiative.
- Single `azurerm_resource_policy_exemption` resource in a `for_each` over a `var.exemptions` map. Each exemption key defines `scope_id`, `category` (`Waiver` / `Mitigated`), `display_name`, `description`, optional `expires_on`, and `policy_definition_reference_ids`.
- Lightweight `README.md` that teaches any engineer how to add a new exemption via a single tfvars block + PR.
- Wired into its own pipeline with Plan → Manual Approval → Apply (see §6).

---

## 5. Terraform — CAE / Ubuntu VM Proof-of-Concepts

**Path:** `Terraform/cae-jammylab-test-it/`, `Terraform/ubuntuvm-testing/`

- **`cae-jammylab-test-it/`** — early test-it-subscription build of the Container App Environment + MySQL Flexible Server + Container App pattern that eventually became the full `wp-jammylab` solution. Kept as a reference for the simpler baseline.
- **`ubuntuvm-testing/`** — reusable Linux VM module (NIC + `azurerm_linux_virtual_machine`, Ubuntu 22.04 LTS Jammy, Premium_LRS 30 GB OS disk) with **6 environment-specific `*.auto.tfvars` files**: `devdata`, `devtest`, `proddatapowerbi`, `prodmodern`, `prodweconnect`, `testmodern`. Used for temporary jump-host / testing VMs across the environment matrix.

---

## 6. Azure DevOps Pipelines

**Path:** `Terraform/Pipelines/`, `Azure/Pipelines/`

All pipelines follow a consistent pattern: **manual trigger → Plan → Manual Approval (email to `nnumbat@jammylab.com`, 60-min timeout with auto-reject) → Apply**. All use Entra ID workload-identity auth, self-hosted `Infra-Pool` agents (pinned to `vm-infra-pool2`), and the shared `jlbstorage` Terraform state account.

| Pipeline | Purpose |
|---|---|
| `Terraform/Pipelines/pipeline.yml` | Main Terraform deploy pipeline for `wp-jammylab` (state key `cae/terraform.tfstate`). |
| `Terraform/Pipelines/AFD/afd-pipeline.yml` | AFD site deploy — takes a `site_name` parameter that resolves to `deployments/<site>/` and a per-site state key (`afd/<site>.tfstate`). |
| `Terraform/Pipelines/Policy/policy-pipeline.yml` | Policy exemption deploy pipeline (state key `policy/pi-public-network-access.tfstate`). |
| `Terraform/Pipelines/wp-jammylab-docker-pipeline.yml` | Builds + pushes the custom WordPress image to ACR (`acrwpjammylabeus2`) via `Docker@2 buildAndPush`, tagging with both `$(Build.BuildId)` and `latest`. |
| `Azure/Pipelines/AMPLS/ampls-pipeline.yaml` | Parameter-rich AMPLS deployment pipeline (13 inputs) with a dedicated Validate stage that checks every required parameter and verifies the target VNet + subnet exist before handing off to deploy. |
| `Azure/Pipelines/VNets/vnet-pipeline.yaml` | Excel-driven VNet + peering + vHub deployment pipeline. Validates the Excel workbook exists and has rows before running the deployment script. |

---

## 7. PowerShell — Azure Networking Automation

**Path:** `Azure/Networking/`

Nine PowerShell scripts that handle the recurring networking operations across the 20+ subscription estate. Heavy use of cross-subscription `az` CLI calls with safe context-switching and per-operation try/catch.

| Script | What it does |
|---|---|
| `Vnetpeer.ps1` | Bi-directional hub↔spoke peering creator driven by a `$peerSets` array. Hardcoded with the full production peer-set inventory (10+ spoke definitions). Handles cross-subscription context switching + `LASTEXITCODE` error propagation. |
| `peerdeploy.ps1` | CSV-driven generalization of `Vnetpeer.ps1`. Accepts `VNetName, ResourceGroup, SubscriptionID` columns; builds peer sets dynamically; hash-truncates peer names that exceed Azure's 80-char limit. |
| `azvnetpeering.ps1` | Foreach-based peering deploy helper kept for ad-hoc use; contains the raw `az network vnet peering create` invocations as templates. |
| `VnetLinkCleanup.ps1` | Cleanup script that enumerates every VNet link on a given private DNS zone and removes them in bulk (used for AFD / ACA DNS zone migrations). |
| `createVNet.ps1` | End-to-end VNet creator that makes the VNet + subnets, then **links to the hub vHub** and creates the bi-directional peering to the Bastion hub. Includes bespoke `New-VHubLink` and `New-BastionPeering` functions with per-op validation. |
| `devsubpeers.ps1` | Same pattern as `createVNet.ps1` but scoped to Dev subscriptions — used for onboarding new Dev spokes. |
| `getVnetInfo.ps1` | Takes a hardcoded here-string map of `vnetName,subscription` pairs, resolves each VNet's resource group, and exports results to CSV (`VNetInfo.csv`). Used as the feeder for `peerdeploy.ps1`. |
| `getazvnet.ps1` | Resource-inventory helper that takes a CSV of resource names and determines the associated VNet ID whether the input is a VNet, private endpoint, or a PaaS resource with an attached PE. |
| `PrivateDNS.ps1` | Bulk-creates private DNS zones (`privatelink.azurecr.io`, `privatelink.eastus2.azurecontainerapps.io`, etc.) in the hub DNS zone RG. |

---

## 8. PowerShell — Azure Pipelines (AMPLS + VNet Intake-Driven)

**Path:** `Azure/Pipelines/AMPLS/`, `Azure/Pipelines/VNets/`

Production-grade deployment scripts that pair with the YAML pipelines in §6.

### `AMPLS/deploy-ampls.ps1`
Idempotent end-to-end deployer for **Azure Monitor Private Link Scope**. Given a target subscription, resource group, AMPLS name, private endpoint name, target VNet/subnet, and optional lists of Log Analytics workspaces / Data Collection Endpoints / Application Insights components:
- Creates the resource group with standard tag set.
- Creates the AMPLS and sets both query-access-mode and ingestion-access-mode.
- Creates the private endpoint for group-id `azuremonitor`.
- **Cross-subscription DNS handling** — switches to the hub subscription (`sub-JLB-hub`) to ensure all 5 AMPLS private DNS zones exist (monitor, ods/oms opinsights, blob, agentsvc) and that a VNet link exists for the target VNet against each zone. Both zone creation and VNet-link creation are idempotent with existence checks.
- Creates the DNS zone group on the private endpoint with all 5 zones wired in a single command.
- Switches back to the target subscription and links the requested LAW / DCE / App Insights resources as scoped resources via `az monitor private-link-scope scoped-resource create`. Each name is sanitized (lowercase, stripped to allowed chars, truncated to ≤60).

### `VNets/deploy-vnet.ps1`
Excel-driven VNet + peering deployer (auto-installs `ImportExcel` module if missing):
- Validates all 8 required columns exist (`VNetName`, `VNetPrefix`, `SubnetName`, `SubnetPrefix`, `ResourceGroup`, `SubscriptionId`, `EnableVhub`, `EnablePeering`).
- Row-level validation pass with line numbers and a single consolidated error report.
- Custom `Get-PeeringName` helper that safely fits peer names within Azure's 80-char limit by appending a truncated SHA-256 hash suffix.
- Groups rows by `VNetName` so a single VNet with multiple subnets gets one `az network vnet create` + N `subnet create` calls.
- Conditional vHub link and bi-directional bastion peering per row via `EnableVhub` / `EnablePeering` flags.
- Hardcoded hub defaults (Bastion hub subscription + VNet).

### `VNets/vnet-config.xlsx`
The live intake workbook paired with the deploy script.

---

## 9. PowerShell — Azure Policy Automation

**Path:** `Azure/Policy/`

- **`policy.ps1`** — policy migration script. Reads a JSON file of exported policy definitions, normalizes each display name into a valid policy name (`[^a-zA-Z0-9_]` stripped, 64-char cap), and re-creates each at a target management group via `New-AzPolicyDefinition -ManagementGroupName`. Green/red per-policy status output.
- **`policyExemption.ps1`** — bulk policy-exemption creator driven by a `$Exemptions` array. Hardcoded with **14 real exemption rows** across 3 subscriptions (Dev / Prod / Test ELMER-Client-Credentialing RGs) targeting the credentialing platform's NLP policy assignment. Per-item sub-scope context switching, name truncation, category `Waiver`. This script was later superseded by the Terraform exemption framework in §4.

---

## 10. PowerShell — Azure & M365 Misc Utilities

**Path:** `Azure/Misc/`

Small single-purpose scripts built in response to specific tickets:

| Script | Purpose |
|---|---|
| `GroupRBACAssign.ps1` | Interactive RBAC role-assignment script. Prompts for an Entra ID group by display name, resolves it to an object ID, then loops through user-supplied roles × user-supplied subscriptions and creates `az role assignment` entries for each pairing. |
| `azcopy.ps1` | Wrapper that kicks off a recursive `azcopy` upload of a local tools folder into an Azure Blob container using a SAS token, with `--overwrite=ifSourceNewer` for idempotent re-runs. |
| `filestruc.ps1` | Recreates an on-prem UNC share's directory tree inside a local drive — used as the first step of lifting share-based content into Azure Files. |
| `EOL-DL.ps1` | Exchange Online Distribution List creator. Prompts for existing connection, creates the distribution group, then loops through a member display-name array and attaches each after resolving via `Get-EXORecipient`. Color-coded status output. |
| `EOL-FIndFwd.ps1` | Exchange Online mailbox forwarding lookup. Accepts either an email or a display name (with multi-match warning), then returns `ForwardingAddress` / `ForwardingSmtpAddress` / `DeliverToMailboxAndForward` for that mailbox. |

---

## 11. PowerShell WinForms App — GP Voucher Tool

**Path:** `GP-VoucherApp/`, `GP-VoucherApp/GPVoucherApp-Deployable/`

A **GUI desktop tool for the AP/Finance team** that wraps a set of SQL voucher-state operations against the on-prem Dynamics GP database. Eliminates the need for finance users to open SSMS.

### Features
- Multi-line "paste vouchers" text area — operators can paste a column of voucher numbers from Excel.
- SQL Server connection supports **either Windows Integrated auth** (default, with visual placeholders showing the current `sup\username`) **or SQL auth** (text + masked password field). Toggle via checkbox — the UI locks/unlocks the credential fields dynamically.
- Two action buttons:
  - **Take Off Hold** — runs `UPDATE PM20000 SET HOLD = 0 WHERE VCHRNMBR = @voucher` for each pasted voucher.
  - **Put On Hold** — the inverse (`HOLD = 1`). Both use parameterized `SqlCommand` to prevent SQL injection.
- Live **in-window log pane** (scroll-locked to bottom, auto-scrolls on append) that mirrors everything being written to the on-disk audit log.
- Full **audit logging** to `%LOCALAPPDATA%\SHC\VoucherApp\GPscript_Audit.log` with ISO timestamps + `$env:USERNAME` on every operation.
- Enter-key binding on Take-Off-Hold, Escape-key closes the form, proper exception handling wrapping every single-voucher update.
- **Packaged as a deployable `.exe`** (`SHCVoucherApp.exe` / `GPVoucherUtil.exe`) with a custom `gpapp.ico` icon, distributed as `GPVoucherApp-Deployable.zip` for the end-user rollout.

---

## 12. Tech Stack Summary

| Category | Tools / Services |
|---|---|
| **IaC** | Terraform (AzureRM provider), HCL, remote state on Azure Storage with Entra ID auth, multi-subscription provider aliasing, module composition |
| **Azure — Compute** | Azure Container Apps, Container App Environments, ACI, Azure Container Registry, Linux VMs (Ubuntu 22.04 LTS) |
| **Azure — Networking** | VNets / Subnets, Hub-and-Spoke peering, Virtual WAN / vHub, Private Endpoints, Private Link Service, Private DNS zones + VNet links, Internal Load Balancer (HA Ports), Azure Front Door (Premium), AFD WAF (Bot Manager), Azure DNS (public + private) |
| **Azure — Data** | Azure Storage Accounts (Premium FileStorage, SMB file shares), MySQL Flexible Server (8.0.21, TLS-enforced) |
| **Azure — Security & Governance** | Entra ID workload identity, Azure Key Vault (RBAC-auth, private-only), Azure Policy (definitions + exemptions), RBAC, AMPLS (Azure Monitor Private Link Scope), Log Analytics, Application Insights, Data Collection Endpoints |
| **Containers** | Docker (multi-stage, PHP 8.2 + Apache + WordPress base), custom entrypoint scripting (bash), OPcache tuning |
| **CI/CD** | Azure DevOps Pipelines (YAML), self-hosted agents, Plan → Manual Approval → Apply pattern, pipeline artifacts, `TerraformInstaller@1`, `TerraformTaskV4@4`, `AzureCLI@2`, `Docker@2`, `ManualValidation@1` |
| **Scripting** | PowerShell 7 (pscore), Azure CLI, Az PowerShell modules, `ImportExcel`, Exchange Online PowerShell V3, azcopy |
| **Desktop** | PowerShell + `System.Windows.Forms` + `System.Drawing`, `System.Data.SqlClient`, packaged into deployable .exe |
| **Patterns** | Cross-subscription automation, hub-and-spoke networking, private-only Azure design (zero-public-endpoint), Excel-as-intake pattern, manual-approval deployment gates, idempotent deploys with existence checks, parameterized modules, module composition (site + plumbing) |

---

## TL;DR

I'm **Noble Numbat**, a cloud / DevOps engineer focused on Azure platform work — IaC, networking, and automation at enterprise scale. This repo is a working portfolio of what I've shipped: reusable Terraform modules (Front Door + PLS, WordPress on Azure Container Apps, ACI, policy exemptions), 20+ PowerShell automation scripts covering cross-subscription networking, AMPLS, Policy, and M365 admin, and Azure DevOps YAML pipelines wired with Plan → Manual Approval → Apply gates and Entra ID workload-identity auth. On the side I also build practical internal tooling, including a packaged PowerShell WinForms app that wraps SQL operations for the finance team. Everything here was designed, written, and deployed in production by me.
