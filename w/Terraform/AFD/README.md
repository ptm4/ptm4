# AFD Terraform Module

Reusable Terraform modules for onboarding sites onto the existing SHC Azure Front Door profile (`fd-JLB-Hub-FrontDoor`). All SHC AFD sites use the PLS (Private Link Service) path backed by the NorthSouth ILB.

---

## Folder Structure

```
AFD/
├── modules/
│   ├── afd-site/          ← AFD resources per site
│   │   ├── main.tf          origin group, origin (PLS), custom domain,
│   │   ├── variables.tf     DNS TXT + CNAME records, route, WAF policy,
│   │   └── outputs.tf       security policy
│   │
│   └── afd-pls-stack/     ← Network plumbing per site
│       ├── main.tf          ILB load balancing rule (HA ports) +
│       ├── variables.tf     Private Link Service
│       └── outputs.tf
│
├── deployments/
│   └── <site-name>/       ← One folder per AFD site deployment
│       ├── main.tf
│       ├── variables.tf
│       ├── providers.tf
│       ├── outputs.tf
│       └── terraform.tfvars
│
├── intake/
│   └── AFD-Site-Intake.xlsx   ← Site intake spreadsheet (one row per site)
│
├── New-AFDSiteIntake.ps1  ← Regenerates the intake Excel from scratch
└── README.md              ← This file
```

---

## What Each Module Creates

### `afd-site`

| Resource | Naming Convention |
|---|---|
| Origin Group | `og-<app_name>` |
| Origin (PLS-backed) | `o-<app_name>` |
| Custom Domain (AFD-managed cert, TLS 1.2) | derived from hostname |
| DNS TXT record for validation | `_dnsauth.<subdomain>` |
| DNS CNAME record | `<subdomain>` → AFD endpoint hostname |
| Route | `rt-<app_name>` |
| WAF Firewall Policy (bot protection enabled) | `waf<appnamenodashes>` |
| Security Policy | `waf-<app_name>` |

### `afd-pls-stack`

| Resource | Naming Convention |
|---|---|
| ILB Load Balancing Rule (HA ports, floating IP) | `lbr-<app_name>` |
| Private Link Service | `pls-<app_name>` |

> **Note:** The ILB frontend IP (`AFD-<app_name>`) is **not** created by Terraform. It is a manual prerequisite — see Step 2 of the onboarding process below.

---

## Existing Infrastructure (not managed by these modules)

| Resource | Name | Location |
|---|---|---|
| AFD Profile | `fd-JLB-Hub-FrontDoor` | `rg-JLB-Hub-FrontDoor` |
| AFD Endpoints | `prod`, `prod-api`, `test`, `test-api`, `dev`, `dev-api` | same RG |
| NorthSouth ILB | `FGHA-NorthSouth-internalloadbalancer` | `rg-network-prod` |
| ILB Backend Pool | `FGHA-NorthSOuth-ILB-snet-afd-prod-backend` | same RG |
| ILB Health Probe | `lbprobe` (TCP:8008) | same RG |
| Hub VNet | `vnet-hub-prod-eus2` | `rg-network-prod` |
| Internal Subnet | `snet-afd-prod` | inside hub VNet |
| DNS Zone RG | `rg-JLB-Hub-Public_DNS_Zones` | — |
| PLS Resource Group | `rg-JLB-Hub-FrontDoor` | — |

---

## Onboarding a New Site — Step by Step

### Step 1 — Fill in the Intake Spreadsheet

