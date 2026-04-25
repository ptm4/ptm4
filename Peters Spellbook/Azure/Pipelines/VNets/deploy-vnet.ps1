#region bootstrap
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$configPath = $env:CONFIG_PATH

# Bastion hub values (hardcoded)
$hubSub  = "a1b2c3d4-1111-4000-8000-111111111111"
$hubRG   = "rg-JLB-Hub-Bastion"
$hubVnet = "vnet-JLB-Hub-Bastion-Network-Hub"
#endregion

#region load Excel
if (-not (Get-Module -ListAvailable -Name ImportExcel)) {
    Write-Host "Installing ImportExcel module..."
    Install-Module ImportExcel -Scope CurrentUser -Force -AllowClobber
}
Import-Module ImportExcel

if (-not (Test-Path $configPath)) {
    Write-Host "[FAIL] Config file not found: $configPath"
    exit 1
}

$rows = Import-Excel -Path $configPath
$requiredColumns = @('VNetName','VNetPrefix','SubnetName','SubnetPrefix','ResourceGroup','SubscriptionId','EnableVhub','EnablePeering')

foreach ($col in $requiredColumns) {
    if ($rows[0].PSObject.Properties.Name -notcontains $col) {
        Write-Host "[FAIL] Missing required column: $col"
        exit 1
    }
}

Write-Host "[OK] Excel loaded - $($rows.Count) subnet row(s) found"
#endregion

#region validate rows
$errors = 0
$rowNum = 2

foreach ($row in $rows) {
    foreach ($col in $requiredColumns) {
        if ([string]::IsNullOrWhiteSpace(($row.$col -as [string]))) {
            Write-Host "[FAIL] Row $rowNum - $col is empty"
            $errors++
        }
    }
    $rowNum++
}

if ($errors -gt 0) {
    Write-Host "[FAIL] $errors validation error(s) found. Aborting."
    exit 1
}

Write-Host "[OK] All rows passed validation"
#endregion

#region functions
function Get-PeeringName {
    param([string]$FullName, [int]$MaxLength = 80)
    if ($FullName.Length -le $MaxLength) { return $FullName }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($FullName)
    $hash  = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    $suffix = ($hash | ForEach-Object { $_.ToString('x2') }) -join ''
    $suffix = $suffix.Substring(0, 8)
    return "$($FullName.Substring(0, $MaxLength - 9))-$suffix"
}

