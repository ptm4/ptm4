# asset-server (ptm, Windows side)

Serves `E:\Assets` read-only to Pertal's **Asset Library** page
(`https://webapp.lan:8444/assets`): a folder tree beside the open folder, thumbnails, search,
and models in the library's own 3D inspector (the same model-viewer build, backdrop and
controls as `E:\Assets\DND5E\viewer.html`).

The library lives on this PC's E: drive (~240 GB, worked on daily), so it is read **live**
rather than copied to opti (Peter's call, 2026-09-27). While this PC is off, asleep or booted
into Linux, the page says "ptm is offline" and nothing else notices: the source never counts
as failing on Pertal's Status page or in the Activity feed.

## How it fits together

```
browser ──https──▶ nginx-webapp (opti :8444) ─┬─ /api/*            ▶ pertal ─┐
                                              └─ /asset-files/*   ─┐         │ /health every 30s,
                                                 /asset-thumbs/*   │         │ /api/list, /api/search
                                                                   ▼         ▼
                                              ptm 192.168.1.3:8767  asset-server.py ──▶ E:\Assets (read-only)
```

- **Pertal** (`webapp.v4.Pertal`): `backend/sources/assets.js` polls `/health` into the
  `assets:server` snapshot; `backend/routes/assets.js` relays folder listings and search with
  hard timeouts; the page is `frontend/src/routes/assets/+page.svelte`.
- **nginx** (`homelab/hosts/opti/apps/nginx-wg.conf`, `:8444` block) passes `/asset-files/`
  and `/asset-thumbs/` straight to this PC, the same shape as `/hls`. The asset server's
  `/api` is not exposed to browsers.
- **Setting:** `ASSET_SERVER_URL` on the `pertal` service in `docker-compose.apps.yml`
  (default `http://192.168.1.3:8767`).

## Install (once, from an elevated PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File E:\REPO\ptm4\homelab\hosts\ptm\asset-server\Install-AssetServer.ps1
```

It copies `asset-server.py` to `%LOCALAPPDATA%\asset-server\`, adds the firewall rule
**Homelab-AssetLibrary** (inbound TCP 8767 from 192.168.1.11 only, `pythonw.exe` only, all
profiles, because this PC's Ethernet is on the Public profile), registers the logon task
`\Homelab\Asset Library server` (runs as ptm, not elevated, restarts on failure), and starts it.
Re-run after changing `asset-server.py`. `-Uninstall` removes the task and the rule.

Needs Python 3.10+ on PATH (python.org build) and, for thumbnails, Pillow
(`python -m pip install pillow`); without Pillow the page shows icons.

## Security

- **Read-only.** GET and HEAD only; nothing is written under `E:\Assets`. Thumbnails and the log
  go to `%LOCALAPPDATA%\asset-server\`, and the thumbnail cache is capped at 1 GB.
- **One folder.** Every path is checked segment by segment (`..`, drive letters and `:`
  streams, DOS device names, trailing dots/spaces, dot-files, OS clutter, a Unity project's
  `Library`/`Temp`/`Logs`/`obj`/`UserSettings`) and then resolved, junctions included; it must
  still be under `E:\Assets`. Hidden and system files are never listed or served.
- **Two locks on who connects.** The firewall admits only opti, and the server itself refuses
  every client except opti and this PC (`--allow`).
- **No login**, like Pertal itself (LAN + WireGuard): anyone who can open Pertal can browse
  and download the library. The library's own HTML galleries run on Pertal's origin.

## Operate

| | |
|---|---|
| Log | `%LOCALAPPDATA%\asset-server\asset-server.log` (rotates at 2 MB) |
| Health | `curl http://192.168.1.3:8767/health` from this PC |
| Restart | `Stop-ScheduledTask` / `Start-ScheduledTask -TaskPath \Homelab\ -TaskName 'Asset Library server'` |
| Search index | built 60 s after start, then re-walked hourly (or when a search finds it 15 min old), at background I/O priority: E: is a spinning disk and a full walk is about a minute of seeking |

## Develop

```bash
python -m unittest discover -s homelab/hosts/ptm/asset-server -v   # path refusals, junction escape, listings, Range, thumbnails, search
python homelab/hosts/ptm/asset-server/asset-server.py --index-delay 5   # 127.0.0.1:8767, loopback only
```

Loopback needs no firewall rule and triggers no prompt. Don't bind the LAN address by hand
with `python.exe`: the rule only covers `pythonw.exe`, and Windows would ask to allow Python on
every port.
