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


def write_fake_curl(bin_dir, body):
    """Create a fake `curl` discoverable by Nift's which() on every platform.
    POSIX uses a shebang script; Windows uses a .cmd wrapper (a bare Python
    script named curl.exe is not a valid PE and would never execute)."""
    py = os.path.join(bin_dir, "fake_curl.py")
    with open(py, "w") as f:
        f.write(body)
    if os.name == "nt":
        cmd = os.path.join(bin_dir, "curl.cmd")
        with open(cmd, "w") as f:
            f.write('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, py))
        return cmd
    sh = os.path.join(bin_dir, "curl")
    with open(sh, "w") as f:
        f.write("#!%s\n" % sys.executable)
        f.write(body)
    os.chmod(sh, 0o755)
    return sh


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

    def do_PATCH(self):
        n = int(self.headers.get("Content-Length", 0))
        self._send(200, self.rfile.read(n))

    def do_DELETE(self):
        self._send(200, b"deleted")

    def log_message(self, *a):
        pass


server = http.server.HTTPServer(("127.0.0.1", 0), H)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()

import shutil
import tempfile
# Keep the work directory OUTSIDE the package root. On Windows, a local package
# is staged by copying (directory symlinks are unavailable), and a work dir
# nested inside the package would recurse into itself.
work = tempfile.mkdtemp(prefix="curl-dogfood-")
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
print(curl.backends().join(","))
print(curl.backend())
print(curl.use_backend("process").ok)
print(curl.get("http://127.0.0.1:{port}/").body)
r := curl.request("http://127.0.0.1:{port}/notfound")
print(r.status)
print(r.body)
print(r.headers.get("content-type")[0])
print(r.headers.get("set-cookie").join(";"))
rd := curl.request("http://127.0.0.1:{port}/redirect", {{"follow_redirects": true}})
print(rd.status)
print(rd.headers.get("content-type")[0])
u := curl.request("http://127.0.0.1:{port}/unicode")
print(u.body)
postr := curl.post("http://127.0.0.1:{port}/", {{"json": {{"name": "Nift", "v": 4.4}}, "headers": {{"X-Custom": "hello world"}}}})
print(postr.status)
print(postr.body)
print(curl.put("http://127.0.0.1:{port}/", {{"json": {{"method": "put"}}}}).body)
print(curl.patch("http://127.0.0.1:{port}/", {{"json": {{"method": "patch"}}}}).body)
print(curl.delete("http://127.0.0.1:{port}/").body)
print(curl.head("http://127.0.0.1:{port}/").status)
print(curl.capabilities().streaming)
print(curl.version().contains("curl"))
saved := curl.get("http://127.0.0.1:{port}/", {{"output": "download.bin"}})
print(saved.body == null)
print(saved.output)
print(curl.use_backend("auto").error_code)
print(curl.request("http://127.0.0.1:{port}/").status)
setenv("PATH", pwd() + "/empty-path")
print(curl.backend())
"""
with open(os.path.join(work, "t.f"), "w") as f:
    f.write(script)
out = subprocess.run([NIFT, "t.f"], cwd=work, capture_output=True, text=True, encoding="utf-8")
lines = out.stdout.strip().splitlines()
expected = [
    "true",
    "process",
    "process",
    "true",
    "get-ok",
    "404",
    "nope",
    "text/plain",
    "a=1;b=2",
    "200",
    "text/plain",
    "héllo ünïcode",
    "200",
    '{"name":"Nift","v":4.4}',
    '{"method":"put"}',
    '{"method":"patch"}',
    "deleted",
    "200",
    "false",
    "true",
    "true",
    "download.bin",
    "backend_locked",
    "200",
    "process",
]
check("basic matrix", lines == expected, out.stdout + out.stderr)
check("output file is not re-buffered", open(os.path.join(work, "download.bin"), "rb").read() == b"get-ok")

# Privacy: private helpers must not be visible to the importer.
with open(os.path.join(work, "priv.f"), "w") as f:
    f.write('@import("curl")\nprint(curl.parse_headers(""))\n')
priv = subprocess.run([NIFT, "priv.f"], cwd=work, capture_output=True, text=True, encoding="utf-8")
check("private methods not leaked", priv.returncode != 0)

# The deprecated v0.x top-level aliases are no longer exported; only the `curl`
# facade is. Each of these member-free names must be an unknown value.
for alias_name in ["request", "get", "post", "put", "patch", "delete", "head"]:
    with open(os.path.join(work, "alias.f"), "w") as f:
        f.write(f'@import("curl")\nprint({alias_name}("http://127.0.0.1:{port}/"))\n')
    gone = subprocess.run([NIFT, "alias.f"], cwd=work, capture_output=True, text=True, encoding="utf-8")
    check(f"deprecated top-level alias {alias_name} removed", gone.returncode != 0, gone.stdout + gone.stderr)

# Fresh and copied facades share package-global backend/temp state. Consumer
# bindings matching implementation globals and every method parameter name
# must not shadow the methods' captured module bindings or call parameters.
fake_bin = os.path.join(work, "fake-bin")
shared_temp = os.path.join(work, "shared-temp")
os.makedirs(fake_bin, exist_ok=True)
os.makedirs(shared_temp, exist_ok=True)
fake_log = os.path.join(work, "fake-curl.log")
write_fake_curl(fake_bin, '''
import os
import sys

args = sys.argv[1:]
header = args[args.index("-D") + 1]
output = args[args.index("-o") + 1]
with open(os.environ["FAKE_CURL_LOG"], "a") as log:
    log.write(os.path.basename(header) + "," + os.path.basename(output) + "\\n")
with open(header, "w") as response_headers:
    response_headers.write("HTTP/1.1 200 OK\\r\\nContent-Type: text/plain\\r\\n\\r\\n")
with open(output, "w") as response_body:
    response_body.write("fake-ok")
sys.stdout.write("200")
''')
with open(os.path.join(work, "shared-state.f"), "w") as f:
    f.write('''curl_backend_requested := "native"
curl_backend_locked := true
curl_backend_selected := "hijacked"
curl_temp_seq := 900
content := "hijacked"
text := "hijacked"
v := "hijacked"
headers := "hijacked"
args := "hijacked"
url := "hijacked"
rest := "hijacked"
opts := "hijacked"
method := "hijacked"
i := "hijacked"
@import("curl")
fresh := curl()
copy := curl
print(fresh.use_backend("process").ok)
print(curl.get("http://fake/exported").body)
print(fresh.get("http://fake/fresh").body)
print(copy.get("http://fake/copy").body)
print(fresh.use_backend("auto").error_code)
print(copy.backend())
''')
shared = subprocess.run(
    [NIFT, "shared-state.f"],
    cwd=work,
    capture_output=True,
    text=True, encoding="utf-8",
    env={
        **os.environ,
        "PATH": fake_bin,
        "TMPDIR": shared_temp,
        "TEMP": shared_temp,
        "TMP": shared_temp,
        "FAKE_CURL_LOG": fake_log,
    },
)
shared_expected = ["true", "fake-ok", "fake-ok", "fake-ok", "backend_locked", "process"]
sequence_expected = [
    ".nift-curl-1.tmp,.nift-curl-2.tmp",
    ".nift-curl-3.tmp,.nift-curl-4.tmp",
    ".nift-curl-5.tmp,.nift-curl-6.tmp",
]
sequence = []
if os.path.exists(fake_log):
    with open(fake_log) as f:
        sequence = f.read().strip().splitlines()
check(
    "fresh/copy shared state and lexical isolation",
    shared.returncode == 0 and shared.stdout.strip().splitlines() == shared_expected and sequence == sequence_expected,
    shared.stdout + shared.stderr + "\n" + "\n".join(sequence),
)

# --no-process: package reports backend unavailability without invoking run().
with open(os.path.join(work, "np.f"), "w") as f:
    f.write(f'@import("curl")\nr := curl.get("http://127.0.0.1:{port}/")\nprint(r.error_code)\n')
np = subprocess.run([NIFT, "np.f", "--no-process"], cwd=work, capture_output=True, text=True, encoding="utf-8")
check("--no-process is structured", np.returncode == 0 and np.stdout.strip() == "backend_unavailable", np.stdout + np.stderr)

with open(os.path.join(work, "nc.f"), "w") as f:
    f.write('@import("curl")\nprint(curl.available())\nprint(curl.backends().size())\nr := curl.get("http://example.invalid")\nprint(r.error_code)\n')
missing_path = os.path.join(work, "empty-path")
os.makedirs(missing_path, exist_ok=True)
nocurl = subprocess.run([NIFT, "nc.f"], cwd=work, capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PATH": missing_path})
check("missing curl is structured", nocurl.returncode == 0 and nocurl.stdout.strip().splitlines() == ["false", "0", "backend_unavailable"], nocurl.stdout + nocurl.stderr)

with open(os.path.join(work, "available.f"), "w") as f:
    f.write('@import("curl")\nprint(curl.available())\n')
avail = subprocess.run([NIFT, "available.f"], cwd=work, capture_output=True, text=True, encoding="utf-8")
check("curl.available", avail.stdout.strip() == "true", avail.stdout + avail.stderr)

# A process-only PATH exercises the checked package-local temporary fallback.
curl_path = shutil.which("curl")
if curl_path is not None:
    curl_only = os.path.join(work, "curl-only-path")
    os.makedirs(curl_only, exist_ok=True)
    exposed_curl = os.path.join(curl_only, "curl.exe" if os.name == "nt" else "curl")
    try:
        os.symlink(curl_path, exposed_curl)
    except (OSError, NotImplementedError):
        shutil.copy2(curl_path, exposed_curl)
    fallback = subprocess.run(
        [NIFT, "t.f"],
        cwd=work,
        capture_output=True,
        text=True, encoding="utf-8",
        env={**os.environ, "PATH": curl_only, "TMPDIR": work, "TEMP": work, "TMP": work},
    )
    check("temporary-file fallback", fallback.returncode == 0 and fallback.stdout.strip().splitlines() == expected, fallback.stdout + fallback.stderr)

server.shutdown()
if failures:
    print("FAILED:", ", ".join(failures))
    sys.exit(1)
print("PASS curl dogfood")
