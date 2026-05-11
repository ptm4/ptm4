[CmdletBinding()]
param(
    [string]$SubscriptionId    = $env:SUBSCRIPTION_ID,
    [string]$ResourceGroup     = $env:RESOURCE_GROUP,
    [string]$AmplsName         = $env:AMPLS_NAME,
    [string]$AmplsQueryMode    = $env:AMPLS_QUERY_ACCESS_MODE,
    [string]$AmplsIngestMode   = $env:AMPLS_INGESTION_ACCESS_MODE,
    [string]$PeName             = $env:PE_NAME,
    [string]$PeVnetRg           = $env:PE_VNET_RG,
    [string]$PeVnetName         = $env:PE_VNET_NAME,
    [string]$PeSubnetName       = $env:PE_SUBNET_NAME,
    [string]$LawNames           = $env:LAW_NAMES,
    [string]$LawRg              = $env:LAW_RG,
    [string]$DceNames           = $env:DCE_NAMES,
    [string]$DceRg              = $env:DCE_RG,
    [string]$AppInsightsNames   = $env:APPINSIGHTS_NAMES,
    [string]$AppInsightsRg      = $env:APPINSIGHTS_RG
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Location          = "eastus2"
$HubSubscriptionId = "a1b2c3d4-1111-4000-8000-111111111111"
$DnsZoneRg         = "rg-JLB-Hub-Private_Azure_DNS_Zones"
$Tags              = @("Enviornment=prod", "App Owner=Infra", "Purpose=AMPLS", "Application=Private Networking")
$TagArgs           = $Tags -join " "

$DnsZones = @(
    "privatelink.monitor.azure.com"
    "privatelink.ods.opinsights.azure.com"
    "privatelink.oms.opinsights.azure.com"
    "privatelink.blob.core.windows.net"
    "privatelink.agentsvc.azure-automation.net"
)

function Write-Log  { param([string]$Message); Write-Host "[INFO] $(Get-Date -Format 'HH:mm:ss') $Message" }
function Write-Warn { param([string]$Message); Write-Warning "[WARN] $(Get-Date -Format 'HH:mm:ss') $Message" }

Write-Log "Setting subscription: $SubscriptionId"
az account set --subscription $SubscriptionId

Write-Log "Ensuring resource group: $ResourceGroup"
az group create --name $ResourceGroup --location $Location --tags $TagArgs --output none

Write-Log "Creating AMPLS: $AmplsName"
az monitor private-link-scope create --name $AmplsName --resource-group $ResourceGroup --tags $TagArgs --output none

Write-Log "Setting AMPLS access modes"
az monitor private-link-scope update --name $AmplsName --resource-group $ResourceGroup --query-access-mode $AmplsQueryMode --ingestion-access-mode $AmplsIngestMode --output none

$AmplsId = az monitor private-link-scope show --name $AmplsName --resource-group $ResourceGroup --query id -o tsv
Write-Log "AMPLS ID: $AmplsId"

$SubnetId = az network vnet subnet show --name $PeSubnetName --vnet-name $PeVnetName --resource-group $PeVnetRg --query id -o tsv

Write-Log "Creating Private Endpoint: $PeName"
az network private-endpoint create --name $PeName --resource-group $ResourceGroup --location $Location --subnet $SubnetId --private-connection-resource-id $AmplsId --group-id "azuremonitor" --connection-name "$PeName-conn" --tags $TagArgs --output none

$PeId = az network private-endpoint show --name $PeName --resource-group $ResourceGroup --query id -o tsv
Write-Log "Private Endpoint ID: $PeId"

Write-Log "Switching to hub subscription for DNS operations: $HubSubscriptionId"
az account set --subscription $HubSubscriptionId

$VnetId = az network vnet show --name $PeVnetName --resource-group $PeVnetRg --query id -o tsv

foreach ($Zone in $DnsZones) {
    $ZoneExists = az network private-dns zone show --name $Zone --resource-group $DnsZoneRg --query name -o tsv 2>$null
    if (-not $ZoneExists) {
        Write-Log "Creating DNS zone: $Zone"
        az network private-dns zone create --name $Zone --resource-group $DnsZoneRg --tags $TagArgs --output none
    } else {
        Write-Log "DNS zone exists, skipping: $Zone"
    }

    $LinkName = "$AmplsName-$($Zone -replace '\.', '-')-link"
    $LinkExists = az network private-dns link vnet show --name $LinkName --resource-group $DnsZoneRg --zone-name $Zone --query name -o tsv 2>$null
    if (-not $LinkExists) {
        Write-Log "Linking DNS zone $Zone to VNet $PeVnetName"
        az network private-dns link vnet create --name $LinkName --resource-group $DnsZoneRg --zone-name $Zone --virtual-network $VnetId --registration-enabled false --tags $TagArgs --output none
    } else {
        Write-Log "DNS VNet link exists, skipping: $LinkName"
    }
}

Write-Log "Creating DNS zone group on PE"
$ZoneConfigArgs = @()
foreach ($Zone in $DnsZones) {
    $ZoneConfigArgs += "--zone-configs"
    $ZoneConfigArgs += "name=$($Zone -replace '\.', '-') private-dns-zone=/subscriptions/$HubSubscriptionId/resourceGroups/$DnsZoneRg/providers/Microsoft.Network/privateDnsZones/$Zone"
}
az network private-endpoint dns-zone-group create --endpoint-name $PeName --name "ampls-dns-zone-group" --resource-group $ResourceGroup --subscription $SubscriptionId @ZoneConfigArgs --output none

Write-Log "Switching back to target subscription: $SubscriptionId"
az account set --subscription $SubscriptionId

function Add-ScopedResource {
    param([string]$ResourceId, [string]$ResourceName)
    $LinkName = ($ResourceName.ToLower() -replace '[^a-z0-9-]', '').Substring(0, [Math]::Min(60, $ResourceName.Length))
    Write-Log "Linking $ResourceName to $AmplsName"
    az monitor private-link-scope scoped-resource create --linked-resource $ResourceId --name $LinkName --resource-group $ResourceGroup --scope-name $AmplsName --output none
}

if ($LawNames -and $LawNames -ne "none") {
    foreach ($Law in $LawNames.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)) {
        $LawId = az monitor log-analytics workspace show --workspace-name $Law --resource-group $LawRg --query id -o tsv 2>$null
        if ($LawId) { Add-ScopedResource -ResourceId $LawId -ResourceName $Law }
        else { Write-Warn "LAW '$Law' not found in '$LawRg' - skipping" }
    }
}

if ($DceNames -and $DceNames -ne "none") {
    foreach ($Dce in $DceNames.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)) {
        $DceId = az monitor data-collection endpoint show --name $Dce --resource-group $DceRg --query id -o tsv 2>$null
        if ($DceId) { Add-ScopedResource -ResourceId $DceId -ResourceName $Dce }
        else { Write-Warn "DCE '$Dce' not found in '$DceRg' - skipping" }
    }
}

if ($AppInsightsNames -and $AppInsightsNames -ne "none") {
    foreach ($Ai in $AppInsightsNames.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)) {
        $AiId = az monitor app-insights component show --app $Ai --resource-group $AppInsightsRg --query id -o tsv 2>$null
        if ($AiId) { Add-ScopedResource -ResourceId $AiId -ResourceName $Ai }
        else { Write-Warn "App Insights '$Ai' not found in '$AppInsightsRg' - skipping" }
    }
}

Write-Log "Deployment complete - AMPLS: $AmplsName | PE: $PeName | ID: $PeId"