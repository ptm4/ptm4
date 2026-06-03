<#
.SYNOPSIS
    Short-name wrapper around Get-LeetifyStats.ps1.

.DESCRIPTION
    Forwards all arguments to Get-LeetifyStats.ps1 in the same directory.
    See Get-Help .\Get-LeetifyStats.ps1 -Full for full parameter docs.
#>
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]]$Args
)

$target = Join-Path -Path $PSScriptRoot -ChildPath 'Get-LeetifyStats.ps1'
& $target @Args
