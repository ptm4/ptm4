#!/usr/bin/env python3
"""
asset-server.py — a read-only HTTP view of E:\\Assets on the workstation (ptm), for
Pertal's Asset Library page (https://webapp.lan:8444/assets). Stdlib only; Pillow, when
installed, adds image thumbnails.

WHY LIVE FROM THIS PC
  Peter chose it over publishing a copy to opti (2026-09-27): the library is ~240 GB and
  worked on daily, and the page should show what is on E: now. The accepted cost: while this
  PC is off, asleep or booted into Linux, the page says "offline" and shows nothing.

WHO TALKS TO IT
  Pertal's backend (container on opti)  GET /health every 30 s, /api/list, /api/search
  nginx-webapp on opti                  /asset-files/*, /asset-thumbs/* passed through to
                                        browsers on https://webapp.lan:8444, path unchanged
  Nothing else: --allow refuses every client but opti (192.168.1.11) and this machine.
  That is the lock that holds. Install-AssetServer.ps1 also adds a firewall rule for opti
  alone, but this PC already has broad "Allow LAN 192.168.1.0/24" rules that admit the
  whole LAN on every port (checked 2026-09-27: noblenumbat reaches :8767 and gets 403).

ENDPOINTS (GET and HEAD only; <rel> is a '/'-separated, percent-encoded path under --root)
  GET /health                        version, root, top-level folders, search-index size
  GET /api/list?path=<rel>           one folder: sub-folders (counts, cover image) + files
  GET /api/search?q=<words>&limit=N  every word must appear in the path; name hits first
  GET /asset-files/<rel>             the file itself (Range, ETag, Last-Modified)
  GET /asset-thumbs/<rel>?w=320      JPEG thumbnail of an image, cached under --cache-dir

SECURITY POSTURE
  - Read-only. Nothing is written under --root. Thumbnails and the log go to --cache-dir
    (default %LOCALAPPDATA%\\asset-server).
  - One root. Every path is checked segment by segment ('..', drive letters and ':'
    streams, DOS device names, trailing dots or spaces, dot-files, OS clutter, a Unity
    project's generated caches), then resolved with realpath (junctions and symlinks
    included) and must still be under --root. Hidden and system files are never served.
  - No login, the same as Pertal itself (LAN + WireGuard): whoever can open Pertal can read
    the library. The library's own gallery pages (index.html, viewer.html, …) are served as
    HTML on Pertal's origin. They are Peter's generated output, and sandboxing them would
    break their navigation.
"""

import argparse
import hashlib
import json
import logging
import logging.handlers
import os
import re
import socket
import stat
import sys
import threading
import time
from datetime import datetime, timezone
from email.utils import formatdate, parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

try:
    from PIL import Image
except ImportError:  # thumbnails are optional; the page falls back to icons
    Image = None

VERSION = "1.0.0"
LOG = logging.getLogger("asset-server")

# ── what may be named, listed and served ────────────────────────────────────────────
DEVICE_NAMES = {"con", "prn", "aux", "nul", "conin$", "conout$", "clock$"}
DEVICE_NAMES |= {f"{p}{n}" for p in ("com", "lpt") for n in list("0123456789") + ["¹", "²", "³"]}
BAD_CHARS = set('<>"|?*:\\') | {chr(c) for c in range(32)}
ALWAYS_HIDDEN = {"__pycache__", "node_modules", "desktop.ini", "thumbs.db", "$recycle.bin",
                 "system volume information"}
UNITY_CACHES = {"library", "temp", "obj", "logs", "usersettings"}  # only inside a Unity project
HIDDEN_ATTRS = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0x2) | getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 0x4)

MODEL_EXT = {".glb", ".gltf"}
COVER_EXT = {".png", ".jpg", ".jpeg", ".webp"}
THUMB_EXT = COVER_EXT | {".gif", ".bmp", ".tga", ".tif", ".tiff"}
THUMB_WIDTHS = (160, 320, 640, 1280, 2048)
# Render names the DND5E pipeline writes, best first; anything else sorts after these.
COVER_NAMES = ("three_quarter", "front", "main", "preview", "hero", "thumbnail", "thumb", "profile")

