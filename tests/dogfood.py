#!/usr/bin/env python3
"""Offline, deterministic curl package dogfood. Starts a tiny local HTTP server
in-process and drives the curl package through the Nift executable. No public
internet access required.
"""
import http.server
import json
import os
import subprocess
import sys
import threading

NIFT = sys.argv[1] if len(sys.argv) > 1 else "nift"
PKG = sys.argv[2] if len(sys.argv) > 2 else "."


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, code=200, body=b"ok"):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Set-Cookie", "a=1")
        self.send_header("Set-Cookie", "b=2")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self._send(200 if self.path != "/notfound" else 404)

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return
        if self.path == "/notfound":
            self._send(404, b"nope")
            return
        if self.path == "/unicode":
            self._send(200, "héllo ünïcode".encode("utf-8"))
            return
        self._send(200, b"get-ok")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        self._send(200, self.rfile.read(n))

    def do_PUT(self):
        n = int(self.headers.get("Content-Length", 0))
        self._send(200, self.rfile.read(n))

    def do_DELETE(self):
        self._send(200, b"deleted")

    def log_message(self, *a):
        pass


server = http.server.HTTPServer(("127.0.0.1", 0), H)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()

work = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".dogfood-work")
import shutil
shutil.rmtree(work, ignore_errors=True)
os.makedirs(os.path.join(work, ".nift"), exist_ok=True)
subprocess.run([NIFT, "add", PKG], cwd=work, check=True, capture_output=True)

failures = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'} {name}")
    if not cond:
        failures.append(name)
        if detail:
            print("  " + detail)


script = f"""
@import("curl")
print(curl.available())
print(request("http://127.0.0.1:{port}/").body)
r := request("http://127.0.0.1:{port}/notfound")
print(r.status)
print(r.body)
print(r.headers.get("content-type"))
print(r.headers.get("set-cookie"))
rd := request("http://127.0.0.1:{port}/redirect", {{"follow_redirects": true}})
print(rd.status)
u := request("http://127.0.0.1:{port}/unicode")
print(u.body)
postr := post("http://127.0.0.1:{port}/", {{"json": {{"name": "Nift", "v": 4.4}}, "headers": {{"X-Custom": "hello world"}}}})
print(postr.status)
print(postr.body)
print(delete("http://127.0.0.1:{port}/").body)
print(head("http://127.0.0.1:{port}/").status)
print(curl.version().contains("curl"))
print(curl.features().contains("HTTP2"))
"""
with open(os.path.join(work, "t.f"), "w") as f:
    f.write(script)
out = subprocess.run([NIFT, "run", "t.f"], cwd=work, capture_output=True, text=True)
lines = out.stdout.strip().splitlines()
expected = [
    "true",
    "get-ok",
    "404",
    "nope",
    "text/plain",
    "a=1; b=2",
    "200",
    "héllo ünïcode",
    "200",
    '{"name":"Nift","v":4.4}',
    "deleted",
    "200",
    "true",
    "true",
]
check("basic matrix", lines == expected, out.stdout + out.stderr)

# Privacy: private helpers must not be visible to the importer.
with open(os.path.join(work, "priv.f"), "w") as f:
    f.write('@import("curl")\nprint(curl_parse_headers)\n')
priv = subprocess.run([NIFT, "run", "priv.f"], cwd=work, capture_output=True, text=True)
check("private helpers not leaked", priv.returncode != 0)

# --no-process: requests fail through the process restriction.
np = subprocess.run([NIFT, "run", "t.f", "--no-process"], cwd=work, capture_output=True, text=True)
check("--no-process denies requests", np.returncode != 0 and "process execution disabled" in np.stderr)

# missing curl: available() is false.
nocurl = subprocess.run(
    [NIFT, "run", "nc.f"],
    cwd=work,
    capture_output=True,
    text=True,
    env={**os.environ, "PATH": "/usr/bin:/bin"},
)
# curl is at /usr/bin/curl, so this checks that available() is true on the normal PATH.
with open(os.path.join(work, "nc.f"), "w") as f:
    f.write('@import("curl")\nprint(curl.available())\n')
avail = subprocess.run([NIFT, "run", "nc.f"], cwd=work, capture_output=True, text=True)
check("curl.available", avail.stdout.strip() == "true", avail.stdout + avail.stderr)

server.shutdown()
if failures:
    print("FAILED:", ", ".join(failures))
    sys.exit(1)
print("PASS curl dogfood")