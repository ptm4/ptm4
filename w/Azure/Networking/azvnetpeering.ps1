<#VNET PEER
az network vnet peering create `
  --name 'peer-JLB-Dev-ELMER-Platform-Spoke_to_Hub' `
  --resource-group 'rg-JLB-Dev-ELMER-Platform-Network-Spoke' `
  --vnet-name 'vnet-JLB-Dev-ELMER-Platform-Network-Spoke' `
  --remote-vnet '/subscriptions/a1b2c3d4-1111-4000-8000-111111111111/resourceGroups/rg-network-prod/providers/Microsoft.Network/virtualNetworks/vnet-hub-prod-eus2' `
  --allow-forwarded-traffic `
  --allow-vnet-access `
  --use-remote-gateways `

az network vnet peering create `
  --name 'peer-Hub_to_SHC-Dev-ELMER-Platform-Spoke' `
  --resource-group 'rg-network-prod' `
  --vnet-name 'vnet-hub-prod-eus2' `
  --remote-vnet '/subscriptions/a8de1922-6b87-4c86-8fd6-98fc2ae45289/resourceGroups/rg-JLB-Dev-ELMER-Platform-Network-Spoke/providers/Microsoft.Network/virtualNetworks/vnet-JLB-Dev-ELMER-Platform-Network-Spoke' `
  --allow-forwarded-traffic `
  --allow-gateway-transit `
  --allow-vnet-access `
#>
<#SUBNET PEER  
  az network vnet peering create `
  --name 'peer-JLB-Dev-ELMER-Platform-Spoke_to_Hub' `
  --resource-group 'rg-JLB-Dev-ELMER-Platform-Network-Spoke' `
  --vnet-name 'vnet-JLB-Dev-ELMER-Platform-Network-Spoke' `
  --remote-vnet '/subscriptions/a1b2c3d4-1111-4000-8000-111111111111/resourceGroups/rg-network-prod/providers/Microsoft.Network/virtualNetworks/vnet-hub-prod-eus2' `
  --allow-forwarded-traffic `
  --allow-vnet-access `
  --peer-complete-vnet false `
  --local-subnet-names 'snet-JLB-DEV-ELMER-Platform-Default' `
  --remote-subnet-names 'AzureBastionSubnet' `
  

az network vnet peering create `
  --name 'peer-Hub_to_SHC-Dev-ELMER-Platform-Spoke' `
  --resource-group 'rg-network-prod' `
  --vnet-name 'vnet-hub-prod-eus2' `
  --remote-vnet '/subscriptions/a8de1922-6b87-4c86-8fd6-98fc2ae45289/resourceGroups/rg-JLB-Dev-ELMER-Platform-Network-Spoke/providers/Microsoft.Network/virtualNetworks/vnet-JLB-Dev-ELMER-Platform-Network-Spoke' `
  --allow-forwarded-traffic `
  --allow-gateway-transit `
  --allow-vnet-access `
  --peer-complete-vnet false `
  --local-subnet-names 'AzureBastionSubnet' `
  --remote-subnet-names 'snet-JLB-DEV-ELMER-Platform-Default' `
  
  #>




# Create Peerings
foreach ($set in $peerSets) {
    Write-Host "==> Processing Spoke $($set.SpokeVnet) <=> Hub $($set.HubVnet)" -ForegroundColor Cyan

    try {
        # Spoke ==> Hub
        Write-Host "==> Creating $($set.SpokeVnet) => $($set.HubVnet) Peering..." -ForegroundColor Yellow
        az account set --subscription $set.SpokeSub
        az network vnet peering create `
            --name "peer-$($set.SpokeVnet)_to_$($set.HubVnet)" `
            --resource-group $set.SpokeRG `
            --vnet-name $set.SpokeVnet `
            --remote-vnet "/subscriptions/$($set.HubSub)/resourceGroups/$($set.HubRG)/providers/Microsoft.Network/virtualNetworks/$($set.HubVnet)" `
            --allow-forwarded-traffic `
            --allow-vnet-access

        if ($LASTEXITCODE -ne 0) {
            throw "Spoke → Hub peering failed for $($set.SpokeVnet)"
        }

        # Hub ==> Spoke
        Write-Host "==> Creating $($set.HubVnet) => $($set.SpokeVnet) Peering..." -ForegroundColor Yellow
        az account set --subscription $set.HubSub
        az network vnet peering create `
            --name "peer-$($set.HubVnet)_to_$($set.SpokeVnet)" `
            --resource-group $set.HubRG `
            --vnet-name $set.HubVnet `
            --remote-vnet "/subscriptions/$($set.SpokeSub)/resourceGroups/$($set.SpokeRG)/providers/Microsoft.Network/virtualNetworks/$($set.SpokeVnet)" `
            --allow-forwarded-traffic `
            --allow-vnet-access

        if ($LASTEXITCODE -ne 0) {
            throw "Peering failed for $($set.SpokeVnet)"
        }

        Write-Host "==> Finished Spoke $($set.SpokeVnet)" -ForegroundColor Green
    }
    catch {
        Write-Host "!! ERROR: $_" -ForegroundColor Red
        continue   # go to next peer set, don’t stop script
    }
}

Write-Host "==> All peer sets processed (errors shown above if any)." -ForegroundColor Cyan
