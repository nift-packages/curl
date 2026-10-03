# curl

HTTP client package for Nift.

Runtime dependency: the `curl` executable on `PATH`. Nift itself carries no
libcurl/TLS/networking dependency; the package drives the user's `curl`
through Nift's structured process API (argv, never shell concatenation).

## API

```text
@import("curl")

response := curl.get("https://example.com")
print(response.status)
print(response.body)
```

`curl.request(url, options?)` returns an ordinary Nift object:

```text
response.ok           // true for any HTTP response (including 4xx/5xx); false on transport failure
response.status       // HTTP status code (int)
response.headers      // object; every field value is an array
response.body         // buffered text body, or null when output/binary is used or on failure
response.body_bytes   // bytes value when options.binary is true, else null
response.output       // selected output path, otherwise null
response.url          // requested URL (after query merging)
response.effective_url// final URL after redirects (from curl %{url_effective})
response.method       // effective HTTP method
response.error        // stable human-readable failure, else ""
response.error_code   // stable package error code, else ""
response.backend      // concrete backend used (currently "process")
response.exit_code    // process diagnostic; do not use for portable control flow
```

The package facade owns the convenience verbs:

```text
curl.get(url, opts?) / curl.post / curl.put / curl.patch / curl.delete / curl.head
curl.download(url, path, opts?)   // GET to a file; response.body is null
curl.upload(url, path, opts?)     // PUT a file; method defaults to PUT
```

The direct `request`, `get`, `post`, `put`, `patch`, `delete` and `head` exports
remain temporarily as deprecated v0.x compatibility aliases. New code should
use the `curl` facade so imports do not claim generic caller bindings.

Backend selection and facility inspection live on `curl`:

```text
print(curl.available())
print(curl.backends())       // ["process"] when usable
print(curl.backend())        // "process", or null when unavailable
print(curl.use_backend("process").ok)
print(curl.capabilities())
print(curl.version())
print(curl.features())
```

`curl.capabilities()` reports both what the facade supports and the installed
`curl` build's real flags (derived from `curl --version`, so they are truthful
when the executable is absent):

```text
buffered output_file binary multipart forms cookies sessions redirects
timeouts auth proxy tls_controls      // package-level
tls https http2 http3 brotli zstd compression ipv6 unix_sockets  // from curl --version
streaming websocket                   // false: not implemented
```

## Options

All options are optional. `method` defaults to `GET` (or `POST` when a body,
form or multipart is supplied; `PUT` for `upload`).

```text
method: "POST"
headers: {"X-Custom": "v"}      // values may be strings or arrays
query: {"q": "a b", "tag": ["x","y"]}  // URL-encoded and appended to the URL
form: {"name": "Nift"}          // application/x-www-form-urlencoded (--data-urlencode)
multipart: {"field": "value", "file": {"file": "p.bin", "filename": "p.bin", "content_type": "application/octet-stream"}}
body: "raw data"                // raw text request body
body: bytes([...])              // raw binary request body (bytes value)
body_file: "payload.bin"        // raw request body from a file (--data-binary @path)
json: {"name": "Nift"}          // JSON body (sets Content-Type: application/json)
upload: "payload.bin"           // upload a file (-T), method PUT
output: "download.bin"          // write the response body to a file; response.body is null
timeout: 30                     // total elapsed seconds (--max-time)
connect_timeout: 5              // connection phase seconds (--connect-timeout)
follow_redirects: true          // -L
max_redirects: 5                // --max-redirs
auth: {"user": "u", "password": "p"}   // Basic (-u)
auth: {"bearer": "token"}       // Authorization: Bearer
authorization: "Bearer token"   // raw Authorization header
cookies: {"theme": "dark"}      // Cookie request header
cookie_jar: "cookies.txt"       // read/write a Netscape cookie jar (-b/-c)
proxy: "http://proxy:3128"      // -x
cacert: "ca.pem"                // --cacert
capath: "/etc/ssl/certs"        // --capath
cert: "client.pem"              // --cert
key: "client.key"               // --key
insecure: true                  // -k (opt-in only; not the default)
compressed: true                // --compressed (Accept-Encoding + decode)
http_version: "2"               // "1.1" | "2" | "2-prior-knowledge" | "3"
user_agent: "my-app/1.0"        // -A
binary: true                    // return response.body_bytes instead of response.body
```

