<#
.SYNOPSIS
    Pulls Counter-Strike 2 stats from the Leetify Public API and writes a JSON export.

.DESCRIPTION
    Fetches a player profile and recent match details from the Leetify Public CS API
    (https://api-public.cs-prod.leetify.com) and writes the combined result as a single
    JSON file. Auth is via the LEETIFY_API_KEY environment variable or the -ApiKey
    parameter. The API key is sent as `Authorization: Bearer <key>` per the OpenAPI spec.

    Endpoints used (discovered from the public OpenAPI document):
        GET /api-key/validate           - validate key (optional)
        GET /v3/profile                 - player profile, ranks, ratings, recent matches
        GET /v3/profile/matches         - full per-match detail array for the player

.PARAMETER SteamId
    Steam64 ID of the player (required).

.PARAMETER MatchCount
    Maximum number of recent matches to include in the output. Default 25.

.PARAMETER OutputPath
    Path to the JSON file to write. Default .\leetify-export.json.

.PARAMETER IncludeMatchDetails
    When set (default true), pulls /v3/profile/matches for full per-match detail.
    When -IncludeMatchDetails:$false, only the summary recent_matches from the profile
    response is included.

.PARAMETER ApiKey
    Optional API key. Overrides the LEETIFY_API_KEY environment variable.

.EXAMPLE
    .\Get-LeetifyStats.ps1 -SteamId 76561197969209908

.EXAMPLE
    .\Get-LeetifyStats.ps1 -SteamId 76561197969209908 -MatchCount 10 -OutputPath C:\tmp\me.json -Verbose

.EXAMPLE
    .\Get-LeetifyStats.ps1 -SteamId 76561197969209908 -IncludeMatchDetails:$false
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SteamId,

    [Parameter()]
    [int]$MatchCount = 25,

    [Parameter()]
    [string]$OutputPath = '.\leetify-export.json',

    [Parameter()]
    [switch]$IncludeMatchDetails = $true,

    [Parameter()]
    [string]$ApiKey
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$BaseUrl = 'https://api-public.cs-prod.leetify.com'

if (-not $ApiKey) {
    $ApiKey = $env:LEETIFY_API_KEY
}
if (-not $ApiKey) {
    Write-Error "No API key provided. Set the LEETIFY_API_KEY environment variable or pass -ApiKey. Get a key at https://leetify.com/app/developer."
    exit 1
}

function Invoke-LeetifyRequest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Path,
        [hashtable]$Query
    )

    $uri = "$BaseUrl$Path"
    if ($Query -and $Query.Count -gt 0) {
        $pairs = foreach ($k in $Query.Keys) {
            if ($null -ne $Query[$k] -and "$($Query[$k])" -ne '') {
                "{0}={1}" -f [uri]::EscapeDataString($k), [uri]::EscapeDataString("$($Query[$k])")
            }
        }
        if ($pairs) { $uri = "$uri`?" + ($pairs -join '&') }
    }

    $headers = @{
        Authorization = "Bearer $ApiKey"
        Accept        = 'application/json'
    }

    $maxAttempts = 3
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        Write-Verbose "GET $uri (attempt $attempt of $maxAttempts)"
        try {
            return Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -ErrorAction Stop
        }
        catch {
            $resp = $_.Exception.Response
            $status = $null
            if ($resp) { $status = [int]$resp.StatusCode }

            if ($status -eq 401 -or $status -eq 403) {
                Write-Error "Authentication failed ($status) calling $Path. Check that LEETIFY_API_KEY (or -ApiKey) is set to a valid key from https://leetify.com/app/developer."
                throw
            }

            if ($status -eq 429 -and $attempt -lt $maxAttempts) {
                $delay = 5
                try {
                    $retryAfter = $resp.Headers['Retry-After']
                    if ($retryAfter) {
                        $parsed = 0
                        if ([int]::TryParse("$retryAfter", [ref]$parsed) -and $parsed -gt 0) { $delay = $parsed }
                    }
                } catch { }
                Write-Verbose "Rate limited (429). Sleeping ${delay}s before retry."
                Start-Sleep -Seconds $delay
                continue
            }

            if ($status -ge 500 -and $attempt -lt $maxAttempts) {
                Write-Verbose "Server error ($status). Backing off 5s before retry."
                Start-Sleep -Seconds 5
                continue
            }

            throw
        }
    }
}

Write-Verbose "Validating API key against /api-key/validate"
try {
    Invoke-LeetifyRequest -Path '/api-key/validate' | Out-Null
    Write-Verbose "API key valid."
}
catch {
    Write-Verbose "Key validation call did not return cleanly; continuing (some keys may still authorize data endpoints)."
}

Write-Verbose "Fetching profile for Steam64 ID $SteamId"
$profile = Invoke-LeetifyRequest -Path '/v3/profile' -Query @{ steam64_id = $SteamId }

$matches = @()
if ($IncludeMatchDetails) {
    Write-Verbose "Fetching full match history via /v3/profile/matches"
    $all = Invoke-LeetifyRequest -Path '/v3/profile/matches' -Query @{ steam64_id = $SteamId }
    if ($null -ne $all) {
        $sorted = @($all) | Sort-Object -Property finished_at -Descending
        $matches = @($sorted | Select-Object -First $MatchCount)
    }
}
else {
    Write-Verbose "IncludeMatchDetails disabled; using profile.recent_matches summary."
    if ($profile.PSObject.Properties.Name -contains 'recent_matches' -and $profile.recent_matches) {
        $matches = @($profile.recent_matches | Select-Object -First $MatchCount)
    }
}

$export = [ordered]@{
    exportedAt = (Get-Date).ToUniversalTime().ToString('o')
    steamId    = $SteamId
    profile    = $profile
    matches    = $matches
}

$json = $export | ConvertTo-Json -Depth 100
$resolvedPath = $OutputPath
if (-not [System.IO.Path]::IsPathRooted($resolvedPath)) {
    $resolvedPath = Join-Path -Path (Get-Location) -ChildPath $resolvedPath
}
$dir = Split-Path -Path $resolvedPath -Parent
if ($dir -and -not (Test-Path -LiteralPath $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}
$json | Set-Content -LiteralPath $resolvedPath -Encoding utf8

$size = (Get-Item -LiteralPath $resolvedPath).Length
$sizeKb = [math]::Round($size / 1KB, 1)
Write-Output "Pulled $($matches.Count) match(es); wrote $sizeKb KB to $resolvedPath"