TYPES = {
    ".glb": "model/gltf-binary", ".gltf": "model/gltf+json",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".bmp": "image/bmp", ".avif": "image/avif",
    ".ico": "image/x-icon", ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".csv": "text/csv; charset=utf-8", ".xml": "text/xml; charset=utf-8",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mp3": "audio/mpeg", ".wav": "audio/wav",
    ".ogg": "audio/ogg", ".pdf": "application/pdf",
}
TEXT_EXT = {".md", ".txt", ".log", ".py", ".cs", ".yaml", ".yml", ".ini", ".cfg", ".toml",
            ".ps1", ".sh", ".bat", ".shader", ".hlsl", ".glsl"}


def utc_iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds") if ts else None


def split_rel(rel):
    """A decoded '/'-separated path → its segments, or None when any segment is refused.
    Empty segments ('a//b', leading or trailing '/') are dropped."""
    if rel is None:
        return []
    if len(rel) > 1024:
        return None
    segs = [s for s in rel.split("/") if s]
    for s in segs:
        if s in (".", "..") or s.startswith(".") or s != s.rstrip(" ."):
            return None
        if any(c in BAD_CHARS for c in s):
            return None
        if s.split(".")[0].rstrip(" ").lower() in DEVICE_NAMES:  # 'nul.txt' is still NUL
            return None
        if s.lower() in ALWAYS_HIDDEN:
            return None
    return segs


def within(path, root):
    p, r = os.path.normcase(path), os.path.normcase(root)
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


def cover_rank(name, stem_hint=None):
    stem = os.path.splitext(name)[0].lower()
    if stem_hint and stem == stem_hint:
        return (0, stem)
    if stem in COVER_NAMES:
        return (1 + COVER_NAMES.index(stem), stem)
    return (50, stem)


