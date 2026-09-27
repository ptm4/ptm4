"""Tests for asset-server.py: path refusals, listings, files, thumbnails, search, clients.

    python -m unittest discover -s homelab/hosts/ptm/asset-server -v

Each test class builds a small library in a temp folder and runs the real server on an
ephemeral 127.0.0.1 port. Nothing outside the temp folder is read or written.
"""
import http.client
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("asset_server", os.path.join(HERE, "asset-server.py"))
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)


class SplitRel(unittest.TestCase):
    def test_accepts_plain_paths(self):
        self.assertEqual(srv.split_rel(""), [])
        self.assertEqual(srv.split_rel("DND5E/characters/races"), ["DND5E", "characters", "races"])
        self.assertEqual(srv.split_rel("/a//b/"), ["a", "b"])
        self.assertEqual(srv.split_rel("Dungeons&Dragons/Peter's spell book"), ["Dungeons&Dragons", "Peter's spell book"])

    def test_refuses_escapes_and_windows_tricks(self):
        for bad in ["..", "a/../b", ".", ".git/config", "a/.hidden", "C:", "C:/Windows", "x:stream",
                    "a\\b", "con", "NUL.txt", "com1", "lpt9.log", "trailing.", "trailing ", "tab\there",
                    "q?", "star*", "__pycache__", "desktop.ini", "x" * 1100]:
            self.assertIsNone(srv.split_rel(bad), bad)


