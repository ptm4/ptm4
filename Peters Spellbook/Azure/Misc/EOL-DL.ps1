$login = Read-Host "Have you already run 'Connect-ExchangeOnline'? (y/n)"

if ($login.ToLower() -ne 'y') {
    Connect-ExchangeOnline | Out-Null
}

New-DistributionGroup -Name "DLName" -PrimarySmtpAddress "email@jammylab.com" -Type Distribution

$members = @(
    "EX1",
    "EX2"
)

foreach ($name in $members) {
    $user = Get-EXORecipient -Filter "DisplayName -eq '$name'" -ErrorAction SilentlyContinue
    if ($user) {
        Add-DistributionGroupMember -Identity "email@jammylab.com" -Member $user.PrimarySmtpAddress
        Write-Host "Added $name"
    } else {
        Write-Host "NOT FOUND: $name" -ForegroundColor Red
    }
}