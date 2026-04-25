$login = Read-Host "Have you already run 'az login'? (y/n)"

if ($login.ToLower() -ne 'y') {
    az login | Out-Null
}

$subId = "a1b2c3d4-1111-4000-8000-111111111111"
$rg = "rg-JLB-Hub-Private_Azure_DNS_Zones"
$zones = @(
        "privatelink.azurecr.io",
        "privatelink.eastus2.azurecontainerapps.io"
)

az account set --subscription $subId

foreach ($zone in $zones) {
    Write-Host "Creating Private DNS Zones: $zone"
    az network private-dns zone create --subscription $subId --resource-group $rg --name $zone
}
