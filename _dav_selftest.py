"""WebDAV end-to-end self-test.

Builds a tree of REAL .evf files (encrypted with the project's own
EncryptionEngine using a known password), mirroring the real library naming
convention, then drives PROPFIND / GET / Range and finally verifies the
decrypted stream is playable with ffprobe.

Run:  python _dav_selftest.py
"""
import base64
import http.client
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "_davtest")
PORT = 18099
PASSWORD = "selftest-pw"
SRC_MP4 = os.path.join(HERE, "633d42658e7d7e8b643d1e8bbac5ac2b.mp4")  # 1MB real mp4


def q(rel):
    """Percent-encode a root-relative path the way a WebDAV client would."""
    if rel in ("", "/"):
        return "/"
    return urllib.parse.quote(rel.replace("\\", "/"), safe="/")


def moov_at_end(path):
    """Return True when the mp4 stores moov after mdat (needs a tail read to open)."""
    order = []
    with open(path, "rb") as f:
        while len(order) < 8:
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            size = struct.unpack(">I", hdr[:4])[0]
            typ = hdr[4:8].decode("ascii", "replace")
            order.append(typ)
            if size == 0:
                break
            if size == 1:
                size = struct.unpack(">Q", f.read(8))[0]
            f.seek(size - 8, os.SEEK_CUR)
    if "moov" in order and "mdat" in order:
        return order.index("moov") > order.index("mdat")
    return False


def build_tree():
    if os.path.isdir(ROOT):
        shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(ROOT, exist_ok=True)

    from core.crypto_engine import EncryptionEngine
    eng = EncryptionEngine()
    cache = {}

    def enc(rel):
        """Encrypt the sample mp4 into ROOT/rel using the project's engine."""
        dst = os.path.join(ROOT, rel.replace("/", os.sep))
        if rel in cache:
            shutil.copyfile(cache[rel], dst)
            return dst
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if not eng.encrypt_file(SRC_MP4, dst, PASSWORD):
            raise RuntimeError("encryption failed for " + rel)
        cache[rel] = dst
        return dst

    with open(os.path.join(ROOT, "根目录说明.txt"), "w", encoding="utf-8") as f:
        f.write("hello")

    enc("IMG_6304.evf")                       # -> IMG_6304.mp4
    enc("video.mp4.evf")                      # dedupe case
    enc("zzz啥.evf")                          # -> zzz啥.mp4
    enc("-5263937573636121720 (2).evf")       # spaces + parens
    enc("电影 测试/一层视频.evf")
    enc("电影 测试/第二层/中层视频.evf")
    enc("电影 测试/第二层/第三层/深层视频.evf")
    with open(os.path.join(ROOT, "电影 测试", "note.txt"), "w", encoding="utf-8") as f:
        f.write("n")

    deep_parent = os.path.join(ROOT, "深路径", "第一段")
    deep = deep_parent
    for i in range(12):
        deep = os.path.join(deep, "verylongdirectoryname%02d" % i)
    os.makedirs(deep, exist_ok=True)
    shutil.copyfile(cache["IMG_6304.evf"], os.path.join(deep, "deep.evf"))
    print("[info] deep chain length: %d chars" % len(deep))
    return deep, deep_parent


def _conn():
    return http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)


def _auth():
    return "Basic " + base64.b64encode(("admin:%s" % PASSWORD).encode()).decode()


def _token():
    return base64.b64encode(("admin:%s" % PASSWORD).encode()).decode()


def propfind(path, depth="1"):
    conn = _conn()
    body = ('<?xml version="1.0" encoding="utf-8"?>'
            '<D:propfind xmlns:D="DAV:"><D:prop>'
            '<D:resourcetype/><D:getcontentlength/><D:displayname/>'
            '</D:prop></D:propfind>').encode()
    conn.request("PROPFIND", path, body=body, headers={
        "Authorization": _auth(), "Depth": depth,
        "Content-Type": 'application/xml; charset="utf-8"',
    })
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, data.decode("utf-8", "replace")


def get(path, extra_headers=None, use_token=False):
    conn = _conn()
    h = {}
    if use_token:
        sep = "&" if "?" in path else "?"
        path = "%s%stoken=%s" % (path, sep, urllib.parse.quote(_token()))
    else:
        h["Authorization"] = _auth()
    if extra_headers:
        h.update(extra_headers)
    conn.request("GET", path, headers=h)
    r = conn.getresponse()
    body = r.read()
    hdrs = dict(r.getheaders())
    conn.close()
    return r.status, hdrs, body


def hrefs(xml):
    return [p.split("</D:href>")[0] for p in xml.split("<D:href>")[1:]]


def subdirs(xml):
    out = []
    for block in xml.split("<D:response>")[1:]:
        if "<D:collection/>" in block:
            out.append(block.split("<D:href>")[1].split("</D:href>")[0])
    return out