1. Open `intake/AFD-Site-Intake.xlsx`.
2. Add a new row to the **Sites** sheet. Fill in every column for the new site:

   | Column | Description |
   |---|---|
   | `app_name` | Short site name (e.g. `weconnect-qa`). Drives all resource naming. |
   | `afd_endpoint` | Which existing AFD endpoint to attach the route to (`prod`, `test`, `dev`, `prod-api`, `test-api`, `dev-api`). |
   | `backend_host_name` | Origin hostname (e.g. Azure Static App or App Service hostname). |
   | `origin_host_header` | Host header sent to origin. Usually the same as `custom_domain`. |
   | `custom_domain` | Full custom domain registered on AFD (e.g. `weconnect-qa.jammylab.dev`). |
   | `dns_zone` | Azure DNS zone containing the domain (e.g. `jammylab.dev` or `jammylab.com`). |
   | `dns_subdomain` | Subdomain label only (e.g. `weconnect-qa`). Leave blank for apex/root domains. |
   | `health_probe_enabled` | `TRUE` for most sites. `FALSE` only if origin has no health endpoint. |
   | `health_probe_path` | Health check URL path (e.g. `/` or `/healthchecks-api`). |
   | `health_probe_method` | `HEAD` or `GET`. |
   | `ilb_private_ip` | **REVIEW** — Static private IP to assign to the ILB frontend IP. Allocate from the network allocation tracker before proceeding to Step 2. |
   | `pls_request_message` | Short message sent with the PLS connection approval request (e.g. `AFD`). |
   | `notes` | Free-text notes about the site. |

3. Check the **Constants** sheet to confirm the shared infrastructure values are still current (subscription ID, state storage, ILB name, etc.). These only change if the environment changes.

---

### Step 2 — Create the ILB Frontend IP (Manual — Azure Portal)

> **Why manual?** The AzureRM Terraform provider does not support `azurerm_lb_frontend_ip_configuration` as a standalone resource. Frontend IPs are inline blocks inside `azurerm_lb`. Since `FGHA-NorthSouth-internalloadbalancer` is a shared production resource not managed in this Terraform state, the safest approach is to add the frontend IP manually. The `afd-pls-stack` module auto-derives the name (`AFD-<app_name>`) and full resource ID from `app_name` — no manual ID entry is required in `terraform.tfvars`.

**What you are creating:** A new private static frontend IP configuration on the existing NorthSouth ILB, named `AFD-<app_name>`.

**Before you start:** Confirm the static private IP with the network allocation tracker / creation Excel (`ilb_private_ip` column from Step 1).

#### Portal Steps