class Library:
    """Everything that touches the disk: path checks, listings, search index, thumbnails."""

    def __init__(self, root, cache_dir, thumb_cache_mb=1024):
        self.root = os.path.abspath(root)
        self.root_real = os.path.realpath(self.root)
        self.thumb_dir = os.path.join(cache_dir, "thumbs")
        self.thumb_cache_bytes = thumb_cache_mb * 1024 * 1024
        self.thumb_sem = threading.Semaphore(2)  # Pillow decodes are CPU- and RAM-heavy
        self._unity = {}
        self._list_cache = {}
        self._lock = threading.Lock()
        self.index = SearchIndex(self)
        self.started_at = time.time()

    # ── hiding ──
    def is_unity_project(self, path):
        now = time.monotonic()
        with self._lock:
            hit = self._unity.get(path)
            if hit and now - hit[1] < 300:
                return hit[0]
        val = (os.path.isdir(os.path.join(path, "ProjectSettings"))
               and os.path.isdir(os.path.join(path, "Assets")))
        with self._lock:
            if len(self._unity) > 5000:
                self._unity.clear()
            self._unity[path] = (val, now)
        return val

    def hidden_name(self, parent, name):
        low = name.lower()
        if name.startswith(".") or low in ALWAYS_HIDDEN:
            return True
        return low in UNITY_CACHES and self.is_unity_project(parent)

    def skip_entry(self, parent, entry):
        """True for anything a listing, the index or a request must never show."""
        if self.hidden_name(parent, entry.name):
            return True
        try:
            if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
                return True  # links could lead out of the root; realpath guards requests
            attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
        except OSError:
            return True
        return bool(attrs & HIDDEN_ATTRS)

    def resolve(self, segs):
        """Segments → (absolute path, stat) under the root, or None."""
        cur = self.root
        for s in segs:
            if self.hidden_name(cur, s):
                return None
            cur = os.path.join(cur, s)
        real = os.path.realpath(cur)
        if not within(real, self.root_real):
            return None
        try:
            st = os.stat(real)
        except (OSError, ValueError):
            return None
        if getattr(st, "st_file_attributes", 0) & HIDDEN_ATTRS:
            return None
        return real, st

    def top_folders(self):
        try:
            with os.scandir(self.root) as it:
                return sorted(e.name for e in it
                              if not self.skip_entry(self.root, e) and e.is_dir(follow_symlinks=False))
        except OSError:
            return []

    # ── listing ──
    def _visible(self, path):
        """(dirs, files) DirEntries of one folder, hidden ones removed, sorted by name."""
        dirs, files = [], []
        with os.scandir(path) as it:
            for e in it:
                if self.skip_entry(path, e):
                    continue
                try:
                    if e.is_dir(follow_symlinks=False):
                        dirs.append(e)
                    elif e.is_file(follow_symlinks=False):
                        files.append(e)
                except OSError:
                    continue
        dirs.sort(key=lambda e: e.name.lower())
        files.sort(key=lambda e: e.name.lower())
        return dirs, files

    def _best_image(self, entries, stem_hint=None):
        images = [e.name for e in entries if os.path.splitext(e.name)[1].lower() in COVER_EXT]
        return min(images, key=lambda n: cover_rank(n, stem_hint)) if images else None

    def _cover(self, path, rel, depth=1, entries=None):
        """A render that stands for this folder: previews/<best>, else an image in the
        folder, else (one level down) the first sub-folder that has one."""
        if entries is None:
            try:
                entries = self._visible(path)
            except OSError:
                return None
        dirs, files = entries
        for d in dirs:
            if d.name.lower() == "previews":
                try:
                    _, pfiles = self._visible(d.path)
                except OSError:
                    pfiles = []
                best = self._best_image(pfiles)
                if best:
                    return f"{rel}/{d.name}/{best}"
        best = self._best_image(files, os.path.basename(path).lower())
        if best:
            return f"{rel}/{best}"
        if depth > 0:
            for d in dirs[:6]:
                if d.name.lower() in ("previews", "textures", "audit", "lods", "models"):
                    continue
                found = self._cover(d.path, f"{rel}/{d.name}", depth - 1)
                if found:
                    return found
        return None

    def _model_previews(self, path, rel, files):
        """Candidate renders for the 3D files in this folder: a sibling previews/ folder
        (…/models/x.glb → …/previews/), then images beside the models."""
        cands = []
        here = os.path.basename(path).lower()
        places = []
        if here in ("models", "lods") and "/" in rel:
            parent_rel = rel.rsplit("/", 1)[0]
            places.append((os.path.join(os.path.dirname(path), "previews"), f"{parent_rel}/previews"))
        places.append((os.path.join(path, "previews"), f"{rel}/previews" if rel else "previews"))
        for p, prel in places:
            if os.path.isdir(p) and within(os.path.realpath(p), self.root_real):
                try:
                    _, pf = self._visible(p)
                except OSError:
                    continue
                cands += [(e.name, f"{prel}/{e.name}") for e in pf
                          if os.path.splitext(e.name)[1].lower() in COVER_EXT]
        cands += [(e.name, f"{rel}/{e.name}" if rel else e.name) for e in files
                  if os.path.splitext(e.name)[1].lower() in COVER_EXT]
        return cands

    def list_dir(self, segs):
        res = self.resolve(segs)
        if not res:
            return 404, {"error": "no such folder"}
        real, st = res
        if not stat.S_ISDIR(st.st_mode):
            return 404, {"error": "not a folder"}
        rel = "/".join(segs)
        key = (os.path.normcase(real), st.st_mtime_ns)
        now = time.monotonic()
        with self._lock:
            hit = self._list_cache.get(key)
        if hit and now - hit[1] < 30:
            return 200, hit[0]

        try:
            dirs, files = self._visible(real)
        except OSError as err:
            return 503, {"error": f"cannot read this folder: {err.strerror or err}"}

        detail = len(dirs) <= 400  # counts and covers cost a few directory reads each
        out_dirs = []
        for d in dirs:
            info = {"name": d.name, "mtime": int(d.stat(follow_symlinks=False).st_mtime),
                    "dirs": None, "files": None, "cover": None}
            if detail:
                try:
                    entries = self._visible(d.path)
                except OSError:
                    entries = None
                if entries:
                    info["dirs"], info["files"] = len(entries[0]), len(entries[1])
                    info["cover"] = self._cover(d.path, f"{rel}/{d.name}" if rel else d.name, 1, entries)
            out_dirs.append(info)

        previews = None
        out_files = []
        for f in files:
            try:
                fst = f.stat(follow_symlinks=False)
            except OSError:
                continue
            item = {"name": f.name, "size": fst.st_size, "mtime": int(fst.st_mtime)}
            stem, ext = os.path.splitext(f.name)
            if ext.lower() in MODEL_EXT:
                if previews is None:
                    previews = self._model_previews(real, rel, files)
                base = re.sub(r"_lod\d+$", "", stem.lower())
                best = min(previews, key=lambda c: cover_rank(c[0], base), default=None)
                item["preview"] = best[1] if best else None
            out_files.append(item)

        payload = {
            "path": rel,
            "name": segs[-1] if segs else os.path.basename(self.root.rstrip("\\/")) or self.root,
            "mtime": int(st.st_mtime),
            "dirs": out_dirs,
            "files": out_files,
        }
        with self._lock:
            if len(self._list_cache) > 500:
                self._list_cache.clear()
            self._list_cache[key] = (payload, now)
        return 200, payload

    # ── thumbnails ──
    def thumbnail(self, real, st, width):
        """Path of a cached JPEG no wider or taller than `width`, making it if needed."""
        w = next((x for x in THUMB_WIDTHS if x >= width), THUMB_WIDTHS[-1])
        key = hashlib.sha1(f"{os.path.normcase(real)}|{st.st_size}|{st.st_mtime_ns}|{w}".encode()).hexdigest()
        out = os.path.join(self.thumb_dir, key[:2], key + ".jpg")
        if os.path.isfile(out):
            return out
        with self.thumb_sem:
            if os.path.isfile(out):
                return out
            os.makedirs(os.path.dirname(out), exist_ok=True)
            tmp = f"{out}.{threading.get_ident()}.tmp"
            with Image.open(real) as im:
                im.draft("RGB", (w, w))  # JPEG: decode at a reduced scale
                if im.mode.startswith("I;16"):  # 16-bit greyscale (height maps): resize as "I"
                    im = im.convert("I")
                im.thumbnail((w, w), Image.Resampling.LANCZOS, reducing_gap=2.0)
                if im.mode == "I":
                    im = im.point(lambda v: v * (1 / 256)).convert("L")
                if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
                    im = im.convert("RGBA")
                    bg = Image.new("RGB", im.size, (33, 38, 41))  # the galleries' tile colour
                    bg.paste(im, mask=im.getchannel("A"))
                    im = bg
                elif im.mode != "RGB":
                    im = im.convert("RGB")
                im.save(tmp, "JPEG", quality=82, optimize=True, progressive=True)
            os.replace(tmp, out)
        return out

    def prune_thumbs(self):
        """Keep the thumbnail cache under its cap: oldest files go first."""
        items, total = [], 0
        for dp, _, fns in os.walk(self.thumb_dir):
            for fn in fns:
                p = os.path.join(dp, fn)
                try:
                    s = os.stat(p)
                except OSError:
                    continue
                if fn.endswith(".tmp") and time.time() - s.st_mtime > 3600:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                    continue
                items.append((s.st_mtime, s.st_size, p))
                total += s.st_size
        if total <= self.thumb_cache_bytes:
            return
        for _, size, p in sorted(items):
            try:
                os.remove(p)
                total -= size
            except OSError:
                pass
            if total <= self.thumb_cache_bytes * 0.8:
                break
        LOG.info("thumbnail cache pruned to %d MB", total // (1024 * 1024))


class SearchIndex:
    """Every visible path under the root, rebuilt in the background. Searches never walk."""

    def __init__(self, lib):
        self.lib = lib
        self.entries = []  # (rel, rel_lower, name_lower, is_dir, size, mtime)
        self.files = self.dirs = self.bytes = 0
        self.built_at = None
        self.took_s = None
        self.building = False
        self._lock = threading.Lock()
        self._wake = threading.Event()

    def build(self):
        with self._lock:
            if self.building:
                return
            self.building = True
        try:
            t0 = time.monotonic()
            entries, files, dirs, total = [], 0, 0, 0
            stack = [(self.lib.root, "")]
            while stack:
                path, rel = stack.pop()
                try:
                    it = os.scandir(path)
                except OSError:
                    continue
                with it:
                    for e in it:
                        if self.lib.skip_entry(path, e):
                            continue
                        r = f"{rel}/{e.name}" if rel else e.name
                        try:
                            if e.is_dir(follow_symlinks=False):
                                dirs += 1
                                entries.append((r, r.lower(), e.name.lower(), True, 0, 0))
                                stack.append((e.path, r))
                            elif e.is_file(follow_symlinks=False):
                                s = e.stat(follow_symlinks=False)
                                files += 1
                                total += s.st_size
                                entries.append((r, r.lower(), e.name.lower(), False, s.st_size, int(s.st_mtime)))
                        except OSError:
                            continue
            self.entries, self.files, self.dirs, self.bytes = entries, files, dirs, total
            self.built_at = time.time()
            self.took_s = round(time.monotonic() - t0, 1)
            LOG.info("indexed %d files, %d folders in %.1fs", files, dirs, self.took_s)
        finally:
            with self._lock:
                self.building = False

    def refresh_soon(self):
        """Ask for a rebuild without waiting for it (search uses the current index)."""
        if not self.building and self.built_at and time.time() - self.built_at > 15 * 60:
            self._wake.set()

    def loop(self, every_minutes, first_delay_s):
        # A full walk is ~12k folders: about a minute of seeking on E:'s spinning disk. Run
        # it at background I/O priority so games and Unity in the foreground come first.
        if sys.platform == "win32":
            try:
                import ctypes
                k32 = ctypes.windll.kernel32
                k32.SetThreadPriority(k32.GetCurrentThread(), 0x00010000)  # THREAD_MODE_BACKGROUND_BEGIN
            except (AttributeError, OSError):
                pass
        time.sleep(first_delay_s)  # started at logon: let the desktop settle first
        while True:
            try:
                self.build()
            except Exception:  # never let the indexer die silently
                LOG.exception("index build failed")
            self._wake.wait(every_minutes * 60)
            self._wake.clear()

    def search(self, q, limit):
        terms = [t for t in q.lower().split() if t][:8]
        whole = " ".join(terms)
        hits = []
        for rel, rl, nl, is_dir, size, mtime in self.entries:
            if all(t in rl for t in terms):
                score = 0 if nl == whole else 1 if all(t in nl for t in terms) else 2
                hits.append((score, rl.count("/"), len(rl), rel, is_dir, size, mtime))
        hits.sort()
        return len(hits), [
            {"path": rel, "name": rel.rsplit("/", 1)[-1], "dir": is_dir,
             "size": None if is_dir else size, "mtime": None if is_dir else mtime}
            for _, _, _, rel, is_dir, size, mtime in hits[:limit]
        ]

    def summary(self):
        return {"files": self.files, "dirs": self.dirs, "bytes": self.bytes,
                "built_at": utc_iso(self.built_at), "took_s": self.took_s, "building": self.building}


class Handler(BaseHTTPRequestHandler):
    server_version = "asset-server/" + VERSION
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 60  # an idle or stalled connection gives its thread back

    @property
    def lib(self):
        return self.server.lib

    def log_message(self, fmt, *args):  # pythonw has no stderr; everything goes to the log
        LOG.info("%s %s", self.client_address[0], fmt % args)

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, socket.timeout):
            self.close_connection = True  # a browser switching models drops the old download

    # ── responses ──
    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", headers=None, head=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body and not head:
            self.wfile.write(body)

    def _json(self, code, obj, head=False, headers=None):
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send(code, body, headers={"Cache-Control": "no-store", **(headers or {})}, head=head)

    # ── routing ──
    def do_GET(self):
        self._route(head=False)

    def do_HEAD(self):
        self._route(head=True)

    def _refuse(self):
        self._json(405, {"error": "read-only: GET and HEAD only"}, headers={"Allow": "GET, HEAD"})

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _refuse

    def _route(self, head):
        ip = self.client_address[0]
        if ip.startswith("::ffff:"):
            ip = ip[7:]
        if ip not in self.server.allowed:
            LOG.warning("refused %s %s", ip, self.path[:200])
            return self._json(403, {"error": "not allowed"}, head=head)
        parts = urlsplit(self.path)
        try:
            path = unquote(parts.path, errors="strict")
        except UnicodeDecodeError:
            return self._json(400, {"error": "bad path encoding"}, head=head)
        q = parse_qs(parts.query)
        arg = lambda k, d=None: (q.get(k) or [d])[0]  # noqa: E731

        if path == "/health":
            return self._json(200, {
                "ok": True, "service": "asset-server", "version": VERSION, "root": self.lib.root,
                "roots": self.lib.top_folders(), "index": self.lib.index.summary(),
                "thumbnails": Image is not None, "started_at": utc_iso(self.lib.started_at),
            }, head=head)
        if path == "/api/list":
            segs = split_rel(arg("path", ""))
            if segs is None:
                return self._json(400, {"error": "bad path"}, head=head)
            code, payload = self.lib.list_dir(segs)
            return self._json(code, payload, head=head)
        if path == "/api/search":
            text = (arg("q", "") or "").strip()
            if not 1 <= len(text) <= 200:
                return self._json(400, {"error": "q must be 1-200 characters"}, head=head)
            idx = self.lib.index
            if not idx.built_at:
                return self._json(503, {"error": "the search index is still being built", "building": True}, head=head)
            try:
                limit = max(1, min(500, int(arg("limit", "200"))))
            except ValueError:
                limit = 200
            idx.refresh_soon()
            total, results = idx.search(text, limit)
            return self._json(200, {"q": text, "total": total, "results": results,
                                    "indexed_at": utc_iso(idx.built_at), "building": idx.building}, head=head)
        if path.startswith("/asset-files/"):
            return self._file(path[len("/asset-files/"):], head)
        if path.startswith("/asset-thumbs/"):
            return self._thumb(path[len("/asset-thumbs/"):], arg("w", "320"), "v" in q, head)
        return self._json(404, {"error": "not found"}, head=head)

    def _file(self, rel, head):
        segs = split_rel(rel)
        res = self.lib.resolve(segs) if segs is not None else None
        if not res:
            return self._json(404, {"error": "not found"}, head=head)
        real, st = res
        if stat.S_ISDIR(st.st_mode):
            index = os.path.join(real, "index.html")
            if rel.endswith("/") and os.path.isfile(index):
                target = "/asset-files/" + quote("/".join(segs) + "/index.html")
                return self._send(302, b"", headers={"Location": target}, head=head)
            return self._json(404, {"error": "that is a folder"}, head=head)
        ext = os.path.splitext(real)[1].lower()
        ctype = TYPES.get(ext) or ("text/plain; charset=utf-8" if ext in TEXT_EXT else "application/octet-stream")
        self._send_file(real, st, ctype, "no-cache", head)

    def _thumb(self, rel, width, versioned, head):
        segs = split_rel(rel)
        res = self.lib.resolve(segs) if segs is not None else None
        if not res or not stat.S_ISREG(res[1].st_mode):
            return self._json(404, {"error": "not found"}, head=head)
        real, st = res
        if Image is None:
            return self._json(501, {"error": "Pillow is not installed on ptm"}, head=head)
        if os.path.splitext(real)[1].lower() not in THUMB_EXT:
            return self._json(415, {"error": "not an image"}, head=head)
        try:
            w = max(32, min(2048, int(width)))
        except ValueError:
            w = 320
        try:
            out = self.lib.thumbnail(real, st, w)
            ost = os.stat(out)
        except Exception as err:  # corrupt, huge or unsupported image
            LOG.warning("thumbnail failed for %s: %s", rel, err)
            return self._json(415, {"error": f"cannot make a thumbnail: {err}"}, head=head)
        cache = "public, max-age=2592000, immutable" if versioned else "no-cache"
        self._send_file(out, ost, "image/jpeg", cache, head)

    def _send_file(self, real, st, ctype, cache_control, head):
        size = st.st_size
        etag = f'"{size:x}-{st.st_mtime_ns:x}"'
        common = {"ETag": etag, "Last-Modified": formatdate(st.st_mtime, usegmt=True),
                  "Cache-Control": cache_control, "Accept-Ranges": "bytes"}

        inm = self.headers.get("If-None-Match")
        ims = self.headers.get("If-Modified-Since")
        fresh = False
        if inm:
            fresh = etag in [t.strip() for t in inm.split(",")] or inm.strip() == "*"
        elif ims:
            try:
                fresh = int(st.st_mtime) <= parsedate_to_datetime(ims).timestamp()
            except (TypeError, ValueError):
                fresh = False
        if fresh:
            self.send_response(304)
            for k, v in common.items():
                self.send_header(k, v)
            self.end_headers()
            return

        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range")
        if rng and (not self.headers.get("If-Range") or self.headers.get("If-Range") == etag):
            m = re.fullmatch(r"\s*bytes=(\d*)-(\d*)\s*", rng)
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
                else:
                    start, end = max(0, size - int(m.group(2))), size - 1
                if start >= size or start > end:
                    return self._send(416, b"", headers={"Content-Range": f"bytes */{size}"}, head=head)
                code = 206

        try:
            fh = open(real, "rb")
        except OSError as err:
            return self._json(503, {"error": f"cannot open the file: {err.strerror or err}"}, head=head)
        with fh:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(max(0, end - start + 1)))
            self.send_header("X-Content-Type-Options", "nosniff")
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            for k, v in common.items():
                self.send_header(k, v)
            self.end_headers()
            if head:
                return
            fh.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = fh.read(min(1 << 20, remaining))
                if not chunk:  # the file shrank while we sent it
                    self.close_connection = True
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR would let a second process bind the same port; ask for
    # exclusive use instead, so a stray second copy fails loudly.
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request, client_address):  # the default prints to a missing stderr
        LOG.exception("request from %s failed", client_address[0])


