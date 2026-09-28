/*
    curl package for Nift. Runtime dependency: the `curl` executable on PATH.
    Public API: the `curl` facade. The direct request/verb exports remain as
    deprecated v0.x compatibility aliases.
    All implementation helpers are private. Nift itself carries no
    libcurl/TLS/networking dependency.
*/

curl_backend_requested := "auto"
curl_backend_locked := false
curl_temp_seq := 0

fn(curl_process_available()) {
    return getenv("NIFT_NO_PROCESS") == null && which("curl") != null
}

fn(curl_backend_names()) {
    if(curl_process_available()) { return ["process"] }
    return []
}

fn(curl_resolved_backend()) {
    if(curl_backend_requested == "process") {
        if(curl_process_available()) { return "process" }
        return null
    }
    if(curl_backend_requested == "auto" && curl_process_available()) { return "process" }
    return null
}

fn(curl_use_backend(name)) {
    if(curl_backend_locked) {
        return {"ok":false,"error":"curl backend is already selected","error_code":"backend_locked","backend":curl_resolved_backend()}
    }
    if(name != "auto" && name != "process" && name != "ffi" && name != "native") {
        return {"ok":false,"error":"unknown curl backend: " + name,"error_code":"unknown_backend","backend":curl_resolved_backend()}
    }
    if(name != "auto" && name != "process") {
        return {"ok":false,"error":"curl backend is not implemented: " + name,"error_code":"backend_unavailable","backend":curl_resolved_backend()}
    }
    if(name == "process" && !curl_process_available()) {
        return {"ok":false,"error":"curl process backend is unavailable","error_code":"backend_unavailable","backend":curl_resolved_backend()}
    }
    curl_backend_requested = name
    return {"ok":true,"error":"","error_code":"","backend":curl_resolved_backend()}
}

fn(curl_available()) { return curl_resolved_backend() != null }

fn(curl_temp_root()) {
    root := getenv("TMPDIR")
    if(root == null || root == "") { root = getenv("TEMP") }
    if(root == null || root == "") { root = getenv("TMP") }
    if(root == null || root == "") { root = pwd() }
    return root
}

