# curl

HTTP client package for Nift.

Runtime dependency: the `curl` executable on `PATH`. Nift itself carries no
libcurl/TLS/networking dependency; the package drives the user's `curl` through
Nift's structured process API (argv, never shell concatenation).

## API

```text
@import("curl")

response := request("https://example.com")
print(response.status)
print(response.body)
```

`request(url, options?)` returns an ordinary Nift object:

```text
response.ok         // true for any HTTP response (including 404); false on process failure
response.status     // HTTP status code (int)
response.headers    // object; repeated headers joined with "; " (e.g. Set-Cookie)
response.body       // response body string
response.exit_code  // curl process exit code
response.error      // stderr text on process failure, else ""
```

Options (all optional):

```text
method: "POST"              // HTTP method
headers: {"X-Custom": "v"}  // request headers (values may be strings or arrays)
body: "raw data"            // raw request body
json: {"name": "Nift"}      // JSON body (sets Content-Type: application/json)
timeout: 30                 // --max-time seconds
follow_redirects: true      // -L
output: "file.bin"          // write the response body to a file
```

Convenience verbs are exported directly:

```text
get(url, opts?) / post / put / patch / delete / head
```

Curl-specific facility inspection lives on the exported `curl` struct:

```text
print(curl.available())
print(curl.version())
print(curl.features())
```

## Example

```text
@import("curl")

response := request("https://example.com/api/posts", {
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

Because the package uses external processes, `nift run script.f --no-process`
fails requests through the existing process restriction. `--fs-root` confines
Nift-native filesystem operations but does not sandbox child processes.

## Future work

Multipart/form uploads and streaming are not yet implemented.