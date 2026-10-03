#!/usr/bin/env python3
"""Self-contained HTTP1 contract for the curl package. Starts a deterministic
local HTTP fixture in-process and drives the package through the Nift binary.
No public internet access is required. The fixture is a test-only dependency;
the production curl package must not require Python.
"""
import base64
import gzip
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse

NIFT = sys.argv[1] if len(sys.argv) > 1 else "nift"
PKG = sys.argv[2] if len(sys.argv) > 2 else "."


class Fixture(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _read_body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(n) if n else b""

    def _send(self, code=200, body=b"ok", ctype="text/plain", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if extra:
            for k, v in extra:
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        # A legal HEAD advertises Content-Length for the would-be body but sends
        # no bytes; `curl -X HEAD` would hang waiting for them, `--head` must not.
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", "5")
        self.end_headers()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/query":
            self._send(200, json.dumps(q, sort_keys=True).encode())
        elif u.path == "/cookies/set":
            self._send(200, b"set", extra=[("Set-Cookie", "session=abc123; Path=/")])
        elif u.path == "/multi-cookie":
            self._send(200, b"multi", extra=[("Set-Cookie", "a=1"), ("Set-Cookie", "b=2"), ("Set-Cookie", "c=3")])
        elif u.path == "/cookies/get":
            self._send(200, (self.headers.get("Cookie", "") or "").encode())
        elif u.path == "/binary":
            self._send(200, bytes(range(256)), "application/octet-stream")
        elif u.path == "/slow":
            time.sleep(3)
            self._send(200, b"slow")
        elif u.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif u.path == "/redirect2":
            self.send_response(302)
            self.send_header("Location", "/redirect")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif u.path == "/status/500":
            self._send(500, b"boom")
        elif u.path == "/status/404":
            self._send(404, b"nope")
        elif u.path == "/auth/basic":
            exp = "Basic " + base64.b64encode(b"u:p").decode()
            self._send(200 if self.headers.get("Authorization") == exp else 401, b"basic")
        elif u.path == "/auth/bearer":
            self._send(200 if self.headers.get("Authorization") == "Bearer tok" else 401, b"bearer")
        elif u.path == "/gzip":
            raw = b"gzipped-content" * 4
            self._send(200, gzip.compress(raw), "text/plain", extra=[("Content-Encoding", "gzip")])
        elif u.path == "/echo":
            hdr = {k.lower(): v for k, v in self.headers.items()}
            self._send(200, json.dumps({
                "method": self.command,
                "x_custom": hdr.get("x-custom", ""),
                "x_session": hdr.get("x-session", ""),
                "user_agent": hdr.get("user-agent", ""),
            }, sort_keys=True).encode())
        else:
            self._send(200, b"get-ok", extra=[("Set-Cookie", "a=1"), ("Set-Cookie", "b=2")])

    def do_POST(self):
        body = self._read_body()
        if self.path == "/form":
            self._send(200, json.dumps(urllib.parse.parse_qs(body.decode()), sort_keys=True).encode())
        elif self.path == "/multipart":
            ok = b'name="field"' in body and b'filename="up.bin"' in body and b"hello-upload-data" in body
            self._send(200, b"multipart-ok" if ok else b"multipart-bad")
        elif self.path == "/echo":
            self._send(200, body)
        elif self.path == "/bytes":
            self._send(200, body, "application/octet-stream")
        else:
            self._send(200, b"posted")

    def do_PUT(self):
        body = self._read_body()
        if self.path == "/upload":
            self._send(200, b"uploaded:" + str(len(body)).encode())
        else:
            self._send(200, body)

    def do_PATCH(self):
        self._send(200, self._read_body())

    def do_DELETE(self):
        self._send(200, b"deleted")

    def log_message(self, *a):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()

work = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".http1-work")
shutil.rmtree(work, ignore_errors=True)
os.makedirs(os.path.join(work, ".nift"), exist_ok=True)
subprocess.run([NIFT, "add", PKG], cwd=work, check=True, capture_output=True)

failures = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'} {name}")
    if not cond:
        failures.append(name)
        if detail:
            print("  " + detail.replace("\n", "\n  "))


def run_script(name, script, env=None, timeout=None):
    path = os.path.join(work, name)
    with open(path, "w") as f:
        f.write(script)
    return subprocess.run(
        [NIFT, name], cwd=work, capture_output=True, text=True,
        env={**os.environ, **(env or {})}, timeout=timeout,
    )


base = f"http://127.0.0.1:{port}"

# ---- 1. verbs, status, headers, effective_url --------------------------------
script = f"""
@import("curl")
base := "{base}"
g := curl.get(base + "/")
print(g.ok)
print(g.status)
print(g.body)
print(g.effective_url)
print(g.headers.get("set-cookie").join(";"))
p := curl.post(base + "/echo", {{"body": "posted-body"}})
print(p.status)
print(p.body)
print(p.method)
print(curl.put(base + "/echo", {{"body": "put-body"}}).body)
print(curl.patch(base + "/echo", {{"body": "patch-body"}}).body)
print(curl.delete(base + "/echo").body)
print(curl.head(base + "/").status)
nf := curl.request(base + "/status/404")
print(nf.ok)
print(nf.status)
print(nf.body)
err := curl.request(base + "/status/500")
print(err.ok)
print(err.status)
"""
out = run_script("t1.f", script)
expected = ["true", "200", "get-ok", base + "/", "a=1;b=2", "200", "posted-body", "POST",
            "put-body", "patch-body", "deleted", "200", "true", "404", "nope", "true", "500"]
lines = out.stdout.strip().splitlines()
check("verbs/status/headers/effective_url", lines == expected, out.stdout + out.stderr)

# ---- 2. headers + query + user agent ----------------------------------------
script = f"""
@import("curl")
base := "{base}"
e := curl.get(base + "/echo", {{"headers": {{"X-Custom": "hello world"}}, "user_agent": "nift-test/1.0"}})
print(e.body)
q := curl.get(base + "/query", {{"query": {{"a": "1", "b": "two words", "c": ["x", "y"]}}}})
print(q.body)
"""
out = run_script("t2.f", script)
lines = out.stdout.strip().splitlines()
check("custom headers + user agent", len(lines) >= 1 and json.loads(lines[0])["x_custom"] == "hello world"
      and json.loads(lines[0])["user_agent"] == "nift-test/1.0", out.stdout + out.stderr)
if len(lines) >= 2:
    parsed = json.loads(lines[1])
    check("query encoding", parsed.get("a") == ["1"] and parsed.get("b") == ["two words"]
          and parsed.get("c") == ["x", "y"], out.stdout + out.stderr)
else:
    check("query encoding", False, out.stdout + out.stderr)

# ---- 3. forms + multipart ----------------------------------------------------
with open(os.path.join(work, "up.bin"), "wb") as f:
    f.write(b"hello-upload-data")
script = f"""
@import("curl")
base := "{base}"
f := curl.post(base + "/form", {{"form": {{"name": "Nift", "note": "a b"}}}})
print(f.body)
m := curl.post(base + "/multipart", {{"multipart": {{"field": "value", "upload": {{"file": "up.bin", "filename": "up.bin"}}}}}})
print(m.body)
"""
out = run_script("t3.f", script)
lines = out.stdout.strip().splitlines()
check("urlencoded form", len(lines) >= 1 and json.loads(lines[0]) == {"name": ["Nift"], "note": ["a b"]},
      out.stdout + out.stderr)
check("multipart upload", len(lines) >= 2 and lines[1] == "multipart-ok", out.stdout + out.stderr)

# ---- 4. auth -----------------------------------------------------------------
script = f"""
@import("curl")
base := "{base}"
print(curl.get(base + "/auth/basic", {{"auth": {{"user": "u", "password": "p"}}}}).status)
print(curl.get(base + "/auth/basic", {{"auth": {{"user": "u", "password": "wrong"}}}}).status)
print(curl.get(base + "/auth/bearer", {{"auth": {{"bearer": "tok"}}}}).status)
print(curl.get(base + "/auth/bearer", {{"authorization": "Bearer tok"}}).status)
print(curl.get(base + "/auth/bearer", {{"authorization": "Bearer nope"}}).status)
"""
out = run_script("t4.f", script)
check("basic + bearer auth", out.stdout.strip().splitlines() == ["200", "401", "200", "200", "401"],
      out.stdout + out.stderr)

# ---- 5. cookies + session ----------------------------------------------------
script = f"""
@import("curl")
base := "{base}"
print(curl.get(base + "/cookies/get", {{"cookies": {{"theme": "dark"}}}}).body)
s := curl.session({{"persist_cookies": true}})
print(curl.get(base + "/cookies/set", {{"session": s}}).status)
print(curl.get(base + "/cookies/get", {{"session": s}}).body)
print(curl.session_close(s).ok)
print(curl.session_close(s).error_code)
"""
out = run_script("t5.f", script)
lines = out.stdout.strip().splitlines()
check("request cookies", len(lines) >= 1 and "theme=dark" in lines[0], out.stdout + out.stderr)
check("session cookie persistence", len(lines) >= 3 and lines[1] == "200" and "session=abc123" in lines[2],
      out.stdout + out.stderr)
check("session close", len(lines) >= 5 and lines[3] == "true" and lines[4] == "invalid_session",
      out.stdout + out.stderr)

# ---- 5b. session lifecycle --------------------------------------------------
script = f"""
@import("curl")
base := "{base}"
s1 := curl.session({{"headers": {{"X-Session": "one"}}}})
s2 := curl.session({{"headers": {{"X-Session": "two"}}}})
print(curl.get(base + "/echo", {{"session": s1}}).body)
print(curl.get(base + "/echo", {{"session": s2}}).body)
print(curl.get(base + "/echo", {{"session": s1, "headers": {{"X-Session": "override"}}}}).body)
caller := curl.session({{"cookie_jar": "jar.txt"}})
curl.get(base + "/cookies/set", {{"session": caller}})
print(curl.get(base + "/cookies/get", {{"session": caller}}).body)
print(curl.session_close(caller).ok)
print(exists("jar.txt"))
"""
out = run_script("t5b.f", script)
lines = out.stdout.strip().splitlines()
check("two sessions isolated", len(lines) >= 2 and json.loads(lines[0])["x_session"] == "one"
      and json.loads(lines[1])["x_session"] == "two", out.stdout + out.stderr)
check("per-request overrides session", len(lines) >= 3 and json.loads(lines[2])["x_session"] == "override",
      out.stdout + out.stderr)
check("caller-owned cookie jar preserved", len(lines) >= 5 and "session=abc123" in lines[3] and lines[4] == "true"
      and os.path.exists(os.path.join(work, "jar.txt")), out.stdout + out.stderr)

# owned session jar is removed by session_close (dedicated TMPDIR)
owned_tmp = os.path.join(work, "owned-tmp")
shutil.rmtree(owned_tmp, ignore_errors=True)
os.makedirs(owned_tmp, exist_ok=True)
script = f'@import("curl")\ns := curl.session({{"persist_cookies": true}})\ncurl.get("{base}/cookies/set", {{"session": s}})\nprint(curl.session_close(s).ok)\n'
path = os.path.join(work, "t5c.f")
with open(path, "w") as f:
    f.write(script)
owned = subprocess.run([NIFT, "t5c.f"], cwd=work, capture_output=True, text=True,
                       env={**os.environ, "TMPDIR": owned_tmp, "TEMP": owned_tmp, "TMP": owned_tmp})
leftovers = os.listdir(owned_tmp)
check("owned session jar removed on close", owned.returncode == 0 and owned.stdout.strip() == "true" and leftovers == [],
      owned.stdout + owned.stderr + "\nleftovers=" + str(leftovers))

# ---- 6. redirects + timeout --------------------------------------------------
script = f"""
@import("curl")
base := "{base}"
r := curl.get(base + "/redirect", {{"follow_redirects": true}})
print(r.status)
print(r.effective_url)
r2 := curl.get(base + "/redirect2", {{"follow_redirects": true, "max_redirects": 5}})
print(r2.status)
r3 := curl.get(base + "/redirect2", {{"follow_redirects": true, "max_redirects": 1}})
print(r3.ok)
print(r3.error_code)
slow := curl.get(base + "/slow", {{"timeout": 1}})
print(slow.ok)
print(slow.error_code)
"""
out = run_script("t6.f", script)
lines = out.stdout.strip().splitlines()
check("follow redirects + effective_url", len(lines) >= 2 and lines[0] == "200" and lines[1] == base + "/",
      out.stdout + out.stderr)
check("max_redirects success", len(lines) >= 3 and lines[2] == "200", out.stdout + out.stderr)
check("max_redirects exceeded is transport failure", len(lines) >= 5 and lines[3] == "false" and lines[4] == "transport_failure",
      out.stdout + out.stderr)
check("timeout maps to timeout", len(lines) >= 7 and lines[5] == "false" and lines[6] == "timeout",
      out.stdout + out.stderr)

# ---- 7. binary response + request -------------------------------------------
script = f"""
@import("curl")
base := "{base}"
b := curl.get(base + "/binary", {{"binary": true}})
print(type(b.body_bytes))
print(b.body_bytes.length())
print(b.body_bytes[0])
print(b.body_bytes[255])
print(b.body == null)
payload := bytes([0, 1, 2, 254, 255])
echo := curl.post(base + "/bytes", {{"body": payload, "binary": true}})
print(echo.body_bytes.length())
print(echo.body_bytes[4])
"""
out = run_script("t7.f", script)
lines = out.stdout.strip().splitlines()
check("binary response bytes", len(lines) >= 5 and lines[0] == "bytes" and lines[1] == "256"
      and lines[2] == "0" and lines[3] == "255" and lines[4] == "true", out.stdout + out.stderr)
check("binary request body", len(lines) >= 7 and lines[5] == "5" and lines[6] == "255", out.stdout + out.stderr)

# ---- 8. download + upload ----------------------------------------------------
script = f"""
@import("curl")
base := "{base}"
d := curl.download(base + "/binary", "down.bin")
print(d.ok)
print(d.body == null)
print(d.output)
u := curl.upload(base + "/upload", "up.bin")
print(u.status)
print(u.body)
"""
out = run_script("t8.f", script)
lines = out.stdout.strip().splitlines()
check("download to file", len(lines) >= 3 and lines[0] == "true" and lines[1] == "true" and lines[2] == "down.bin",
      out.stdout + out.stderr)
down = os.path.join(work, "down.bin")
check("download bytes are exact", os.path.exists(down) and open(down, "rb").read() == bytes(range(256)),
      out.stdout + out.stderr)
check("upload file", len(lines) >= 5 and lines[3] == "200" and lines[4] == "uploaded:17", out.stdout + out.stderr)

# ---- 9. compression ----------------------------------------------------------
script = f"""
@import("curl")
base := "{base}"
r := curl.get(base + "/gzip", {{"compressed": true}})
print(r.status)
print(r.body)
"""
out = run_script("t9.f", script)
lines = out.stdout.strip().splitlines()
check("compressed transfer decoded", len(lines) >= 2 and lines[0] == "200" and "gzipped-content" in lines[1],
      out.stdout + out.stderr)

# ---- 10. capabilities --------------------------------------------------------
script = """
@import("curl")
c := curl.capabilities()
print(c.streaming)
print(c.websocket)
print(c.sessions)
print(c.multipart)
print(c.binary)
print(type(c.http2))
print(type(c.brotli))
print(c.https == c.tls)
print(curl.version().contains("curl"))
print(curl.features().contains("Protocols"))
print(curl.backend())
"""
out = run_script("t10.f", script)
lines = out.stdout.strip().splitlines()
check("capabilities truthful", lines == ["false", "false", "true", "true", "true", "bool", "bool", "true", "true", "true", "process"],
      out.stdout + out.stderr)

# ---- 11. error model: unavailable backend -----------------------------------
script = f"""
@import("curl")
r := curl.get("{base}/")
print(r.ok)
print(r.error_code)
"""
path = os.path.join(work, "t11.f")
with open(path, "w") as f:
    f.write(script)
np = subprocess.run([NIFT, "t11.f", "--no-process"], cwd=work, capture_output=True, text=True)
check("--no-process structured failure", np.stdout.strip().splitlines() == ["false", "backend_unavailable"],
      np.stdout + np.stderr)

# ---- 12. fixed-defect regressions -------------------------------------------
script = f"""
@import("curl")
base := "{base}"
h := curl.head(base + "/")
print(h.status)
print(h.body == null)
mc := curl.get(base + "/multi-cookie")
print(mc.headers.get("set-cookie").size())
print(mc.headers.get("set-cookie").join("|"))
q := curl.get(base + "/query", {{"query": {{"a": "1"}}}})
print(q.url.contains("?a=1"))
inj := curl.get(base + "/", {{"headers": {{"X-Custom": "v\\r\\nX-Evil: 1"}}}})
print(inj.ok)
print(inj.error_code)
bad := curl.request(base + "/", {{"method": "POST", "session": {{"kind": "curl_session", "_session_id": 99999}}}})
print(bad.method)
"""
out = run_script("t13.f", script, timeout=30)
lines = out.stdout.strip().splitlines()
check("HEAD with content-length completes", len(lines) >= 2 and lines[0] == "200" and lines[1] == "true",
      out.stdout + out.stderr)
check("repeated Set-Cookie preserved", len(lines) >= 4 and lines[2] == "3" and lines[3] == "a=1|b=2|c=3",
      out.stdout + out.stderr)
check("response.url includes query", len(lines) >= 5 and lines[4] == "true", out.stdout + out.stderr)
check("CRLF header injection rejected", len(lines) >= 7 and lines[5] == "false" and lines[6] == "invalid_header",
      out.stdout + out.stderr)
check("early failure reports intended method", len(lines) >= 8 and lines[7] == "POST", out.stdout + out.stderr)

# ---- 13. safe inspection under --no-process ---------------------------------
script = ('@import("curl")\n'
          'print("v=[" + curl.version() + "]")\n'
          'print("f=[" + curl.features() + "]")\n'
          'print(curl.capabilities().streaming)\n'
          'print(curl.capabilities().http2)\n')
path = os.path.join(work, "t14.f")
with open(path, "w") as f:
    f.write(script)
noproc = subprocess.run([NIFT, "t14.f", "--no-process"], cwd=work, capture_output=True, text=True)
check("inspection safe under --no-process", noproc.returncode == 0
      and noproc.stdout.strip().splitlines() == ["v=[]", "f=[]", "false", "false"], noproc.stdout + noproc.stderr)

# ---- 14. temporary fallback with TMPDIR/TEMP/TMP unset ----------------------
curl_path = shutil.which("curl")
if curl_path is not None:
    only = os.path.join(work, "curl-only2")
    os.makedirs(only, exist_ok=True)
    exposed = os.path.join(only, "curl.exe" if os.name == "nt" else "curl")
    try:
        os.symlink(curl_path, exposed)
    except (OSError, NotImplementedError):
        shutil.copy2(curl_path, exposed)
    script = f'@import("curl")\nprint(curl.get("{base}/").body)\n'
    path = os.path.join(work, "t15.f")
    with open(path, "w") as f:
        f.write(script)
    env = {k: v for k, v in os.environ.items() if k not in ("TMPDIR", "TEMP", "TMP")}
    env["PATH"] = only
    fallback = subprocess.run([NIFT, "t15.f"], cwd=work, capture_output=True, text=True, env=env)
    check("temporary fallback with TMPDIR unset", fallback.returncode == 0 and fallback.stdout.strip() == "get-ok",
          fallback.stdout + fallback.stderr)

# ---- 15. adversarial ---------------------------------------------------------
script = f"""
@import("curl")
base := "{base}"
refused := curl.get("http://127.0.0.1:1/")
print(refused.ok)
print(refused.error_code)
bad := curl.get("not-a-url")
print(bad.ok)
print(bad.error_code)
missing := curl.post(base + "/echo", {{"body_file": "does-not-exist.bin"}})
print(missing.ok)
print(missing.error_code)
print(curl.request(base + "/", {{"session": {{"kind": "curl_session", "_session_id": 99999}}}}).error_code)
print(curl.session_close({{"kind": "curl_session", "_session_id": 99999}}).error_code)
empty := curl.post(base + "/bytes", {{"body": bytes(), "binary": true}})
print(empty.status)
print(empty.body_bytes.length())
"""
out = run_script("t12.f", script)
lines = out.stdout.strip().splitlines()
check("connection refused structured", len(lines) >= 2 and lines[0] == "false" and lines[1] == "transport_failure",
      out.stdout + out.stderr)
check("malformed url structured", len(lines) >= 4 and lines[2] == "false" and lines[3] == "transport_failure",
      out.stdout + out.stderr)
check("missing body file is file_error", len(lines) >= 6 and lines[4] == "false" and lines[5] == "file_error",
      out.stdout + out.stderr)
check("invalid session handle", len(lines) >= 8 and lines[6] == "invalid_session" and lines[7] == "invalid_session",
      out.stdout + out.stderr)
check("empty binary body", len(lines) >= 10 and lines[8] == "200" and lines[9] == "0", out.stdout + out.stderr)

server.shutdown()
if failures:
    print("FAILED:", ", ".join(failures))
    sys.exit(1)
print("PASS curl HTTP1 contract")
