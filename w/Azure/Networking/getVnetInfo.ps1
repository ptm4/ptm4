# Requires: az login

# Define your VNet -> Subscription mapping
$vnetMap = @"
vnet-JLB-Lab-Frank-Network-Spoke,sub-JLB-Lab-FRobertson
vnet-JLB-Lab-LFS-Network-Spoke,sub-JLB-Lab-LFS
vnet-JLB-Test-IT-Network-Spoke,sub-JLB-Test-IT
vnet-JLB-Dev-ELMER-Client-Network-Spoke,sub-JLB-Dev-ELMER-Client
vnet-JLB-Dev-ELMER-Recruitment-Network-Spoke,sub-JLB-Dev-ELMER-Recruitment
vnet-JLB-Dev-ELMER-WeConnect-Network-Spoke,sub-JLB-Dev-ELMER-WeConnect
vnet-weconnect-dev,sub-JLB-Dev-ELMER-WeConnect
vnet-JLB-Test-Lab-Network-Spoke,sub-JLB-Test-lab
vnet-JLB-Test-SQL-Network-Spoke,sub-JLB-Test-SQL
vnet-JLB-Prod-Legacy-Network-Spoke,sub-JLB-Prod-Legacy
vnet-JLB-Prod-WeConnect-Network-Spoke,sub-JLB-Prod-WeConnect
vnet-JLB-Test-Data-Network-Spoke,sub-JLB-Test-DATA
vnet-spoke-it-prod-server-eus2,sub-JLB-prod-IT:deprecated
vnet-JLB-Dev-Data-Network-Spoke,sub-JLB-Dev-DATA
vnet-JLB-Test-Legacy-Network-Spoke,sub-JLB-Test-Legacy
vnet-weconnect-qa,sub-JLB-QA-ELMER-WeConnect
vnet-weconnect-uat,sub-JLB-UAT-ELMER-WeConnect
vnet-JLB-DEV-ELMER-Back_Office-Network-Spoke,sub-JLB-Dev-ELMER-Back_Office
vnet-JLB-Hub-SCUS-Veeam-LFS_Connect,sub-JLB-hub
vnet-azure-monitor-svr,sub-JLB-prod-IT:deprecated
vnet-spoke-prod-eus2,sub-JLB-Prod-DATA
vnet-JLB-Dev-ELMER-Platform-Network-Spoke,sub-JLB-Dev-ELMER-Platform
vnet-spoke-dev-eus2,sub-JLB-Dev-DATA
vnet-spoke-test-eus2,sub-JLB-Test-DATA
VM-JLB-Prod-DATA-PowerBI-Gateway-vnet,sub-JLB-Prod-DATA-PowerBI_ETL
vnet-JLB-Prod-Data-Network-Spoke,sub-JLB-Prod-DATA
vnet-JLB-Prod-SQL-Network-Spoke,sub-JLB-Prod-SQL
vnet-JLB-Test-Modern-Network-Spoke,sub-JLB-Test-Modern
vnet-JLB-Prod-Modern-Network-Spoke,sub-JLB-Prod-Modern
vnet-JLB-Prod-IT-Network-Spoke,sub-JLB-Prod-IT
vnet-weconnect-prod,sub-JLB-Prod-ELMER-WeConnect
vnet-spoke-it-prod-w365-eus2,sub-JLB-prod-IT:deprecated
vnet-hub-prod-eus2,sub-JLB-hub
vnet-hub-prod-eus2,sub-JLB-hub
vnet-scripts,sub-JLB-prod-IT:deprecated
vnet-shc-hub-network-eus2-01,sub-JLB-hub
"@

# Prepare output collection
$results = @()

# Split the mapping into lines
$vnetMap.Trim().Split("`n") | ForEach-Object {
    if ($_ -match ",") {
        $parts = $_.Trim().Split(",")
        $vnet = $parts[0].Trim()
        $sub = $parts[1].Trim()

        Write-Host "Checking $vnet in subscription $sub ..." -ForegroundColor Cyan
        
        # Set subscription context
        az account set --subscription $sub | Out-Null

        # Get subscription ID
        $subId = az account show --query id -o tsv

        # Get the resource group for the VNet
        $rg = az network vnet list --query "[?name=='$vnet'].resourceGroup" -o tsv

        if ($rg) {
            $results += [PSCustomObject]@{
                VNetName       = $vnet
                ResourceGroup  = $rg
                SubscriptionID = $subId
            }
        } else {
            $results += [PSCustomObject]@{
                VNetName       = $vnet
                ResourceGroup  = "NOT_FOUND"
                SubscriptionID = $subId
            }
        }
    }
}

# Export or show the results
$results | Format-Table
# Or save to CSV
$results | Export-Csv -Path ./VNetInfo.csv -NoTypeInformation