def default_cache_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "asset-server")


def parse_args(argv=None):
    env = os.environ.get
    ap = argparse.ArgumentParser(description="Read-only HTTP view of the asset library, for Pertal.")
    ap.add_argument("--root", default=env("ASSET_ROOT", r"E:\Assets"))
    ap.add_argument("--bind", default=env("ASSET_BIND", "127.0.0.1"),
                    help="address to listen on; the install script uses this PC's LAN address")
    ap.add_argument("--port", type=int, default=int(env("ASSET_PORT", "8767")))
    ap.add_argument("--allow", default=env("ASSET_ALLOW", "192.168.1.11"),
                    help="comma-separated client IPs admitted besides this machine (default: opti)")
    ap.add_argument("--cache-dir", default=env("ASSET_CACHE_DIR", default_cache_dir()))
    ap.add_argument("--reindex-minutes", type=float, default=float(env("ASSET_REINDEX_MINUTES", "60")),
                    help="full re-walk interval; a search also asks for one once the index is 15 min old")
    ap.add_argument("--index-delay", type=float, default=float(env("ASSET_INDEX_DELAY", "60")),
                    help="seconds to wait before the first index build")
    ap.add_argument("--thumb-cache-mb", type=int, default=int(env("ASSET_THUMB_CACHE_MB", "1024")))
    return ap.parse_args(argv)


