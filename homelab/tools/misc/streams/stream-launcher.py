#!/usr/bin/env python3
"""
stream-launcher.py — cross-platform ad-free stream launcher (Twitch/YouTube/Kick).

Detects the OS, locates VLC + streamlink, and launches a stream at the best
available quality in its own VLC window. streamlink pulls the raw stream and
bypasses the site's web player, so pre-roll/mid-roll ads don't load. The launch
runs on THIS machine (the one with a screen) — there's intentionally no webapp
hook, since a headless server can't open a VLC window for you.

Cross-platform replacement for vlcwatcher.ps1 (which stays for Windows/PowerShell users).

Usage:
    stream-launcher.py eslcs                 # preset -> twitch/eslcs, best quality
    stream-launcher.py -p kick -c someone    # any platform + channel
    stream-launcher.py -p youtube -c @chan   # youtube handle (with or without @)
    stream-launcher.py --list                # list presets
    stream-launcher.py --dry-run eslcs       # print the command, don't launch
    stream-launcher.py -q 720p eslcs         # override quality

Requires: streamlink (winget/apt/pacman install streamlink) and VLC.
Stdlib only — no pip installs needed.
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys

# Quality fallback chain — mirrors vlcwatcher.ps1. streamlink picks the first available.
DEFAULT_QUALITY = "best,1440p60,1440p,1080p60,1080p,720p60,720p,worst"

# Preset channels (edit freely). Each maps a short name -> (platform, channel).
PRESETS = {
    "eslcs":  ("twitch", "eslcs"),
    "eslcsb": ("twitch", "eslcsb"),
    "pgl":    ("twitch", "pgl"),
    "fl0m":   ("twitch", "fl0m"),
}

# Known VLC install locations to probe after PATH (per-OS).
VLC_CANDIDATES = {
    "Windows": [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    ],
    "Darwin": [
        "/Applications/VLC.app/Contents/MacOS/VLC",
    ],
    "Linux": [
        "/usr/bin/vlc",
        "/usr/local/bin/vlc",
        "/snap/bin/vlc",
        "/var/lib/flatpak/exports/bin/org.videolan.VLC",
    ],
}


def find_vlc():
    """Return a path to VLC, or None. PATH first, then OS-specific known locations."""
    found = shutil.which("vlc")
    if found:
        return found
    for path in VLC_CANDIDATES.get(platform.system(), []):
        if os.path.exists(path):
            return path
    # Flatpak fallback: launch via `flatpak run` if the app is installed.
    if platform.system() == "Linux" and shutil.which("flatpak"):
        return "flatpak-vlc"  # sentinel handled in build_player_arg
    return None


def stream_url(plat, channel):
    plat = plat.lower()
    if plat == "twitch":
        return f"https://www.twitch.tv/{channel}"
    if plat == "youtube":
        handle = channel if channel.startswith("@") else f"@{channel}"
        return f"https://www.youtube.com/{handle}/live"
    if plat == "kick":
        return f"https://kick.com/{channel}"
    raise ValueError(f"Unsupported platform: {plat} (use twitch/youtube/kick)")


def player_arg(vlc):
    """Quote the VLC path for streamlink's --player; handle the flatpak sentinel."""
    if vlc == "flatpak-vlc":
        return "flatpak run org.videolan.VLC"
    return f'"{vlc}"'


def install_hint():
    sysname = platform.system()
    if sysname == "Windows":
        return "winget install streamlink.streamlink  (and VLC: winget install VideoLAN.VLC)"
    if sysname == "Darwin":
        return "brew install streamlink  (and VLC: brew install --cask vlc)"
    # Linux — guess the package manager
    for mgr, cmd in (("pacman", "sudo pacman -S streamlink vlc"),
                     ("apt", "sudo apt install streamlink vlc"),
                     ("dnf", "sudo dnf install streamlink vlc")):
        if shutil.which(mgr):
            return cmd
    return "install streamlink + vlc with your package manager"


def launch(plat, channel, quality, dry_run):
    sl = shutil.which("streamlink")
    vlc = find_vlc()

    missing = []
    if not sl:
        missing.append("streamlink")
    if not vlc:
        missing.append("VLC")
    if missing and not dry_run:
        print(f"ERROR: {' and '.join(missing)} not found.", file=sys.stderr)
        print(f"Install: {install_hint()}", file=sys.stderr)
        return 1

    url = stream_url(plat, channel)
    title = f"{plat}:{channel}"
    # streamlink <url> <quality> --player "<vlc>" --title "<title>"
    args = [sl or "streamlink", url, quality,
            "--player", player_arg(vlc or "<vlc>"),
            "--title", title]

    print(f"[stream-launcher] {plat}/{channel} -> {url}  (quality: {quality.split(',')[0]} first)")
    if dry_run:
        # Show a copy-pasteable command line
        print("  " + " ".join(args))
        if missing:
            print(f"  (note: {', '.join(missing)} not detected on this machine — {install_hint()})")
        return 0

    # Detach so multiple launches run in parallel and survive this process exiting.
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    except Exception as e:
        print(f"ERROR launching streamlink: {e}", file=sys.stderr)
        return 1
    print(f"  launched in VLC ({vlc})")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Launch an ad-free Twitch/YouTube/Kick stream in VLC via streamlink.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Presets: " + ", ".join(PRESETS) + "\nExample: stream-launcher.py eslcs",
    )
    p.add_argument("preset", nargs="?", help="preset name (see --list) OR a twitch channel")
    p.add_argument("-p", "--platform", choices=["twitch", "youtube", "kick"],
                   help="platform for a free-entry channel (with -c)")
    p.add_argument("-c", "--channel", help="channel/handle for a free-entry stream")
    p.add_argument("-q", "--quality", default=DEFAULT_QUALITY, help="streamlink quality string")
    p.add_argument("--list", action="store_true", help="list presets and exit")
    p.add_argument("--dry-run", action="store_true", help="print the command without launching")
    args = p.parse_args(argv)

    if args.list:
        print("Presets:")
        for name, (plat, ch) in PRESETS.items():
            print(f"  {name:8s} -> {plat}/{ch}")
        vlc = find_vlc()
        print(f"\nVLC: {vlc or 'NOT FOUND'} · streamlink: {shutil.which('streamlink') or 'NOT FOUND'}")
        return 0

    # Resolve what to launch: free-entry (-p/-c) wins; else preset; else a bare twitch channel.
    if args.channel:
        plat = args.platform or "twitch"
        channel = args.channel
    elif args.preset and args.preset in PRESETS:
        plat, channel = PRESETS[args.preset]
    elif args.preset:
        plat, channel = "twitch", args.preset  # treat a bare token as a twitch channel
    else:
        p.print_help()
        return 2

    return launch(plat, channel, args.quality, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
