# Path to your CSV file
$csvPath = ""

# Import CSV (columns: VNetName, ResourceGroup, SubscriptionID)
$spokeData = Import-Csv -Path $csvPath

# Define Hub defaults
$HubSub = "a1b2c3d4-1111-4000-8000-111111111111"
$HubRG  = "rg-JLB-Hub-Bastion"
$HubVnet = "vnet-JLB-Hub-Bastion-Network-Hub"

# Build peer set array dynamically
$peerSets = foreach ($row in $spokeData) {
    [PSCustomObject]@{
        SpokeSub  = $row.SubscriptionID
        SpokeRG   = $row.ResourceGroup
        SpokeVnet = $row.VNetName
        HubSub    = $HubSub
        HubRG     = $HubRG
        HubVnet   = $HubVnet
    }
}

# Create Peerings
foreach ($set in $peerSets) {
    try {
        # Build base names
        $peerName1 = ("peer-$($set.SpokeVnet)_to_$($set.HubVnet)") + ""
        $peerName2 = ("peer-$($set.HubVnet)_to_$($set.SpokeVnet)") + ""

        # Safe truncate
        if ($peerName1.ToString().Length -gt 80) { $peerName1 = $peerName1.Substring(0,80) }
        if ($peerName2.ToString().Length -gt 80) { $peerName2 = $peerName2.Substring(0,80) }

        # Fix invalid trailing characters
        $peerName1 = $peerName1.TrimEnd('-','.')
        $peerName2 = $peerName2.TrimEnd('-','.')

        # Spoke ==> Hub Creation
        Write-Host "==> Creating $($set.SpokeVnet) => $($set.HubVnet) Peering..." -ForegroundColor Yellow
        az account set --subscription $set.SpokeSub
        az network vnet peering create `
            --name $peerName1 `
            --resource-group $set.SpokeRG `
            --vnet-name $set.SpokeVnet `
            --remote-vnet "/subscriptions/$($set.HubSub)/resourceGroups/$($set.HubRG)/providers/Microsoft.Network/virtualNetworks/$($set.HubVnet)" `
            --allow-forwarded-traffic `
            --allow-vnet-access

        if ($LASTEXITCODE -ne 0) {
            throw "Peering failed for $($set.SpokeVnet)"
        }

        # Hub ==> Spoke Creation
        Write-Host "==> Creating $($set.HubVnet) => $($set.SpokeVnet) Peering..." -ForegroundColor Yellow
        az account set --subscription $set.HubSub
        az network vnet peering create `
            --name $peerName2 `
            --resource-group $set.HubRG `
            --vnet-name $set.HubVnet `
            --remote-vnet "/subscriptions/$($set.SpokeSub)/resourceGroups/$($set.SpokeRG)/providers/Microsoft.Network/virtualNetworks/$($set.SpokeVnet)" `
            --allow-forwarded-traffic `
            --allow-vnet-access

        if ($LASTEXITCODE -ne 0) {
            throw "Peering failed for $($set.HubVnet)"
        }

        Write-Host "==> Finished Spoke $($set.SpokeVnet)" -ForegroundColor Green
    }
    catch {
        Write-Host "Error: $_" -ForegroundColor Red
        continue
    }
}
