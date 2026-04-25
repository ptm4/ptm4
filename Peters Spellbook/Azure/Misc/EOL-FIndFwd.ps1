$login = Read-Host "Have you already run 'Connect-ExchangeOnline'? (y/n)"

if ($login.ToLower() -ne 'y') {
    Connect-ExchangeOnline | Out-Null
}
$email = Read-Host "Enter email or press Enter to search by display name"

if ([string]::IsNullOrWhiteSpace($email)) {
    $name = Read-Host "Enter display name"
    $user = Get-EXORecipient -Filter "DisplayName -eq '$name'" -ErrorAction SilentlyContinue

    if (-not $user) { Write-Warning "No recipient found with display name '$name'"; return }
    if ($user.Count -gt 1) { Write-Warning "Multiple recipients found. Please be more specific."; $user | Select-Object DisplayName, PrimarySmtpAddress; return }

    $identity = $user.PrimarySmtpAddress
} else {
    $identity = $email
}

Get-Mailbox -Identity $identity | Select-Object DisplayName, ForwardingAddress, ForwardingSmtpAddress, DeliverToMailboxAndForward