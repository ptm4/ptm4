<#
.SYNOPSIS
    Generates the AFD site intake Excel workbook (AFD-Site-Intake.xlsx).

.DESCRIPTION
    Creates or overwrites intake/AFD-Site-Intake.xlsx with:
      Sheet 1 "Sites"     — one row per AFD site; columns map 1-to-1 to terraform.tfvars fields
      Sheet 2 "Constants" — shared values that don't change per site (subscription, backend, tags)

    Pre-seeded with the example-site (weconnect-qa) values so the format is immediately clear.

    Requires the ImportExcel module. If not installed the script will install it for the current user.

.NOTES
    Run from the AFD/ folder or pass -OutputPath to override the output location.
    To add a new site: open the xlsx and add a row under the existing data in the Sites sheet.
    Column names match the [Excel: <name>] annotations in modules/afd-site/variables.tf.
#>

[CmdletBinding()]
param(
    [string]$OutputPath
)

# Resolve script root reliably whether run via F5, -File, or dot-sourced
if (-not $PSScriptRoot) {
    $scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    $scriptRoot = $PSScriptRoot
}
if (-not $OutputPath) {
    $OutputPath = Join-Path $scriptRoot "intake\AFD-Site-Intake.xlsx"
}

# ── Ensure ImportExcel is available ───────────────────────────────────────────
if (-not (Get-Module -ListAvailable -Name ImportExcel)) {
    Write-Host "ImportExcel module not found. Installing for current user..." -ForegroundColor Yellow
    Install-Module ImportExcel -Scope CurrentUser -Force -Repository PSGallery
}
Import-Module ImportExcel -ErrorAction Stop

# ── Ensure output directory exists ────────────────────────────────────────────
$outputDir = Split-Path $OutputPath -Parent
if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
    Write-Host "Created directory: $outputDir" -ForegroundColor Cyan
}

# Remove existing file so Export-Excel creates fresh (avoids sheet merge issues)
if (Test-Path $OutputPath) {
    Remove-Item $OutputPath -Force
    Write-Host "Removed existing file: $OutputPath" -ForegroundColor DarkYellow
}

# ─────────────────────────────────────────────────────────────────────────────
# Sheet 1 — Sites
# One row per AFD site. Add new sites as additional rows.
# Each column name matches the [Excel: <name>] annotation in variables.tf.
# ─────────────────────────────────────────────────────────────────────────────
$sites = [System.Collections.Generic.List[PSCustomObject]]::new()

$sites.Add([PSCustomObject]@{
    # ── Identity ──────────────────────────────────────────────────────────────
    app_name                = "weconnect-qa"
    afd_endpoint            = "dev"        # prod | test | dev | prod-api | test-api | dev-api

    # ── Origin ────────────────────────────────────────────────────────────────
    backend_host_name       = "polite-rock-023aa090f.5.azurestaticapps.net"
    origin_host_header      = "weconnect-qa.jammylab.dev"

    # ── Custom Domain & DNS ───────────────────────────────────────────────────
    custom_domain           = "weconnect-qa.jammylab.dev"
    dns_zone                = "jammylab.dev"
    dns_subdomain           = "weconnect-qa"   # leave blank for apex

    # ── Health Probe ──────────────────────────────────────────────────────────
    health_probe_enabled    = $true
    health_probe_path       = "/healthchecks-api"
    health_probe_method     = "GET"             # HEAD or GET

    # ── ILB / PLS ─────────────────────────────────────────────────────────────
    # ilb_private_ip is documentation only — not a tfvars input.
    # The frontend IP name (AFD-<app_name>) and resource ID are auto-derived
    # by the afd-pls-stack module from app_name + known constants.
    # PREREQUISITE: Create "AFD-weconnect-qa" on FGHA-NorthSouth-internalloadbalancer
    # with this static IP from snet-afd-prod before running terraform apply.
    ilb_private_ip          = "x.x.x.x"    # REVIEW: allocate from network tracker
    pls_request_message     = "AFD"

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes                   = "Example site - WeConnect QA environment"
})

# ── Column widths & formatting ────────────────────────────────────────────────
$sitesExcelParams = @{
    Path          = $OutputPath
    WorksheetName = "Sites"
    AutoSize      = $true
    FreezeTopRow  = $true
    BoldTopRow    = $true
    TableName     = "AFDSites"
    TableStyle    = "Medium9"
    PassThru      = $true
}

$pkg = $sites | Export-Excel @sitesExcelParams

$ws = $pkg.Workbook.Worksheets["Sites"]

