<#
.SYNOPSIS
    Launches one or more live streams in VLC via streamlink.

.DESCRIPTION
    Wrapper around streamlink that accepts a platform and one or more channels,
    builds the proper URL per platform, and launches each stream in its own VLC
    window. Designed to be invoked as: vlcwatcher -p twitch -ch eslcs
    Or for multiple channels: vlcwatcher -p twitch -ch eslcs,pgl,fl0m
    Or use a saved preset:    vlcwatcher -Preset cs

.PARAMETER Platform
    Streaming platform. Currently supports: twitch, youtube, kick.
    Alias: -p

.PARAMETER Channel
    One or more channel names (comma-separated). Do NOT include the URL prefix.
    Alias: -ch

.PARAMETER Quality
    Streamlink quality string. Defaults to "best".
    Alias: -q

.PARAMETER Preset
    Load a saved preset list of channels (defined in the $Presets hashtable
    below). When used, -Platform and -Channel are ignored.

.PARAMETER VlcPath
    Full path to vlc.exe. Defaults to the standard install location.

.PARAMETER DryRun
    Print the streamlink commands that would run without launching them.

.EXAMPLE
    vlcwatcher -p twitch -ch eslcsb

.EXAMPLE
    vlcwatcher -p twitch -ch eslcs,eslcsb,pgl,fl0m

.EXAMPLE
    vlcwatcher -Preset cs
#>

[CmdletBinding(DefaultParameterSetName = 'Direct')]
param(
    [Parameter(ParameterSetName = 'Direct', Mandatory = $true)]
    [Alias('p')]
    [ValidateSet('twitch', 'youtube', 'kick')]
    [string]$Platform,

    [Parameter(ParameterSetName = 'Direct', Mandatory = $true)]
    [Alias('ch')]
    [string[]]$Channel,

    [Parameter(ParameterSetName = 'Preset', Mandatory = $true)]
    [string]$Preset,

    [Alias('q')]
    [string]$Quality = 'best',

    [string]$VlcPath = 'C:\Program Files\VideoLAN\VLC\vlc.exe',

    [switch]$DryRun
)

# -------------------------------------------------------------------
# Presets: edit these to build your own channel groups.
# Each preset is an array of @{ Platform = '...'; Channel = '...' }
# -------------------------------------------------------------------
$Presets = @{
    'cs' = @(
        @{ Platform = 'twitch'; Channel = 'eslcs' }
        @{ Platform = 'twitch'; Channel = 'eslcsb' }
        @{ Platform = 'twitch'; Channel = 'pgl' }
        @{ Platform = 'twitch'; Channel = 'fl0m' }
    )
}

function Get-StreamUrl {
    param(
        [string]$Platform,
        [string]$Channel
    )
    switch ($Platform.ToLower()) {
        'twitch'  { return "https://www.twitch.tv/$Channel" }
        'youtube' { return "https://www.youtube.com/@$Channel/live" }
        'kick'    { return "https://kick.com/$Channel" }
        default   { throw "Unsupported platform: $Platform" }
    }
}

function Start-Stream {
    param(
        [string]$Platform,
        [string]$Channel,
        [string]$Quality,
        [string]$VlcPath,
        [switch]$DryRun
    )

    $url = Get-StreamUrl -Platform $Platform -Channel $Channel
    $streamlinkArgs = @(
        $url,
        $Quality,
        '--player',  "`"$VlcPath`"",
        '--title',   "`"$Platform`:$Channel`""
    )

    Write-Host "[vlcwatcher] $Platform/$Channel -> $url" -ForegroundColor Cyan

    if ($DryRun) {
        Write-Host "           streamlink $($streamlinkArgs -join ' ')" -ForegroundColor Yellow
        return
    }

    # Launch each stream in its own process so multiple channels run in parallel
    Start-Process -FilePath 'streamlink' -ArgumentList $streamlinkArgs -WindowStyle Minimized | Out-Null
}

# -------------------------------------------------------------------
# Sanity checks
# -------------------------------------------------------------------
if (-not (Get-Command streamlink -ErrorAction SilentlyContinue)) {
    Write-Error "streamlink not found on PATH. Install via: winget install streamlink.streamlink"
    exit 1
}

if (-not (Test-Path $VlcPath)) {
    Write-Error "VLC not found at $VlcPath. Pass -VlcPath to override."
    exit 1
}

# -------------------------------------------------------------------
# Dispatch
# -------------------------------------------------------------------
if ($PSCmdlet.ParameterSetName -eq 'Preset') {
    if (-not $Presets.ContainsKey($Preset)) {
        Write-Error "Unknown preset '$Preset'. Available: $($Presets.Keys -join ', ')"
        exit 1
    }
    foreach ($item in $Presets[$Preset]) {
        Start-Stream -Platform $item.Platform -Channel $item.Channel -Quality $Quality -VlcPath $VlcPath -DryRun:$DryRun
    }
}
else {
    foreach ($c in $Channel) {
        Start-Stream -Platform $Platform -Channel $c -Quality $Quality -VlcPath $VlcPath -DryRun:$DryRun
    }
}