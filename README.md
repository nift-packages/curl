# curl

HTTP client package for Nift.

Runtime dependency: the `curl` executable on `PATH`. Nift itself carries no
libcurl/TLS/networking dependency; the package drives the user's `curl` through
Nift's structured process API (argv, never shell concatenation).

## API

```text
@import("curl")

response := curl.get("https://example.com")
print(response.status)
print(response.body)
```

`curl.request(url, options?)` returns an ordinary Nift object:

```text
response.ok         // true for any HTTP response (including 404); false on process failure
response.status     // HTTP status code (int)
response.headers    // object; every field value is an array
response.body       // buffered text body, or null when output is used/failure occurs
response.output     // selected output path, otherwise null
response.error      // stable human-readable failure, else ""
response.error_code // stable package error code, else ""
response.backend    // concrete backend used (currently "process")
response.exit_code  // process diagnostic; do not use for portable control flow
```

Options (all optional):

```text
method: "POST"              // HTTP method
headers: {"X-Custom": "v"}  // request headers (values may be strings or arrays)
body: "raw data"            // raw request body
json: {"name": "Nift"}      // JSON body (sets Content-Type: application/json)
timeout: 30                 // --max-time seconds
follow_redirects: true      // -L
output: "file.bin"          // write body to a file; response.body is null
```

The package facade owns the convenience verbs:

```text
curl.get(url, opts?) / curl.post / curl.put / curl.patch / curl.delete / curl.head
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

## Example

```text
@import("curl")

response := curl.request("https://example.com/api/posts", {
    method: "POST",
    headers: {"Authorization": "Bearer " + token},
    json: {title: "Hello"},
    timeout: 30
})
```

## Protocol capabilities

HTTP/2, HTTP/3 and TLS support depend entirely on the user's `curl` build;
`curl.features()` makes the build's capability list inspectable. Unsupported
protocols fail clearly through the underlying curl error.

## Restrictions

Because the current backend uses external processes, `nift script.f
--no-process` makes it unavailable. Requests then return
`error_code: "backend_unavailable"` without invoking `run()`. `--fs-root`
confines Nift-native filesystem operations but does not sandbox child
processes.

Backend selection is package-local and freezes on the first request.
`use_backend()` after that point returns `error_code: "backend_locked"`.
`auto` currently resolves only to `process`; `ffi` and `native` are reserved but
are not advertised or accepted as available implementations.

`timeout` maps to curl's elapsed `--max-time`. It is not a general cancellation
token. HTTP 4xx/5xx responses still have `ok: true`; `ok: false` means the
transfer/backend failed.

The process backend prefers `mktemp` on POSIX and
`[System.IO.Path]::GetTempFileName()` through PowerShell on Windows. A checked
package-local fallback is available when neither exists. Because Nift does not
yet expose atomic exclusive temporary-file creation, that fallback retains a
small cross-process name race; it never continues with an empty path.

## Future work

Multipart/form uploads and streaming are not yet implemented. Buffered body
strings are text-oriented. Use `output` for arbitrary or large response bytes;
the package does not reopen that file to populate `response.body`.
