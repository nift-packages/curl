#!/usr/bin/env python3
"""Deterministic option-construction and scratch-file tests for the curl
package. Uses a fake `curl` executable that records its argv, so option mapping
(proxy, TLS, timeouts, HTTP version, auth, etc.) is asserted without any
network access. The fake is test-only; the production package has no Python
dependency.
"""
import json
import os
import shutil
import subprocess
import sys

NIFT = sys.argv[1] if len(sys.argv) > 1 else "nift"
PKG = sys.argv[2] if len(sys.argv) > 2 else "."


def write_fake_curl(bin_dir, body):
    """Create a fake `curl` discoverable by Nift's which() on every platform."""
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

import tempfile
# Keep the work directory OUTSIDE the package root (see dogfood.py): a work dir
# nested inside the package recurses on Windows where local packages are copied.
work = tempfile.mkdtemp(prefix="curl-options-")
os.makedirs(os.path.join(work, ".nift"), exist_ok=True)
subprocess.run([NIFT, "add", PKG], cwd=work, check=True, capture_output=True)

fake_bin = os.path.join(work, "fake-bin")
os.makedirs(fake_bin, exist_ok=True)
log = os.path.join(work, "argv.log")
tmpdir = os.path.join(work, "tmp")
os.makedirs(tmpdir, exist_ok=True)
write_fake_curl(fake_bin, '''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CURL_LOG"], "a") as fh:
    fh.write(json.dumps(args) + "\\n")
if "--version" in args:
    sys.stdout.write("curl 8.0.0 (fake) libcurl/8.0.0\\nProtocols: http https\\nFeatures: HTTP2 brotli zstd\\n")
    sys.exit(0)
def val(flag):
    return args[args.index(flag) + 1] if flag in args else None
h = val("-D"); o = val("-o")
if h:
    open(h, "w").write("HTTP/1.1 200 OK\\r\\nContent-Type: text/plain\\r\\nSet-Cookie: a=1\\r\\nSet-Cookie: b=2\\r\\nSet-Cookie: c=3\\r\\n\\r\\n")
if o:
    open(o, "w").write("fake-body")
sys.stdout.write("200\\thttp://fake/effective")
''')

env = {**os.environ, "PATH": fake_bin, "TMPDIR": tmpdir, "TEMP": tmpdir, "TMP": tmpdir, "FAKE_CURL_LOG": log}

failures = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'} {name}")
    if not cond:
        failures.append(name)
        if detail:
            print("  " + detail.replace("\n", "\n  "))


def run_case(name, script, pairs=(), flags=(), absent=(), url_contains=None):
    open(log, "w").close()
    path = os.path.join(work, "case.f")
    with open(path, "w") as f:
        f.write('@import("curl")\n' + script + "\n")
    out = subprocess.run([NIFT, "case.f"], cwd=work, capture_output=True, text=True, encoding="utf-8", env=env)
    argv = []
    with open(log) as f:
        for line in f:
            line = line.strip()
            if line:
                argv.append(json.loads(line))
    last = argv[-1] if argv else []
    ok = out.returncode == 0
    detail = out.stdout + out.stderr + "\nargv=" + json.dumps(last)
    for flag, value in pairs:
        found = any(last[i] == flag and i + 1 < len(last) and last[i + 1] == value for i in range(len(last)))
        if not found:
            ok = False
    for flag in flags:
        if flag not in last:
            ok = False
    for flag in absent:
        if flag in last:
            ok = False
    if url_contains is not None:
        url = last[last.index("--") + 1] if "--" in last else ""
        if url_contains not in url:
            ok = False
    check(name, ok, detail)


run_case("proxy + user agent", 'print(curl.get("http://fake/", {"proxy": "http://proxy:3128", "user_agent": "nift/1.0"}).status)',
         pairs=[("-x", "http://proxy:3128"), ("-A", "nift/1.0")])
run_case("custom CA path", 'print(curl.get("https://fake/", {"cacert": "ca.pem", "capath": "/etc/ssl/certs"}).status)',
         pairs=[("--cacert", "ca.pem"), ("--capath", "/etc/ssl/certs")])
run_case("client cert + key", 'print(curl.get("https://fake/", {"cert": "c.pem", "key": "c.key"}).status)',
         pairs=[("--cert", "c.pem"), ("--key", "c.key")])
run_case("insecure is opt-in only", 'print(curl.get("https://fake/").status)',
         absent=["-k"])
run_case("insecure when requested", 'print(curl.get("https://fake/", {"insecure": true}).status)',
         flags=["-k"])
run_case("explicit http version", 'print(curl.get("http://fake/", {"http_version": "2"}).status)',
         flags=["--http2"])
run_case("http 1.1 selection", 'print(curl.get("http://fake/", {"http_version": "1.1"}).status)',
         flags=["--http1.1"])
run_case("connect + total timeout", 'print(curl.get("http://fake/", {"timeout": 30, "connect_timeout": 5}).status)',
         pairs=[("--max-time", "30"), ("--connect-timeout", "5")])