def setup_logging(cache_dir):
    LOG.setLevel(logging.INFO)
    fh = logging.handlers.RotatingFileHandler(os.path.join(cache_dir, "asset-server.log"),
                                              maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(fh)
    if sys.stderr is not None:  # python.exe in a console; pythonw has no stderr
        LOG.addHandler(logging.StreamHandler())


def main(argv=None):
    args = parse_args(argv)
    os.makedirs(args.cache_dir, exist_ok=True)
    setup_logging(args.cache_dir)
    if not os.path.isdir(args.root):
        LOG.error("root %s is not a folder", args.root)
        return 2
    lib = Library(args.root, args.cache_dir, args.thumb_cache_mb)
    allowed = {"127.0.0.1", "::1"} | {a.strip() for a in args.allow.split(",") if a.strip()}
    if args.bind not in ("", "0.0.0.0", "::"):
        allowed.add(args.bind)  # this PC reaching its own LAN address

    # At logon the network can come up after us: keep trying to bind for ten minutes.
    httpd = None
    for attempt in range(60):
        try:
            httpd = Server((args.bind, args.port), Handler)
            break
        except OSError as err:
            if attempt == 0:
                LOG.warning("cannot listen on %s:%d yet (%s); retrying", args.bind, args.port, err)
            time.sleep(10)
    if httpd is None:
        LOG.error("gave up listening on %s:%d", args.bind, args.port)
        return 1
    httpd.lib = lib
    httpd.allowed = allowed

    threading.Thread(target=lib.index.loop, args=(args.reindex_minutes, args.index_delay),
                     daemon=True, name="indexer").start()

    def prune_loop():
        while True:
            try:
                lib.prune_thumbs()
            except Exception:
                LOG.exception("thumbnail prune failed")
            time.sleep(3600)

    if Image is not None:
        threading.Thread(target=prune_loop, daemon=True, name="thumb-prune").start()
    else:
        LOG.warning("Pillow is not installed: no thumbnails (pip install pillow)")

    LOG.info("asset-server %s serving %s on %s:%d (clients: %s)", VERSION, lib.root, args.bind,
             args.port, ", ".join(sorted(allowed)))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