def png(path, size=(64, 48), rgba=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if srv.Image is None:
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
        return
    srv.Image.new("RGBA" if rgba else "RGB", size, (200, 30, 30, 128) if rgba else (200, 30, 30)).save(path)


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="asset-server-test-")
        cls.root = os.path.join(cls.tmp, "Assets")
        outside = os.path.join(cls.tmp, "outside")
        write(os.path.join(outside, "secret.txt"), b"outside the root")
        write(os.path.join(cls.root, "lib", "orc", "models", "orc.glb"), b"glTF" + b"\0" * 60)
        write(os.path.join(cls.root, "lib", "orc", "models", "orc.fbx"), b"fbx")
        write(os.path.join(cls.root, "lib", "orc", "lods", "orc_LOD1.glb"), b"glTF")
        png(os.path.join(cls.root, "lib", "orc", "previews", "front.png"))
        png(os.path.join(cls.root, "lib", "orc", "previews", "three_quarter.png"), rgba=True)
        write(os.path.join(cls.root, "lib", "notes.md"), b"# Notes\nhello library\n")
        write(os.path.join(cls.root, "lib", ".secret"), b"dot")
        write(os.path.join(cls.root, "unity", "Assets", "a.txt"))
        write(os.path.join(cls.root, "unity", "ProjectSettings", "p.asset"))
        write(os.path.join(cls.root, "unity", "Library", "cache.bin"))
        write(os.path.join(cls.root, "gallery", "index.html"), b"<!doctype html><title>g</title>")
        cls.junction = False
        if sys.platform == "win32":
            import _winapi
            try:
                _winapi.CreateJunction(outside, os.path.join(cls.root, "escape"))
                cls.junction = True
            except OSError:
                pass
        else:
            os.symlink(outside, os.path.join(cls.root, "escape"))
            cls.junction = True

        cls.lib = srv.Library(cls.root, os.path.join(cls.tmp, "cache"))
        cls.lib.index.build()
        cls.httpd = srv.Server(("127.0.0.1", 0), srv.Handler)
        cls.httpd.lib = cls.lib
        cls.httpd.allowed = {"127.0.0.1"}
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        if cls.junction and sys.platform == "win32":
            os.rmdir(os.path.join(cls.root, "escape"))  # removes the junction, not its target
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, path, method="GET", headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r, body

    def get_json(self, path):
        r, body = self.req(path)
        return r.status, json.loads(body) if body else None

    def test_health(self):
        code, h = self.get_json("/health")
        self.assertEqual(code, 200)
        self.assertEqual(h["service"], "asset-server")
        self.assertEqual(h["roots"], ["gallery", "lib", "unity"])  # no junction, no dot-folders
        self.assertGreater(h["index"]["files"], 5)

    def test_listing_hides_what_it_should(self):
        code, lst = self.get_json("/api/list?path=lib")
        self.assertEqual(code, 200)
        self.assertEqual([d["name"] for d in lst["dirs"]], ["orc"])
        self.assertEqual([f["name"] for f in lst["files"]], ["notes.md"])
        orc = lst["dirs"][0]
        self.assertEqual((orc["dirs"], orc["files"]), (3, 0))
        self.assertEqual(orc["cover"], "lib/orc/previews/three_quarter.png")
        code, unity = self.get_json("/api/list?path=unity")
        self.assertEqual([d["name"] for d in unity["dirs"]], ["Assets", "ProjectSettings"])

    def test_models_get_their_render(self):
        _, lst = self.get_json("/api/list?path=lib/orc/models")
        glb = next(f for f in lst["files"] if f["name"] == "orc.glb")
        self.assertEqual(glb["preview"], "lib/orc/previews/three_quarter.png")
        _, lods = self.get_json("/api/list?path=lib/orc/lods")
        self.assertEqual(lods["files"][0]["preview"], "lib/orc/previews/three_quarter.png")

    def test_refused_paths_are_404_or_400(self):
        for p in ["/asset-files/lib/.secret", "/asset-files/unity/Library/cache.bin",
                  "/asset-files/escape/secret.txt", "/asset-files/lib/..%2F..%2Foutside%2Fsecret.txt",
                  "/asset-files/lib%5C..%5C..%5Coutside%5Csecret.txt", "/asset-files/C:%2FWindows%2Fwin.ini",
                  "/asset-files/nope.txt", "/asset-thumbs/escape/secret.txt"]:
            r, body = self.req(p)
            self.assertEqual(r.status, 404, p)
            self.assertNotIn(b"outside the root", body)
        self.assertEqual(self.get_json("/api/list?path=../outside")[0], 400)
        self.assertEqual(self.get_json("/api/list?path=escape")[0], 404)

    def test_junction_out_of_the_root_is_real_but_refused(self):
        self.assertTrue(self.junction, "could not create the test junction/symlink")
        with open(os.path.join(self.root, "escape", "secret.txt"), "rb") as f:
            self.assertEqual(f.read(), b"outside the root")  # the OS follows it...
        r, body = self.req("/asset-files/escape/secret.txt")
        self.assertEqual(r.status, 404)  # ...the server does not
        self.assertNotIn("escape", [d["name"] for d in self.get_json("/api/list?path=")[1]["dirs"]])

    def test_file_etag_and_range(self):
        r, body = self.req("/asset-files/lib/notes.md")
        self.assertEqual(r.status, 200)
        self.assertTrue(r.getheader("Content-Type").startswith("text/plain"))
        self.assertEqual(body, b"# Notes\nhello library\n")
        etag = r.getheader("ETag")
        r2, _ = self.req("/asset-files/lib/notes.md", headers={"If-None-Match": etag})
        self.assertEqual(r2.status, 304)
        r3, part = self.req("/asset-files/lib/notes.md", headers={"Range": "bytes=2-6"})
        self.assertEqual((r3.status, part), (206, b"Notes"))
        self.assertEqual(r3.getheader("Content-Range"), f"bytes 2-6/{len(body)}")
        r4, _ = self.req("/asset-files/lib/notes.md", headers={"Range": "bytes=999-"})
        self.assertEqual(r4.status, 416)
        r5, _ = self.req("/asset-files/lib/orc/models/orc.glb", method="HEAD")
        self.assertEqual((r5.status, r5.getheader("Content-Type")), (200, "model/gltf-binary"))

    def test_folder_with_index_redirects(self):
        r, _ = self.req("/asset-files/gallery/")
        self.assertEqual((r.status, r.getheader("Location")), (302, "/asset-files/gallery/index.html"))
        r, _ = self.req("/asset-files/gallery/index.html")
        self.assertTrue(r.getheader("Content-Type").startswith("text/html"))

    @unittest.skipIf(srv.Image is None, "Pillow not installed")
    def test_thumbnail(self):
        r, body = self.req("/asset-thumbs/lib/orc/previews/three_quarter.png?w=32&v=1")
        self.assertEqual((r.status, r.getheader("Content-Type")), (200, "image/jpeg"))
        self.assertIn("immutable", r.getheader("Cache-Control"))
        self.assertEqual(body[:2], b"\xff\xd8")
        self.assertEqual(self.req("/asset-thumbs/lib/notes.md")[0].status, 415)

    def test_search(self):
        code, res = self.get_json("/api/search?q=orc%20glb")
        self.assertEqual(code, 200)
        self.assertEqual(res["results"][0]["path"], "lib/orc/models/orc.glb")
        self.assertFalse(any("Library" in x["path"] or ".secret" in x["path"] for x in res["results"]))
        self.assertEqual(self.get_json("/api/search?q=")[0], 400)

    def test_read_only_and_client_allowlist(self):
        self.assertEqual(self.req("/health", method="POST")[0].status, 405)
        self.assertEqual(self.req("/asset-files/lib/notes.md", method="DELETE")[0].status, 405)
        self.httpd.allowed = {"10.9.9.9"}
        try:
            self.assertEqual(self.req("/health")[0].status, 403)
        finally:
            self.httpd.allowed = {"127.0.0.1"}


if __name__ == "__main__":
    unittest.main()
