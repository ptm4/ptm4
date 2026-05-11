$login = Read-Host "Have you already run 'az login'? (y/n)"

if ($login.ToLower() -ne 'y') {
    az login | Out-Null
}

$subId = "a1b2c3d4-1111-4000-8000-111111111111"
$rg = "rg-JLB-Hub-Private_Azure_DNS_Zones"
$zone = "privatelink.eastus2.azurecontainerapps.io"

az account set --subscription $subId

$links = az network private-dns link vnet list --resource-group $rg --zone-name $zone --query "[].name" -o tsv

foreach ($link in $links) {
    Write-Host "Deleting VNet link: $link"
    az network private-dns link vnet delete --resource-group $rg --zone-name $zone --name $link --yes
}
