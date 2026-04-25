$jsonFile = "C:\Temp\ClonedPolicies\policy.json"

$jsonContent = Get-Content -Raw -Path $jsonFile
$policyObjects = $jsonContent | ConvertFrom-Json

$mgName = "MG-JLB-LZ"   # Set target management group

foreach ($p in $policyObjects) {

    $displayName = $p.properties.displayName
    $description = $p.properties.description
    $metadata = $p.properties.metadata
    $policyRule = $p.properties.policyRule | ConvertTo-Json -Depth 10 -Compress

    # Generate a safe Name: replace spaces with _, remove invalid chars, limit to 64 chars
    $safeName = ($displayName -replace '[^a-zA-Z0-9_]', '_')
    if ($safeName.Length -gt 64) {
        $safeName = $safeName.Substring(0,64)
    }

    try {
        New-AzPolicyDefinition `
            -Name $safeName `
            -DisplayName $displayName `
            -Description $description `
            -Policy $policyRule `
            -Mode All `
            -Metadata $metadata `
            -ManagementGroupName $mgName   # <-- Deploy to MG

        Write-Host "Created policy: $displayName in $mgName" -ForegroundColor Green
    }
    catch {
        Write-Warning "Failed to create $displayName. $_"
    }
}