run_case("max redirects", 'print(curl.get("http://fake/", {"follow_redirects": true, "max_redirects": 3}).status)',
         pairs=[("--max-redirs", "3")], flags=["-L"])
run_case("raw authorization", 'print(curl.get("http://fake/", {"authorization": "Bearer tok"}).status)',
         pairs=[("-H", "Authorization: Bearer tok")])
run_case("basic auth", 'print(curl.get("http://fake/", {"auth": {"user": "u", "password": "p"}}).status)',
         pairs=[("-u", "u:p")])
run_case("bearer auth", 'print(curl.get("http://fake/", {"auth": {"bearer": "tok"}}).status)',
         pairs=[("-H", "Authorization: Bearer tok")])
run_case("query encoding", 'print(curl.get("http://fake/", {"query": {"a": "b c"}}).status)',
         url_contains="a=b%20c")
run_case("form encoding", 'print(curl.post("http://fake/", {"form": {"a": "b c"}}).status)',
         pairs=[("--data-urlencode", "a=b c")])
run_case("multipart file", 'print(curl.post("http://fake/", {"multipart": {"f": {"file": "x.bin", "filename": "x.bin"}}}).status)',
         pairs=[("-F", "f=@x.bin;filename=x.bin")])
run_case("upload method", 'print(curl.upload("http://fake/", "x.bin").status)',
         pairs=[("-T", "x.bin"), ("-X", "PUT")])
run_case("download output", 'print(curl.download("http://fake/", "out.bin").status)',
         pairs=[("-o", "out.bin")])
run_case("compressed", 'print(curl.get("http://fake/", {"compressed": true}).status)',
         flags=["--compressed"])
run_case("CRLF cookie rejected", 'print(curl.get("http://fake/", {"cookies": {"a": "b\\r\\nX-Evil: 1"}}).error_code)',
         absent=["-H"])

# ---- scratch-file cleanup ---------------------------------------------------
open(log, "w").close()
script = """
@import("curl")
print(curl.get("http://fake/").status)
print(curl.post("http://fake/", {"body": "text"}).status)
print(curl.post("http://fake/", {"body": bytes([1,2,3])}).status)
print(curl.get("http://fake/", {"binary": true}).status)
print(curl.post("http://fake/", {"multipart": {"f": "v"}}).status)
print(curl.get("http://fake/", {"output": "keep.bin"}).status)
print(curl.get("http://fake/", {"headers": {"X-Custom": "v"}}).status)
"""
path = os.path.join(work, "cleanup.f")
with open(path, "w") as f:
    f.write(script)
out = subprocess.run([NIFT, "cleanup.f"], cwd=work, capture_output=True, text=True, encoding="utf-8", env=env)
leftovers = [n for n in os.listdir(tmpdir) if n.startswith(".nift-curl-") and n.endswith(".tmp")]
check("scratch temp files cleaned up", out.returncode == 0 and leftovers == [],
      out.stdout + out.stderr + "\nleftovers=" + str(leftovers))
check("user output file preserved", os.path.exists(os.path.join(work, "keep.bin")))

# transport failure must also clean up scratch files
open(log, "w").close()
# Make the fake curl exit nonzero for the next request by flipping a sentinel.
sentinel = os.path.join(work, "fail.flag")
with open(sentinel, "w") as f:
    f.write("1")
write_fake_curl(fake_bin, '''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CURL_LOG"], "a") as fh:
    fh.write(json.dumps(args) + "\\n")
if "--version" in args:
    sys.stdout.write("curl 8.0.0 (fake)\\nProtocols: http https\\nFeatures: HTTP2\\n")
    sys.exit(0)
if os.path.exists(%r):
    sys.stderr.write("curl: (7) Failed to connect\\n")
    sys.exit(7)
h = args[args.index("-D") + 1] if "-D" in args else None
o = args[args.index("-o") + 1] if "-o" in args else None
if h:
    open(h, "w").write("HTTP/1.1 200 OK\\r\\n\\r\\n")
if o:
    open(o, "w").write("body")
sys.stdout.write("200\\thttp://fake/effective")
''' % sentinel)
with open(os.path.join(work, "fail.f"), "w") as f:
    f.write('@import("curl")\nprint(curl.get("http://fake/").error_code)\n')
out = subprocess.run([NIFT, "fail.f"], cwd=work, capture_output=True, text=True, encoding="utf-8", env=env)
leftovers = [n for n in os.listdir(tmpdir) if n.startswith(".nift-curl-") and n.endswith(".tmp")]
check("scratch temp files cleaned after transport failure",
      out.returncode == 0 and out.stdout.strip() == "transport_failure" and leftovers == [],
      out.stdout + out.stderr + "\nleftovers=" + str(leftovers))

if failures:
    print("FAILED:", ", ".join(failures))
    sys.exit(1)
print("PASS curl option construction")