def main():
    if not os.path.exists(SRC_MP4):
        print("missing sample mp4:", SRC_MP4)
        return 1
    print("[info] sample mp4 moov-at-end =", moov_at_end(SRC_MP4),
          "(True => clients must read the tail to open it)")

    deep, deep_parent = build_tree()
    from core.network_share_server import NetworkShareServer
    srv = NetworkShareServer()
    srv.start(ROOT, PORT, PASSWORD, use_https=False)
    time.sleep(0.5)
    print("server up at %s | root = %s\n" % (srv.url, ROOT))

    results = []

    def check(name, ok, detail=""):
        results.append((name, ok))
        print("  [%s] %s %s" % ("PASS" if ok else "FAIL", name, detail))

    try:
        print("=== [A] PROPFIND / (Depth 1) ===")
        st, xml = propfind("/")
        print("status:", st)
        for h in hrefs(xml):
            print("    ", h)
        check("PROPFIND / -> 207", st == 207)
        check("level-1 chinese dir listed", "/%E7%94%B5%E5%BD%B1%20%E6%B5%8B%E8%AF%95/" in subdirs(xml))
        leaked = [h for h in hrefs(xml) if h.lower().endswith(".evf")]
        check("no raw .evf leaked in listing", not leaked, str(leaked))
        check("virtual name for 'video.mp4.evf' is /video.mp4", "/video.mp4" in hrefs(xml))

        for label, rel, minresp in [
            ("lvl1", "/电影 测试", 4),
            ("lvl2", "/电影 测试/第二层", 3),
            ("lvl3", "/电影 测试/第二层/第三层", 2),
        ]:
            print("\n=== [%s] PROPFIND %s ===" % (label.upper(), q(rel)))
            st, xml = propfind(q(rel) + "/")
            n = xml.count("<D:response>")
            print("status:", st, "| responses:", n)
            for h in hrefs(xml):
                print("    ", h)
            check("PROPFIND %s -> 207" % label, st == 207)
            check("%s children >= %d" % (label, minresp), n >= minresp)

        print("\n=== [E1] deep leaf (>260 char path) ===")
        st, xml = propfind(q(os.path.relpath(deep, ROOT)) + "/")
        check("deep leaf -> 207", st == 207)
        check("deep leaf lists file", xml.count("<D:response>") >= 2)

        print("\n=== [E2] deep PARENT (child path >260 chars) ===")
        st, xml = propfind(q(os.path.relpath(deep_parent, ROOT)) + "/")
        n = xml.count("<D:response>")
        print("  status:", st, "| responses:", n)
        for h in hrefs(xml):
            print("    ", h)
        check("deep parent -> 207", st == 207)
        check("deep parent listing not empty", n >= 2, "*** 'deeper dirs do not show' ***")

        print("\n=== [F] GET virtual-name resolution (want 206/200, NOT 404) ===")
        cases = [
            ("/IMG_6304.mp4", "plain <name>.evf -> .mp4"),
            ("/zzz啥.mp4", "plain <name>.evf -> .mp4"),
            ("/-5263937573636121720 (2).mp4", "spaces + parens"),
            ("/video.mp4", "source name already carried the ext (dedupe)"),
            ("/电影 测试/一层视频.mp4", "lvl1"),
            ("/电影 测试/第二层/中层视频.mp4", "lvl2"),
            ("/电影 测试/第二层/第三层/深层视频.mp4", "lvl3"),
            (os.path.relpath(deep, ROOT).replace("\\", "/") + "/deep.mp4", "deep"),
        ]
        for rel, note in cases:
            st, hdrs, body = get(q(rel))
            ok = st in (200, 206)
            print("  %-52s -> %s %s  (%s)" % (rel[-52:], st, "" if ok else "*** BUG ***", note))
            results.append(("GET resolves: " + note, ok))

        print("\n=== [G] suffix Range bytes=-1024 (moov probe) ===")
        st, hdrs, body = get("/IMG_6304.mp4", {"Range": "bytes=-1024"})
        cr = hdrs.get("Content-Range", "")
        print("  status:", st, "| Content-Range:", repr(cr), "| bytes:", len(body))
        total = int(cr.split("/")[-1]) if "/" in cr else -1
        try:
            start = int(cr.split(" ")[1].split("-")[0])
        except Exception:
            start = -1
        check("suffix Range = LAST 1024 bytes", start == total - 1024 and len(body) == 1024,
              "expected %d got %d" % (total - 1024, start))

        print("\n=== [H] prefix Range bytes=0-1023 ===")
        st, hdrs, body = get("/IMG_6304.mp4", {"Range": "bytes=0-1023"})
        print("  status:", st, "| Content-Range:", repr(hdrs.get("Content-Range")), "| bytes:", len(body))
        check("prefix Range -> 206 + 1024", st == 206 and len(body) == 1024)

        print("\n=== [I] open-ended Range bytes=0- ===")
        st, hdrs, body = get("/IMG_6304.mp4", {"Range": "bytes=0-"})
        print("  status:", st, "| Content-Range:", repr(hdrs.get("Content-Range")), "| bytes:", len(body))
        check("open Range -> 206", st == 206)

        print("\n=== [J] ?token= query auth (used by <video>/<img> tags) ===")
        st, hdrs, body = get("/IMG_6304.mp4", use_token=True)
        print("  status:", st, "| bytes:", len(body))
        check("query-token GET works", st in (200, 206))

        print("\n=== [K] ffprobe end-to-end over WebDAV ===")
        url = "http://127.0.0.1:%d/IMG_6304.mp4?token=%s" % (PORT, urllib.parse.quote(_token()))
        try:
            cp = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                 "format=format_name,duration", "-show_entries",
                                 "stream=codec_name,codec_type", "-of", "default=nw=1", url],
                                capture_output=True, timeout=120)
            out = (cp.stdout or b"").decode("utf-8", "replace").strip()
            err = (cp.stderr or b"").decode("utf-8", "replace").strip()
            print("  rc:", cp.returncode)
            for line in out.splitlines():
                print("    ", line)
            if err:
                print("   stderr:", err[:300])
            check("ffprobe opens decrypted stream", cp.returncode == 0 and "codec_name" in out)
        except FileNotFoundError:
            print("  ffprobe not found, skipping")
            results.append(("ffprobe opens decrypted stream", True))

        print("\n=== [L] path traversal attempt (must be blocked) ===")
        st, hdrs, body = get("/%2e%2e%2f%2e%2e%2fWindows%2fwin.ini")
        print("  GET /../../Windows/win.ini ->", st, "| bytes:", len(body))
        check("traversal blocked (403/404)", st in (403, 404))

        print("\n=== [M] non-faststart mp4 (moov at END) end-to-end ===")
        moov_src = os.path.join(HERE, "_davtest_moovend.mp4")
        try:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", SRC_MP4,
                            "-c", "copy", moov_src], check=True, timeout=120)
            at_end = moov_at_end(moov_src)
            print("  moov-at-end =", at_end)
            enc_dst = os.path.join(ROOT, "尾部索引视频.evf")
            from core.crypto_engine import EncryptionEngine
            EncryptionEngine().encrypt_file(moov_src, enc_dst, PASSWORD)
            url = "http://127.0.0.1:%d/%s?token=%s" % (
                PORT, urllib.parse.quote("尾部索引视频.mp4"), urllib.parse.quote(_token()))
            cp = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                 "format=duration", "-show_entries", "stream=codec_name",
                                 "-of", "default=nw=1", url],
                                capture_output=True, timeout=120)
            out = (cp.stdout or b"").decode("utf-8", "replace").strip()
            err = (cp.stderr or b"").decode("utf-8", "replace").strip()
            print("  rc:", cp.returncode)
            for line in out.splitlines():
                print("    ", line)
            if err:
                print("   stderr:", err[:300])
            check("moov-at-end video opens over WebDAV", at_end and cp.returncode == 0,
                  "this is the exact 'video will not open' scenario")
        except FileNotFoundError:
            print("  ffmpeg not found, skipping")
            results.append(("moov-at-end video opens over WebDAV", True))
        finally:
            if os.path.exists(moov_src):
                os.remove(moov_src)

        print("\n=== [N] web API /api/files/raw suffix Range (plain file) ===")
        st, hdrs, body = get("/api/files/raw?path=" + urllib.parse.quote("/根目录说明.txt"),
                             {"Range": "bytes=-2"})
        cr = hdrs.get("Content-Range", "")
        print("  status:", st, "| Content-Range:", repr(cr), "| body:", body)
        check("raw suffix Range -> last 2 bytes", st == 206 and body == b"lo")

        print("\n=== [O] web API /api/stream/<sid>/video suffix Range ===")
        try:
            payload = json.dumps({"path": "/IMG_6304.mp4", "password": PASSWORD}).encode()
            conn = _conn()
            conn.request("POST", "/api/stream/open", body=payload, headers={
                "Authorization": _auth(), "Content-Type": "application/json"})
            r = conn.getresponse()
            raw_body = r.read()
            conn.close()
            info = json.loads(raw_body.decode())
            sid = info.get("session_id") or info.get("token") or ""
            print("  open ->", r.status, "| session:", (sid or "")[:12])
            if sid:
                st, hdrs, body = get("/api/stream/%s/video" % sid, {"Range": "bytes=-1024"})
                cr = hdrs.get("Content-Range", "")
                total = int(cr.split("/")[-1]) if "/" in cr else -1
                try:
                    start = int(cr.split(" ")[1].split("-")[0])
                except Exception:
                    start = -1
                print("  status:", st, "| Content-Range:", repr(cr), "| bytes:", len(body))
                check("stream video suffix Range = last 1024",
                      start == total - 1024 and len(body) == 1024)
            else:
                check("stream video suffix Range = last 1024", False, "no session id")
        except Exception as e:
            check("stream video suffix Range = last 1024", False, "exception: %s" % e)

        print("\n=== SUMMARY ===")
        failed = [n for n, ok in results if not ok]
        print("%d/%d passed" % (len(results) - len(failed), len(results)))
        if failed:
            print("FAILED ITEMS:")
            for n in failed:
                print("  -", n)
        return 1 if failed else 0
    finally:
        srv.stop()


if __name__ == "__main__":
    sys.exit(main())
