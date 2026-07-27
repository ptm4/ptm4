# stream-launcher

Cross-platform ad-free stream launcher for Twitch / YouTube / Kick. Detects the OS,
locates VLC + streamlink, and opens a stream at best quality in its own VLC window.
streamlink pulls the raw stream and bypasses the site's web player, so the usual
pre-roll / mid-roll ads don't load.

This is the cross-platform replacement for `../vlcwatcher.ps1` (the PowerShell version
still works on Windows). The launch runs on the machine you're sitting at — there's no
webapp/server hook, because a headless server can't open a VLC window for you.

## Install prerequisites

| OS | Command |
|----|---------|
| Windows | `winget install streamlink.streamlink` + `winget install VideoLAN.VLC` |
| Arch | `sudo pacman -S streamlink vlc` |
| Debian/Ubuntu | `sudo apt install streamlink vlc` |
| Fedora | `sudo dnf install streamlink vlc` |
| macOS | `brew install streamlink` + `brew install --cask vlc` |

The script itself needs only Python 3 (stdlib only — no pip installs).

## Usage

```sh
python3 stream-launcher.py eslcs              # preset -> twitch/eslcs, best quality
python3 stream-launcher.py -p kick -c someone # any platform + channel
python3 stream-launcher.py -p youtube -c chan # youtube handle (@ optional)
python3 stream-launcher.py --list             # list presets + show detected VLC/streamlink
python3 stream-launcher.py --dry-run eslcs    # print the command, don't launch
python3 stream-launcher.py -q 720p eslcs      # override quality
```

Presets live in the `PRESETS` dict at the top of the script (seeded with
`eslcs, eslcsb, pgl, fl0m`) — edit to taste. A bare token is treated as a Twitch
channel, so `stream-launcher.py shroud` works too.

### Tip: make it a short command

- **Linux/macOS:** `alias stream='python3 ~/path/to/stream-launcher.py'` in your shell rc.
- **Windows (PowerShell):** add a function to your `$PROFILE`, or keep using `vlcwatcher.ps1`.