function New-VHubLink {
    param($vnet, $resourceGroup, $hubSub, $subId)

    Write-Host "Linking $($vnet.VNetName) to vHub..."

    # Get spoke VNet ID while on spoke sub
    az account set --subscription $subId
    $vnetId = az network vnet show `
        --name $vnet.VNetName `
        --resource-group $resourceGroup `
        --subscription $subId `
        --query id -o tsv

    if ([string]::IsNullOrWhiteSpace($vnetId)) {
        throw "Could not resolve VNet ID for $($vnet.VNetName)"
    }

    Write-Host "Spoke VNet ID: $vnetId"

    # check
    az account set --subscription $hubSub
    $currentSub = az account show --query id -o tsv
    Write-Host "Active subscription: $currentSub"

    if ($currentSub -ne $hubSub) {
        throw "Failed to switch to hub subscription $hubSub"
    }

    az network vhub connection create `
        --name "vhub-$($vnet.VNetName)" `
        --vhub-name "vhub-jlb-hub-network-eus2" `
        --resource-group "rg-shc-hub-network-eus2-01" `
        --remote-vnet $vnetId `
        --subscription $hubSub

    if ($LASTEXITCODE -ne 0) {
        throw "vHub link failed for $($vnet.VNetName)"
    }

    # Swap back to spoke sub for any subsequent operations
    az account set --subscription $subId
}

function New-BastionPeering {
    param($vnet, $SpokeSub, $SpokeRG, $HubSub, $HubRG, $HubVnet)

    $peerName1 = Get-PeeringName "peer-$($vnet.VNetName)_to_$HubVnet"
    $peerName2 = Get-PeeringName "peer-$($HubVnet)_to_$($vnet.VNetName)"

    try {
        Write-Host "Creating peering $($vnet.VNetName) => $HubVnet..."
        az account set --subscription $SpokeSub
        az network vnet peering create `
            --name $peerName1 `
            --resource-group $SpokeRG `
            --vnet-name $vnet.VNetName `
            --remote-vnet "/subscriptions/$HubSub/resourceGroups/$HubRG/providers/Microsoft.Network/virtualNetworks/$HubVnet" `
            --allow-forwarded-traffic `
            --allow-vnet-access

        if ($LASTEXITCODE -ne 0) { throw "Spoke=>Hub peering failed for $($vnet.VNetName)" }

        Write-Host "Creating peering $HubVnet => $($vnet.VNetName)..."
        az account set --subscription $HubSub
        az network vnet peering create `
            --name $peerName2 `
            --resource-group $HubRG `
            --vnet-name $HubVnet `
            --remote-vnet "/subscriptions/$SpokeSub/resourceGroups/$SpokeRG/providers/Microsoft.Network/virtualNetworks/$($vnet.VNetName)" `
            --allow-forwarded-traffic `
            --allow-vnet-access

        if ($LASTEXITCODE -ne 0) { throw "Hub=>Spoke peering failed for $($vnet.VNetName)" }

        Write-Host "Peering complete for $($vnet.VNetName)"
    }
    catch {
        Write-Host "Error during peering: $_"
        throw
    }
}
#endregion

#region main
$vnetGroups = $rows | Group-Object -Property VNetName

foreach ($group in $vnetGroups) {
    $firstRow      = $group.Group[0]
    $vnetName      = $firstRow.VNetName
    $vnetPrefix    = $firstRow.VNetPrefix
    $resourceGroup = $firstRow.ResourceGroup
    $subId         = $firstRow.SubscriptionId
    $enableVhub    = $firstRow.EnableVhub -eq $true -or $firstRow.EnableVhub -eq 'TRUE'
    $enablePeering = $firstRow.EnablePeering -eq $true -or $firstRow.EnablePeering -eq 'TRUE'

    $vnetObj = @{ VNetName = $vnetName }

    Write-Host ""
    Write-Host "--- Processing VNet: $vnetName ($subId) ---"
    az account set --subscription $subId

    Write-Host "Creating VNet: $vnetName"
    az network vnet create `
        --name $vnetName `
        --resource-group $resourceGroup `
        --address-prefixes $vnetPrefix `
        --subnet-name $firstRow.SubnetName `
        --subnet-prefixes $firstRow.SubnetPrefix `
        --dns-servers 10.200.1.132 10.200.1.133

    if ($LASTEXITCODE -ne 0) { throw "VNet creation failed for $vnetName" }

    foreach ($row in $group.Group | Select-Object -Skip 1) {
        Write-Host "Adding subnet: $($row.SubnetName) ($($row.SubnetPrefix))"
        az network vnet subnet create `
            --vnet-name $vnetName `
            --name $row.SubnetName `
            --address-prefix $row.SubnetPrefix `
            --resource-group $resourceGroup `
            --subscription $subId

        if ($LASTEXITCODE -ne 0) { throw "Subnet creation failed for $($row.SubnetName)" }
    }

    if ($enableVhub) {
        New-VHubLink -vnet $vnetObj -resourceGroup $resourceGroup -hubSub $hubSub -subId $subId
    }

    if ($enablePeering) {
        New-BastionPeering -vnet $vnetObj -SpokeSub $subId -SpokeRG $resourceGroup -HubSub $hubSub -HubRG $hubRG -HubVnet $hubVnet
    }
}

Write-Host ""
Write-Host "All VNet deployments complete."
#endregion