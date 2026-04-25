# Define Peer Sets
$peerSets = @(
    @{
        SpokeSub   = "698a1ef1-a61f-4598-b28b-f1fb73c39e51"
        SpokeRG    = "rg-network-dev"
        SpokeVnet  = "vnet-spoke-dev-eus2"
        HubSub     = "a1b2c3d4-1111-4000-8000-111111111111"
        HubRG      = "rg-JLB-Hub-Bastion-Temp"
        HubVnet    = "vnet-JLB-Hub-Bastion-Temp-Network-Spoke"
    },
    @{
        SpokeSub   = "d4e5f6a7-4444-4000-8000-444444444444"
        SpokeRG    = "rg-network-test"
        SpokeVnet  = "vnet-spoke-test-eus2"
        HubSub     = "a1b2c3d4-1111-4000-8000-111111111111"
        HubRG      = "rg-JLB-Hub-Bastion-Temp"
        HubVnet    = "vnet-JLB-Hub-Bastion-Temp-Network-Spoke"
    },
    @{
        SpokeSub   = "1252673f-fe11-43ae-8821-3695c6cf5947"
        SpokeRG    = "rg-JLB-Prod-DATA_PowerBI-Gateway"
        SpokeVnet  = "VM-JLB-Prod-DATA-PowerBI-Gateway-vnet"
        HubSub     = "a1b2c3d4-1111-4000-8000-111111111111"
        HubRG      = "rg-JLB-Hub-Bastion-Temp"
        HubVnet    = "vnet-JLB-Hub-Bastion-Temp-Network-Spoke"
    },
    @{
        SpokeSub   = "238536e4-c07a-4ade-90fd-23196bcd7749"
        SpokeRG    = "rg-JLB-Prod-Data-Network-Spoke"
        SpokeVnet  = "vnet-JLB-Prod-Data-Network-Spoke"
        HubSub     = "a1b2c3d4-1111-4000-8000-111111111111"
        HubRG      = "rg-JLB-Hub-Bastion-Temp"
        HubVnet    = "vnet-JLB-Hub-Bastion-Temp-Network-Spoke"
    },
    @{
        SpokeSub   = "3b997895-f69a-4f92-afbb-94ada84f05dd"
        SpokeRG    = "rg-JLB-Prod-SQL-Network-Spoke"
        SpokeVnet  = "vnet-JLB-Prod-SQL-Network-Spoke"
        HubSub     = "a1b2c3d4-1111-4000-8000-111111111111"
        HubRG      = "rg-JLB-Hub-Bastion-Temp"
        HubVnet    = "vnet-JLB-Hub-Bastion-Temp-Network-Spoke"
    },
    @{
        SpokeSub   = "c3d4e5f6-3333-4000-8000-333333333333"
        SpokeRG    = "rg-JLB-Test-Modern-Network-Spoke"
        SpokeVnet  = "vnet-JLB-Test-Modern-Network-Spoke"
        HubSub     = "a1b2c3d4-1111-4000-8000-111111111111"
        HubRG      = "rg-JLB-Hub-Bastion-Temp"
        HubVnet    = "vnet-JLB-Hub-Bastion-Temp-Network-Spoke"
    },
    @{
        SpokeSub   = "24b5efbb-f6e2-4552-8fea-bfbbae97c64a"
        SpokeRG    = "rg-JLB-Prod-Modern-Network-Spoke"
        SpokeVnet  = "vnet-JLB-Prod-Modern-Network-Spoke"
        HubSub     = "a1b2c3d4-1111-4000-8000-111111111111"
        HubRG      = "rg-JLB-Hub-Bastion-Temp"
        HubVnet    = "vnet-JLB-Hub-Bastion-Temp-Network-Spoke"
    },
    @{
        SpokeSub   = "486aaf41-e4e8-4fd7-8ec2-4df1ab7c9dc5"
        SpokeRG    = "rg-JLB-Prod-IT-Network-Spoke"
        SpokeVnet  = "vnet-JLB-Prod-IT-Network-Spoke"
        HubSub     = "a1b2c3d4-1111-4000-8000-111111111111"
        HubRG      = "rg-JLB-Hub-Bastion-Temp"
        HubVnet    = "vnet-JLB-Hub-Bastion-Temp-Network-Spoke"
    },
    @{
        SpokeSub   = "4479a7ac-f5c9-4b89-add0-b77d9c70db46"
        SpokeRG    = "rg-network-it-prod-w365"
        SpokeVnet  = "vnet-spoke-it-prod-w365-eus2"
        HubSub     = "a1b2c3d4-1111-4000-8000-111111111111"
        HubRG      = "rg-JLB-Hub-Bastion-Temp"
        HubVnet    = "vnet-JLB-Hub-Bastion-Temp-Network-Spoke"
    },
    @{
        SpokeSub   = "64c6a0fb-fb91-49bc-a66b-1c361eb0a868"
        SpokeRG    = "rg-weconnect-prod"
        SpokeVnet  = "vnet-weconnect-prod"
        HubSub     = "a1b2c3d4-1111-4000-8000-111111111111"
        HubRG      = "rg-JLB-Hub-Bastion-Temp"
        HubVnet    = "vnet-JLB-Hub-Bastion-Temp-Network-Spoke"
    }
)

# Create Peerings
foreach ($set in $peerSets) {
    #Write-Host "==> Processing Spoke $($set.SpokeVnet) <=> Hub $($set.HubVnet)" -ForegroundColor Cyan
    try{
        # Spoke ==> Hub
        Write-Host "==> Creating $($set.SpokeVnet) => $($set.HubVnet) Peering..." -ForegroundColor Yellow
        
        az account set --subscription $set.SpokeSub
        az network vnet peering create `
            --name "peer-$($set.SpokeVnet)_to_$($set.HubVnet)" `
            --resource-group $set.SpokeRG `
            --vnet-name $set.SpokeVnet `
            --remote-vnet "/subscriptions/$($set.HubSub)/resourceGroups/$($set.HubRG)/providers/Microsoft.Network/virtualNetworks/$($set.HubVnet)" `
            --allow-forwarded-traffic `
            --allow-vnet-access `
        

        if ($LASTEXITCODE -ne 0) {
            throw "Peering failed for $($set.SpokeVnet)"
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
            --allow-vnet-access `
        

        if ($LASTEXITCODE -ne 0) {
            throw "Peering failed for $($set.HubVnet)"
        }

        Write-Host "==> Finished Spoke $($set.SpokeVnet)" -ForegroundColor Green
    }
    catch{
        Write-Host "Error: $_" -ForegroundColor Red
        continue
    }
}

