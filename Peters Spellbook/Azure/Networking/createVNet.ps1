    $login = Read-Host "Have you already run 'az login'? (y/n)"

    if ($login.ToLower() -ne 'y') {
        az login | Out-Null
    }
#Params
    $subId = "c3d4e5f6-3333-4000-8000-333333333333"

    if ($subId -eq "") {
        $subId = Read-Host "Enter subId"
    }
    #Set Context
    az account set --subscription $subId

    $resourceGroup = "rg-JLB-Test-Modern-Network-Spoke"
    if ($resourceGroup -eq "") {
        $resourceGroup = Read-Host "Enter resourceGroup"
    }

    #Hub defaults
    $HubSub  = "a1b2c3d4-1111-4000-8000-111111111111"
    $HubRG   = "rg-JLB-Hub-Bastion"
    $HubVnet = "vnet-JLB-Hub-Bastion-Network-Hub"

    $vnets = @(
        @{vnetName="vnet-JLB-Test-Modern-Network-Spoke_Credentialing_Common";subnetName="snet-JLB-Test-Modern-Network-Spoke_Credentialing_Common";vnetAddressPrefix="10.10.64.0/23";subnetAddressPrefix="10.10.64.0/27"},
        @{vnetName="vnet-JLB-Test-Modern-Network-Spoke_Credentialing_Eval";subnetName="snet-JLB-Test-Modern-Network-Spoke_Credentialing_Eval";vnetAddressPrefix="10.10.66.0/23";subnetAddressPrefix="10.10.66.0/27"},
        @{vnetName="vnet-JLB-Test-Modern-Network-Spoke_Credentialing_Req";subnetName="snet-JLB-Test-Modern-Network-Spoke_Credentialing_Req";vnetAddressPrefix="10.10.68.0/23";subnetAddressPrefix="10.10.68.0/27"}
    )
#Functions for Links
    function New-VHubLink {
        param($vnet, $resourceGroup, $HubSub, $subId)

        Write-Host "Linking $($vnet.vnetName) to vHub..."
        az account set --subscription $subId
        $vnetId = az network vnet show --name $vnet.vnetName --resource-group $resourceGroup --query id -o tsv
        az account set --subscription $HubSub
        az network vhub connection create --name "vhub-$($vnet.vnetName)" --vhub-name "vhub-jlb-hub-network-eus2" --resource-group "rg-shc-hub-network-eus2-01" --remote-vnet $vnetId

        if ($LASTEXITCODE -ne 0) {
            throw "vhub link failed for $($vnet.vnetName)"
        }
    }

    function New-BastionPeering {
        param($vnet, $SpokeSub, $SpokeRG, $HubSub, $HubRG, $HubVnet)

        $peerName1 = "peer-$($vnet.vnetName)_to_$HubVnet"
        $peerName2 = "peer-$HubVnet_to_$($vnet.vnetName)"

        if ($peerName1.Length -gt 80) { $peerName1 = $peerName1.Substring(0,80) }
        if ($peerName2.Length -gt 80) { $peerName2 = $peerName2.Substring(0,80) }

        $peerName1 = $peerName1.TrimEnd('-','.')
        $peerName2 = $peerName2.TrimEnd('-','.')

        try {
            # Spoke => Hub
            Write-Host "Creating peering $($vnet.vnetName) => $HubVnet..."
            az account set --subscription $SpokeSub
            az network vnet peering create --name $peerName1 --resource-group $SpokeRG --vnet-name $vnet.vnetName --remote-vnet "/subscriptions/$HubSub/resourceGroups/$HubRG/providers/Microsoft.Network/virtualNetworks/$HubVnet" --allow-forwarded-traffic --allow-vnet-access

            if ($LASTEXITCODE -ne 0) { throw "Spoke=>Hub peering failed for $($vnet.vnetName)" }

            # Hub => Spoke
            Write-Host "Creating peering $HubVnet => $($vnet.vnetName)..."
            az account set --subscription $HubSub
            az network vnet peering create --name $peerName2 --resource-group $HubRG --vnet-name $HubVnet --remote-vnet "/subscriptions/$SpokeSub/resourceGroups/$SpokeRG/providers/Microsoft.Network/virtualNetworks/$($vnet.vnetName)" --allow-forwarded-traffic --allow-vnet-access

            if ($LASTEXITCODE -ne 0) { throw "Hub=>Spoke peering failed for $($vnet.vnetName)" }

            Write-Host "Peering complete for $($vnet.vnetName)" -ForegroundColor Green
        }
        catch {
            Write-Host "Error: $_" -ForegroundColor Red
        }
    }

#Loop
foreach ($vnet in $vnets) {
    Write-Host "Creating VNet: $($vnet.vnetName)"
    az account set --subscription $subId
    az network vnet create --name $vnet.vnetName --resource-group $resourceGroup --address-prefixes $vnet.vnetAddressPrefix --subnet-name $vnet.subnetName --subnet-prefixes $vnet.subnetAddressPrefix

    New-VHubLink -vnet $vnet -resourceGroup $resourceGroup -HubSub $HubSub -subId $subId
    New-BastionPeering -vnet $vnet -SpokeSub $subId -SpokeRG $resourceGroup -HubSub $HubSub -HubRG $HubRG -HubVnet $HubVnet
}
