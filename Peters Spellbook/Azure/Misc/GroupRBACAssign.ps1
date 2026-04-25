$login = Read-Host "Have you already run 'az login'? (y/n)"

if ($login.ToLower() -ne 'y') {
    az login | Out-Null
}
#Made a change
# Get group name
$groupName = Read-Host "Enter Azure AD group display name"

# Grab groupID
$groupID = az ad group show --group "$groupName" --query id -o tsv 2>$null

if (-not $groupID) {
    Write-Error "Group '$groupName' not found. Check the display name and try again."
    exit 1
}

Write-Host "Group resolved: $groupName ($groupID)"

# Grab roles
$roles = @()
do {
    $role = Read-Host "Enter role name (press Enter when done)"
    if ($role) {
        $roles += $role
    }
} while ($role)

if ($roles.Count -eq 0) {
    Write-Error "No roles provided."
    exit 1
}

# Grab subscriptions
$subs = @()
do {
    $sub = Read-Host "Enter subscription NAME or ID (press Enter when done)"
    if ($sub) {
        $subID = az account show --subscription "$sub" --query id -o tsv 2>$null
        if ($subID) {
            $subs += $subID
            Write-Host "Subscription resolved: $sub ($subID)"
        } else {
            Write-Warning "Subscription '$sub' not found, skipping."
        }
    }
} while ($sub)

if ($subs.Count -eq 0) {
    Write-Error "No valid subscriptions provided."
    exit 1
}

# Assign roles
foreach ($subID in $subs) {

    az account set --subscription $subID | Out-Null

    foreach ($role in $roles) {
        Write-Host "Assigning '$role' to '$groupName' on subscription $subID"

        az role assignment create --assignee $groupID --role "$role"  --scope "/subscriptions/$subID"            
    }
}