# Add a REVIEW comment to the ilb_private_ip header cell
$nameColIdx = ($sites[0].PSObject.Properties.Name).IndexOf("ilb_private_ip") + 1
if ($nameColIdx -gt 0) {
    $headerCell = $ws.Cells[1, $nameColIdx]
    $headerCell.AddComment("REVIEW: Allocate from network tracker before apply. NOT a tfvars input - documentation only. Module auto-derives AFD-<app_name> as the frontend IP name.", "AFD Module") | Out-Null
}

# ─────────────────────────────────────────────────────────────────────────────
# Sheet 2 — Constants
# Shared values that apply to every site. Update once when the environment changes.
# ─────────────────────────────────────────────────────────────────────────────
$constants = @(
    [PSCustomObject]@{ Setting = "subscription_id";              Value = "a1b2c3d4-1111-4000-8000-111111111111"; Notes = "sub-JLB-hub" }
    [PSCustomObject]@{ Setting = "backend_resource_group_name";  Value = "rg-JLB-Hub-TerraformState";           Notes = "Terraform state storage RG" }
    [PSCustomObject]@{ Setting = "backend_storage_account_name"; Value = "stshchubterraform";                   Notes = "Terraform state storage account" }
    [PSCustomObject]@{ Setting = "backend_container_name";       Value = "tfstate";                             Notes = "Blob container" }
    [PSCustomObject]@{ Setting = "backend_state_key";            Value = "afd/terraform.tfstate";               Notes = "Terraform state key — shared for all AFD sites" }
    [PSCustomObject]@{ Setting = "afd_profile_name";             Value = "fd-JLB-Hub-FrontDoor";                Notes = "Existing AFD profile - do not change" }
    [PSCustomObject]@{ Setting = "afd_resource_group";           Value = "rg-JLB-Hub-FrontDoor";                Notes = "AFD + WAF policy resource group" }
    [PSCustomObject]@{ Setting = "dns_zone_rg";                  Value = "rg-JLB-Hub-Public_DNS_Zones";         Notes = "DNS zone resource group" }
    [PSCustomObject]@{ Setting = "ilb_rg";                       Value = "rg-network-prod";                     Notes = "NorthSouth ILB resource group" }
    [PSCustomObject]@{ Setting = "ilb_name";                     Value = "FGHA-NorthSouth-internalloadbalancer"; Notes = "Existing NorthSouth ILB" }
    [PSCustomObject]@{ Setting = "ilb_backend_pool";             Value = "FGHA-NorthSOuth-ILB-snet-afd-prod-backend"; Notes = "Existing backend pool" }
    [PSCustomObject]@{ Setting = "ilb_frontend_ip_naming";      Value = "AFD-<app_name>";                      Notes = "Auto-derived by afd-pls-stack module - pre-create on ILB with this name" }
    [PSCustomObject]@{ Setting = "vnet_name";                    Value = "vnet-hub-prod-eus2";                   Notes = "Hub VNet" }
    [PSCustomObject]@{ Setting = "internal_subnet";              Value = "snet-afd-prod";                   Notes = "PLS NAT + ILB frontend IP subnet" }
    [PSCustomObject]@{ Setting = "pls_resource_group";           Value = "rg-JLB-Hub-FrontDoor";                Notes = "PLS resource group" }
    [PSCustomObject]@{ Setting = "tag_app_owner";                Value = "UGd-org:SHC.IT.Infra";                Notes = "Standard tag" }
    [PSCustomObject]@{ Setting = "tag_application";              Value = "Front Door";                           Notes = "Standard tag" }
    [PSCustomObject]@{ Setting = "tag_environment";              Value = "Hub";                                  Notes = "Standard tag" }
    [PSCustomObject]@{ Setting = "tag_purpose";                  Value = "Public web application CDN, WAF, and gateway"; Notes = "Standard tag" }
)

$constantsExcelParams = @{
    ExcelPackage  = $pkg
    WorksheetName = "Constants"
    AutoSize      = $true
    FreezeTopRow  = $true
    BoldTopRow    = $true
    TableName     = "AFDConstants"
    TableStyle    = "Medium2"
    PassThru      = $true
}

$pkg = $constants | Export-Excel @constantsExcelParams

# ── Save and close ────────────────────────────────────────────────────────────
Close-ExcelPackage $pkg -Show:$false

Write-Host ""
Write-Host "Excel intake sheet created:" -ForegroundColor Green
Write-Host "  $OutputPath" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Open the file and add new site rows to the 'Sites' sheet."
Write-Host "  2. For each new site, copy deployments/example-site/ to deployments/<site-name>/."
Write-Host "  3. Fill in terraform.tfvars from the matching row in the sheet."
Write-Host "  4. Pre-create the ILB frontend IP (AFD-<app_name>) before terraform apply."