`output` and `binary` are mutually exclusive in effect: with `output` the body
is written by curl and not read back; with `binary` the body is read as an
immutable Nift `bytes` value. Text responses read `response.body` as a string.

## Sessions and cookies

```text
s := curl.session({
    base_url: "...",          // informational; not auto-joined
    headers: {"Authorization": "Bearer " + token},
    timeout: 30,
    follow_redirects: true
})
r1 := curl.request(base + "/login", {"session": s})
r2 := curl.get(base + "/me", {"session": s})
curl.session_close(s)
```

A session is **package-managed state** (default headers, timeouts, auth,
redirect policy, cookies) applied to each request; per-request options override
session defaults, and `headers`/`cookies` are merged. `curl.session({...,
persist_cookies: true})` creates a session-owned temporary cookie jar so
`Set-Cookie` values persist across requests; `cookie_jar: "path"` uses a
caller-owned jar file. `session_close` removes an owned jar.

This is honest about the backend: each request is a separate `curl` process, so
a session does **not** provide in-process connection-pool/keepalive ownership.
It provides persistent cookies and default request state.

## Error model

Transport success and HTTP status are separate concerns:

```text
HTTP 4xx/5xx:
    ok: true
    status: 404 / 500 / ...
    (the caller inspects status; not a package error)

DNS / connect / TLS / timeout / redirect / file failures:
    ok: false
    status: 0
    error_code: "timeout" | "transport_failure" | "file_error"
    error: human-readable message
```

Package error codes: `backend_unavailable` (curl missing or `--no-process`),
`temporary_file` (cannot create a temp file), `invalid_session` (bad session
handle), `timeout`, `transport_failure`, `file_error`. HTTP status codes are
never turned into Nift language exceptions; transport failures are structured
results, not catchable Errors.

## Capability and build inspection

`curl.version()` is the first `curl --version` line; `curl.features()` is the
full output. `curl.capabilities()` derives `tls`, `https`, `http2`, `http3`,
`brotli`, `zstd`, `compression`, `ipv6` and `unix_sockets` from the installed
build. HTTP/2/3 and TLS therefore depend entirely on the user's `curl` build;
unsupported protocols fail clearly through the underlying curl error.

## Binary safety

The backend is binary-safe through temp files: request bodies and response
bodies never pass through a shell or text formatting. Use `body: bytes(...)`
or `body_file` for binary requests and `binary: true` (yielding
`response.body_bytes`) or `output` for binary responses. Buffered
`response.body` strings are text-oriented.

## Restrictions

Because the current backend uses external processes, `nift script.f
--no-process` makes it unavailable. Requests then return
`error_code: "backend_unavailable"` without invoking `run()`. `--fs-root`
confines Nift-native filesystem operations but does not sandbox child
processes.

Backend selection is package-local and freezes on the first request.
`use_backend()` after that point returns `error_code: "backend_locked"`.
`auto` currently resolves only to `process`; `ffi` and `native` are reserved
but are not advertised or accepted as available implementations.

The process backend prefers `mktemp` on POSIX and
`[System.IO.Path]::GetTempFileName()` through PowerShell on Windows. A checked
package-local fallback is available when neither exists. Because Nift does not
expose atomic exclusive temporary-file creation, that fallback retains a small
cross-process name race; it never continues with an empty path.

## Not implemented (explicit blockers)

- **Streaming response bodies / SSE / WebSockets.** A `curl` process can write
  directly to a file (`output`) and `--compressed` is supported, but incremental
  Nift chunk callbacks require a process-stream read primitive that `run()`
  does not expose. WebSockets additionally require libcurl's multi interface.
  These are deferred; they are not "buffered" and must not be advertised as
  supported.
- **Async composition.** The client is synchronous. Running it on a Nift
  `thread()`/`async` worker is currently blocked because struct facades are
  non-transferable and cannot be referenced from worker closures
  (`unknown value or malformed expression: curl`; passing the facade as an
  argument yields `non-transferable resource`). This needs a general Nift core
  change (worker-capturable package facades); it is not solvable at package
  level.
- **libcurl via FFI.** Direct FFI to libcurl is blocked by the FFI's fixed
  arity (no variadic `curl_easy_setopt`), its single `i64(i64)` callback shape,
  the absence of a closure/userdata context, callback lifetime limits, and no
  `curl_slist`/pointer-field struct support. The process backend is the
  supported path.