fn(curl_temp_file()) {
    if(which("mktemp") != null) {
        m := run("mktemp")
        if(m.exit_code == 0 && m.stdout.trim() != "") { return m.stdout.trim() }
    }
    if(os() == "windows" && which("powershell.exe") != null) {
        p := run("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "[System.IO.Path]::GetTempFileName()")
        if(p.exit_code == 0 && p.stdout.trim() != "") { return p.stdout.trim() }
    }
    attempts := 0
    while(attempts < 1000) {
        curl_temp_seq += 1
        candidate := curl_temp_root() + "/.nift-curl-" + curl_temp_seq.to_string() + ".tmp"
        if(!exists(candidate)) {
            touch(candidate)
            return candidate
        }
        attempts += 1
    }
    return ""
}

fn(curl_write_temp(content)) {
    temp := curl_temp_file()
    if(temp == "") { return "" }
    f := file(temp)
    f.open("w")
    f.write(content)
    f.save()
    f.close()
    return temp
}

fn(curl_parse_headers(text)) {
    h := map()
    lines := text.split("\r\n")
    if(lines.size() == 1) { lines = text.split("\n") }
    for(line : lines) {
        normalized := line.to_lower().trim()
        if(normalized.index_of("http/") == 0) {
            // curl -D writes every response block; retain only the final block.
            h = map()
        } else if(line.contains(":")) {
            colon := line.index_of(":")
            if(colon > 0) {
                hname := line.substr(0, colon).to_lower().trim()
                value := line.substr(colon + 1).trim()
                if(hname.index_of("http/") != 0) {
                    if(h.contains(hname)) {
                        cur := h.get(hname)
                        if(type(cur) == "array") { cur.push(value) } else { h.set(hname, [cur, value]) }
                    } else {
                        h.set(hname, value)
                    }
                }
            }
        }
    }
    // Arrays preserve repeated fields such as Set-Cookie without inventing a
    // delimiter that is invalid for some HTTP headers.
    entries := []
    for((k, v) : h) {
        if(type(v) == "array") { entries.push({"key": k, "value": v}) }
        else { entries.push({"key": k, "value": [v]}) }
    }
    return entries.from_entries()
}

fn(curl_header_text(v)) {
    if(type(v) == "string") { return v }
    return v.to_string()
}

fn(curl_headers_as_args(headers, args)) {
    if(headers != null && type(headers) == "object") {
        for(k : headers.keys()) {
            v := headers.get(k)
            if(type(v) == "array") {
                for(item : v) { args.push("-H"); args.push(k + ": " + curl_header_text(item)) }
            } else {
                args.push("-H"); args.push(k + ": " + curl_header_text(v))
            }
        }
    }
    return null
}

fn(curl_request_impl(url, opts)) {
    curl_backend_locked = true
    backend := curl_resolved_backend()
    if(backend == null) {
        return {"ok":false,"status":0,"headers":{},"body":null,"output":null,"error":"curl process backend is unavailable","error_code":"backend_unavailable","backend":null,"exit_code":127}
    }
    args := ["-sS"]
    method := "GET"
    timeout := 0
    follow := false
    output := ""
    body := ""
    use_json := false
    headers := {}
    if(opts != null) {
        method = opts.get("method", "GET")
        timeout = opts.get("timeout", 0)
        follow = opts.get("follow_redirects", false)
        output = opts.get("output", "")
        body = opts.get("body", "")
        use_json = opts.has("json")
        headers = opts.get("headers", {})
    }
    curl_headers_as_args(headers, args)
    bodytemp := ""
    if(use_json) {
        json_value := opts.get("json")
        bodytemp = curl_write_temp(json_value.stringify())
        if(bodytemp == "") { return {"ok":false,"status":0,"headers":{},"body":null,"output":null,"error":"cannot create request body temporary file","error_code":"temporary_file","backend":backend,"exit_code":null} }
        args.push("--data-binary"); args.push("@" + bodytemp)
        args.push("-H"); args.push("Content-Type: application/json")
    } else if(body != "") {
        bodytemp = curl_write_temp(body)
        if(bodytemp == "") { return {"ok":false,"status":0,"headers":{},"body":null,"output":null,"error":"cannot create request body temporary file","error_code":"temporary_file","backend":backend,"exit_code":null} }
        args.push("--data-binary"); args.push("@" + bodytemp)
    }
    if(method != "GET") { args.push("-X"); args.push(method) }
    if(follow) { args.push("-L") }
    if(timeout > 0) { args.push("--max-time"); args.push(timeout.to_string()) }
    args.push("-w"); args.push("%{http_code}")
    header_temp := curl_temp_file()
    if(header_temp == "") {
        if(bodytemp != "") { remove(bodytemp) }
        return {"ok":false,"status":0,"headers":{},"body":null,"output":null,"error":"cannot create response header temporary file","error_code":"temporary_file","backend":backend,"exit_code":null}
    }
    args.push("-D"); args.push(header_temp)
    body_temp := ""
    if(output != "") { args.push("-o"); args.push(output) }
    else {
        body_temp = curl_temp_file()
        if(body_temp == "") {
            if(bodytemp != "") { remove(bodytemp) }
            remove(header_temp)
            return {"ok":false,"status":0,"headers":{},"body":null,"output":null,"error":"cannot create response body temporary file","error_code":"temporary_file","backend":backend,"exit_code":null}
        }
        args.push("-o"); args.push(body_temp)
    }
    args.push("--")
    args.push(url)
    r := run("curl", ...args)
    if(bodytemp != "") { remove(bodytemp) }
    if(r.exit_code != 0) {
        if(header_temp != "") { remove(header_temp) }
        if(body_temp != "") { remove(body_temp) }
        error_code := "transport_failure"
        if(r.exit_code == 28) { error_code = "timeout" }
        else if(r.exit_code == 23 || r.exit_code == 26) { error_code = "file_error" }
        if(output != "") {
            return {"ok":false,"status":0,"headers":{},"body":null,"output":output,"error":r.stderr,"error_code":error_code,"backend":backend,"exit_code":r.exit_code}
        }
        return {"ok":false,"status":0,"headers":{},"body":null,"output":null,"error":r.stderr,"error_code":error_code,"backend":backend,"exit_code":r.exit_code}
    }
    status := 0
    code := r.stdout.trim()
    if(code != "") { status = code.to_int() }
    headers_obj := {}
    headers_obj = curl_parse_headers(open(header_temp))
    resp_body := ""
    if(body_temp != "") { resp_body = open(body_temp) }
    if(header_temp != "") { remove(header_temp) }
    if(body_temp != "") { remove(body_temp) }
    if(output != "") {
        return {"ok":true,"status":status,"headers":headers_obj,"body":null,"output":output,"error":"","error_code":"","backend":backend,"exit_code":r.exit_code}
    }
    return {"ok":true,"status":status,"headers":headers_obj,"body":resp_body,"output":null,"error":"","error_code":"","backend":backend,"exit_code":r.exit_code}
}

fn(curl_merge_opts(opts, method)) {
    if(opts == null) { return {"method": method} }
    return opts.merge({"method": method})
}

fn(curl_version_text()) {
    r := run("curl", "--version")
    if(r.exit_code != 0) { return "" }
    return r.stdout.split("\n")[0]
}

fn(curl_features_text()) {
    r := run("curl", "--version")
    if(r.exit_code != 0) { return "" }
    return r.stdout
}

// Public API: request() and convenience verbs exported directly; the `curl`
// struct exports facility inspection. opts is optional.
fn(curl_opt_at(rest, i)) { if(i < rest.size()) { return rest[i] } return null }
request := (url, ...rest) => curl_request_impl(url, curl_opt_at(rest, 0))
get := (url, ...rest) => curl_request_impl(url, curl_merge_opts(curl_opt_at(rest, 0), "GET"))
post := (url, ...rest) => curl_request_impl(url, curl_merge_opts(curl_opt_at(rest, 0), "POST"))
put := (url, ...rest) => curl_request_impl(url, curl_merge_opts(curl_opt_at(rest, 0), "PUT"))
patch := (url, ...rest) => curl_request_impl(url, curl_merge_opts(curl_opt_at(rest, 0), "PATCH"))
delete := (url, ...rest) => curl_request_impl(url, curl_merge_opts(curl_opt_at(rest, 0), "DELETE"))
head := (url, ...rest) => curl_request_impl(url, curl_merge_opts(curl_opt_at(rest, 0), "HEAD"))

@struct(curl_api) {
    available := () => curl_available()
    backends := () => curl_backend_names()
    backend := () => curl_resolved_backend()
    use_backend := (name) => curl_use_backend(name)
    capabilities := () => { return {"buffered":true,"output_file":true,"streaming":false,"websocket":false} }
    version := () => curl_version_text()
    features := () => curl_features_text()
    request := (url, ...rest) => curl_request_impl(url, curl_opt_at(rest, 0))
    get := (url, ...rest) => curl_request_impl(url, curl_merge_opts(curl_opt_at(rest, 0), "GET"))
    post := (url, ...rest) => curl_request_impl(url, curl_merge_opts(curl_opt_at(rest, 0), "POST"))
    put := (url, ...rest) => curl_request_impl(url, curl_merge_opts(curl_opt_at(rest, 0), "PUT"))
    patch := (url, ...rest) => curl_request_impl(url, curl_merge_opts(curl_opt_at(rest, 0), "PATCH"))
    delete := (url, ...rest) => curl_request_impl(url, curl_merge_opts(curl_opt_at(rest, 0), "DELETE"))
    head := (url, ...rest) => curl_request_impl(url, curl_merge_opts(curl_opt_at(rest, 0), "HEAD"))
}

curl := curl_api()
export(request)
export(get)
export(post)
export(put)
export(patch)
export(delete)
export(head)
export(curl)