1. **Navigate to the Load Balancer**
   - In the [Azure Portal](https://portal.azure.com), go to the search bar at the top and type `FGHA-NorthSouth-internalloadbalancer`.
   - Select the Load Balancer result under the `rg-network-prod` resource group.

2. **Open Frontend IP Configuration**
   - In the left-hand menu of the Load Balancer, scroll to the **Settings** section.
   - Click **Frontend IP configuration**.
   - You will see the existing frontend IP configurations listed.

3. **Add a New Configuration**
   - Click **+ Add** at the top of the Frontend IP configuration blade.
   - The **Add frontend IP configuration** panel opens on the right.

4. **Fill in the Fields**

   | Field | Value |
   |---|---|
   | **Name** | `AFD-<app_name>` — e.g. `AFD-weconnect-qa` |
   | **IP version** | IPv4 |
   | **IP type** | Private |
   | **IP address assignment** | Static |
   | **IP address** | The static IP from the network allocation tracker (`ilb_private_ip` from the intake sheet) |
   | **Virtual network** | `vnet-hub-prod-eus2` |
   | **Subnet** | `snet-afd-prod` |

   > Leave all other fields at their defaults.

5. **Save**
   - Click **Add** (or **Save**) at the bottom of the panel.
   - Wait for the portal to confirm the update succeeds (green notification banner).
   - The new frontend IP will appear in the list.

6. **Record in the Intake Sheet**
   - Confirm the `ilb_private_ip` value in the intake Excel matches what was assigned.
   - No further action is needed — the Terraform module constructs the full resource ID automatically using the naming convention `AFD-<app_name>`.

7. **Verify (optional but recommended)**
   - In the portal, click the new frontend IP configuration you just created.
   - Confirm: Name matches `AFD-<app_name>`, IP assignment is Static, IP address is correct, subnet is `snet-afd-prod`.

---

### Step 3 — Create the Deployment Folder

1. Copy the example deployment:

   ```powershell
   Copy-Item -Recurse "deployments\example-site" "deployments\<site-name>"
   ```
   Replace `<site-name>` with your `app_name` value (e.g. `weconnect-qa`).

2. Open `deployments\<site-name>\terraform.tfvars` and fill in all values from the intake spreadsheet row:

   | tfvars field | Value / Intake column |
   |---|---|
   | `subscription_id` | `a1b2c3d4-1111-4000-8000-111111111111` (constant) |
   | `app_name` | `app_name` |
   | `frontdoor_endpoint_name` | `afd_endpoint` |
   | `backend_host_name` | `backend_host_name` |
   | `origin_host_header` | `origin_host_header` |
   | `custom_domain_hostname` | `custom_domain` |
   | `dns_zone_name` | `dns_zone` |
   | `dns_subdomain` | `dns_subdomain` |
   | `health_probe_enabled` | `health_probe_enabled` |
   | `health_probe_path` | `health_probe_path` |
   | `health_probe_request_type` | `health_probe_method` |
   | `pls_request_message` | `pls_request_message` |

   > The backend storage configuration (storage account, container, state key) is supplied entirely by the pipeline — nothing backend-related goes in `terraform.tfvars`.

3. Commit and push the new deployment folder to the repo on your working branch.

---

### Step 4 — Run the Pipeline

The AFD pipeline is located at `Pipelines/AFD/afd-pipeline.yml`. It is a **manually triggered** pipeline with a Plan → Approval → Apply flow. No direct `terraform` CLI commands are needed.

#### Pipeline Overview

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Plan job   │────▶│ WaitForApproval  │────▶│  Apply job  │
│             │     │  (manual gate)   │     │             │
│ tf init     │     │                  │     │ tf init     │
│ tf plan     │     │ 60-min timeout   │     │ tf apply    │
│ publish     │     │ auto-reject      │     │             │
│ artifact    │     │ on timeout       │     │             │
└─────────────┘     └──────────────────┘     └─────────────┘
```

#### Backend Configuration (baked into pipeline — no tfvars needed)

| Setting | Value |
|---|---|
| Service Connection | `sub-JLB-hub(a1b2c3d4-1111-4000-8000-111111111111)` |
| State Storage RG | `rg-JLB-Hub-Terraform` |
| Storage Account | `jlbstorage` |
| Container | `terraform` |
| State Key | `afd/terraform.tfstate` |
| Agent Pool | `Infra-Pool` |
| Auth | Entra ID (workload identity) |

#### Triggering the Pipeline

1. In Azure DevOps, navigate to **Pipelines** and find **AFD Pipeline** (or the pipeline linked to `afd-pipeline.yml`).

2. Click **Run pipeline**.

3. In the **Run pipeline** panel, set the parameter:

   | Parameter | Value |
   |---|---|
   | **AFD Site Name** | The deployment folder name (e.g. `weconnect-qa`) — must exactly match `deployments/<site-name>` |

4. Click **Run**.

#### What Happens — Stage by Stage

**Job 1: Plan** (runs on `Infra-Pool`)
- Checks out the repo.
- Installs the latest version of Terraform.
- Runs `terraform init` — initialises the backend against `jlbstorage/terraform/afd/terraform.tfstate` using Entra ID auth.
- Runs `terraform plan -out=tfplan` from `deployments/<site-name>/`.
- Publishes the `tfplan` file as a pipeline artifact named `tfplan`.

**Job 2: WaitForApproval** (agentless — `pool: server`)
- Sends an approval notification email to `nnumbat@jammylab.com`.
- The email includes the deployment folder and state key for reference.
- You have **60 minutes** to review and approve. The pipeline **auto-rejects** on timeout.
- To review the plan before approving:
  1. In the pipeline run, click the **Plan** job.
  2. Expand the **Terraform Plan** step to read the full plan output directly in the pipeline logs.
  3. Alternatively, download the `tfplan` artifact from the **Artifacts** tab of the pipeline run (this is the binary plan file, not human-readable on its own).

**Job 3: Apply** (runs on `Infra-Pool`, only after approval)
- Checks out the repo.
- Installs the latest version of Terraform.
- Runs `terraform init` again (required — each job is a fresh agent).
- Downloads the `tfplan` artifact published by the Plan job.
- Runs `terraform apply tfplan` — applies exactly what was planned. No interactive prompts.

> **If you reject or the approval times out:** The pipeline ends at the WaitForApproval job. Nothing is applied. Re-run the pipeline from scratch to try again.

---

### Step 5 — Approve the PLS Connection (Post-Apply, Manual)

After `terraform apply` completes, AFD will attempt to connect through the Private Link Service. This connection request must be manually approved.

1. In the Azure Portal, navigate to:
   `rg-JLB-Hub-FrontDoor` → **Private Link Services** → `pls-<app_name>`

2. In the left menu, click **Private endpoint connections**.

3. You will see a pending connection request from AFD with state **Pending**.

4. Select the checkbox next to the pending connection.

5. Click **Approve** in the top menu bar.

6. In the confirmation dialog, optionally enter a reason, then click **Yes**.

7. The connection state will change to **Approved**. AFD can now route traffic to the origin through the PLS.

   > Alternatively, approve via Azure CLI:
   > ```bash
   > az network private-endpoint-connection approve \
   >   --resource-group rg-JLB-Hub-FrontDoor \
   >   --type Microsoft.Network/privateLinkServices \
   >   --resource-name pls-<app_name> \
   >   --name <connection-name> \
   >   --description "Approved"
   > ```
   > Get `<connection-name>` from:
   > `az network private-link-service show -g rg-JLB-Hub-FrontDoor -n pls-<app_name> --query "privateEndpointConnections[].name"`

---

### Step 6 — Verify Domain Validation

Terraform automatically creates the `_dnsauth.<subdomain>` TXT record for AFD domain validation. Validation typically completes within a few minutes, but can take up to 30 minutes.

1. In the Azure Portal, navigate to:
   `rg-JLB-Hub-FrontDoor` → **Front Door and CDN profiles** → `fd-JLB-Hub-FrontDoor`

2. In the left menu, click **Domains**.

3. Find your custom domain. The **Validation state** column should show **Approved** once the TXT record has been verified by AFD.

4. The **Certificate status** will show **Provisioning** initially, then **Ready** once the AFD-managed certificate has been issued (this can take up to 10 minutes after validation).

---

### Step 7 — Verify End-to-End

Once all statuses are green, confirm the site is reachable:

```powershell
# Should return a 200 or expected redirect — confirms AFD is routing traffic
Invoke-WebRequest -Uri "https://<custom_domain_hostname>" -UseBasicParsing
```

Check in the portal:
- **Route** (`rt-<app_name>`) shows **Enabled**
- **Origin** (`o-<app_name>`) health status shows **Healthy**
- **Security Policy** (`waf-<app_name>`) shows **Active**

---

## Notes

- **Domain validation** is fully automated — Terraform creates the `_dnsauth.<subdomain>` TXT record using the `validation_token` output from the custom domain resource. No manual portal steps needed for this.
- **CNAME record** is also created automatically by Terraform, routing `<subdomain>` to the AFD endpoint hostname.
- **Apex domains** — set `dns_subdomain = ""` in tfvars. Terraform skips the CNAME; you must manually create an alias A record in the DNS zone pointing to the AFD endpoint.
- **WAF policy** is created per site (`waf<name>`) with `Microsoft_BotManagerRuleSet 1.0` in **Prevention** mode.
- **Frontend IP naming** is enforced as `AFD-<app_name>` — the module auto-derives the name and full resource ID. The name must match exactly when you create it manually in Step 2.
- **Shared Terraform state** — all AFD sites share the state file `afd/terraform.tfstate` in the `jlbstorage` storage account. This is intentional; the pipeline backend config is hardcoded and requires no per-site input.
- **Re-running `New-AFDSiteIntake.ps1`** regenerates the intake Excel from scratch. Run it from the `AFD/` folder if columns need to be updated after module changes.
