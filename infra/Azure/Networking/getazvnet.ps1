<#
#az login
$csvPath = "C:\Users\nnumbat\Downloads\xl.csv"
$resources = Import-Csv -Path $csvPath

# Initialize results array
$results = @()

foreach ($r in $resources) {
    $resourceName = $r.NAME.Trim()
    $res = az resource list --name $resourceName --query "[0]" -o json | ConvertFrom-Json
    Write-Output $res.id

}

# Display nicely
$results | Format-Table -AutoSize
#>
# Path to CSV (expects header 'NAME')
$csvPath = "C:\Users\nnumbat\Downloads\xl.csv"
$resources = Import-Csv -Path $csvPath

# Initialize results array
$results = @()

foreach ($r in $resources) {
    $resourceName = $r.NAME.Trim()

    # Get the resource
    $res = az resource list --name $resourceName --query "[0]" -o json | ConvertFrom-Json
    if (-not $res) { continue }  # skip if resource not found

    $vnetId = $null

    # Case 1: Resource is a VNet
    if ($res.type -eq "Microsoft.Network/virtualNetworks") {
        $vnetId = $res.id
    }
    # Case 2: Resource is a Private Endpoint
    elseif ($res.type -eq "Microsoft.Network/privateEndpoints") {
        $subnetId = $res.properties.ipConfigurations[0].properties.subnet.id
        if ($subnetId) {
            $vnetId = ($subnetId -split "/subnets/")[0]
        }
    }
    # Case 3: Resource may have associated private endpoints (like Storage Account)
    else {
        # List private endpoints connected to this resource
        $peList = az network private-endpoint list -o json | ConvertFrom-Json

        # Filter for endpoints that have connections and match this resource
        $matchingPE = $peList | Where-Object {
            $_.properties.privateLinkServiceConnections -ne $null -and
            ($_.properties.privateLinkServiceConnections.properties.privateLinkServiceId -contains $res.id)
        }

        if ($matchingPE.Count -gt 0) {
            $subnetId = $matchingPE[0].properties.ipConfigurations[0].properties.subnet.id
            if ($subnetId) {
                $vnetId = ($subnetId -split "/subnets/")[0]
            }
        }
    }

    # Save results
    $results += [PSCustomObject]@{
        ResourceName = $resourceName
        ResourceType = $res.type
        ResourceId   = $res.id
        VNetId       = $vnetId
    }
}

# Display nicely
Export-Csv $results -path "C:\Users\nnumbat\Downloads\output.csv"
