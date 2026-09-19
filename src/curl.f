/*
    curl package for Nift. Runtime dependency: the `curl` executable on PATH.
    Public API: request() plus the HTTP verb helpers (direct exports) and the
    `curl` struct for facility inspection (curl.available/version/features).
    All implementation helpers are private. Nift itself carries no
    libcurl/TLS/networking dependency.
*/

fn(curl_available()) { return which("curl") != null }

fn(curl_temp_file()) {
    m := run("mktemp")
    if(m.exit_code != 0) { return "" }
    return m.stdout.trim()
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
        if(line.contains(":")) {
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
    // Convert to an ordinary object; repeated headers are joined so their
    // values are preserved (the object model cannot hold duplicate keys).
    entries := []
    for((k, v) : h) {
        if(type(v) == "array") { entries.push({"key": k, "value": v.join("; ")}) }
        else { entries.push({"key": k, "value": v}) }
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
    if(!curl_available()) { return {"ok":false,"status":0,"headers":{},"body":"","exit_code":127,"error":"curl executable not found"} }
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
        args.push("--data-binary"); args.push("@" + bodytemp)
        args.push("-H"); args.push("Content-Type: application/json")
        method = "POST"
    } else if(body != "") {
        bodytemp = curl_write_temp(body)
        args.push("--data-binary"); args.push("@" + bodytemp)
    }
    if(method != "GET") { args.push("-X"); args.push(method) }
    if(follow) { args.push("-L") }
    if(timeout > 0) { args.push("--max-time"); args.push(timeout.to_string()) }
    args.push("-w"); args.push("%{http_code}")
    header_temp := curl_temp_file()
    if(header_temp != "") { args.push("-D"); args.push(header_temp) }
    body_temp := ""
    if(output != "") { args.push("-o"); args.push(output) } else { body_temp = curl_temp_file(); args.push("-o"); args.push(body_temp) }
    args.push(url)
    r := run("curl", ...args)
    if(bodytemp != "") { remove(bodytemp) }
    if(r.exit_code != 0) {
        if(header_temp != "") { remove(header_temp) }
        if(body_temp != "") { remove(body_temp) }
        return {"ok":false,"status":0,"headers":{},"body":"","exit_code":r.exit_code,"error":r.stderr}
    }
    status := 0
    code := r.stdout.trim()
    if(code != "") { status = code.to_int() }
    headers_obj := {}
    if(header_temp != "") { headers_obj = curl_parse_headers(open(header_temp)) }
    resp_body := ""
    if(body_temp != "" && open(body_temp) != "") { resp_body = open(body_temp) }
    else if(output != "" && open(output) != "") { resp_body = open(output) }
    if(header_temp != "") { remove(header_temp) }
    if(body_temp != "") { remove(body_temp) }
    return {"ok":true,"status":status,"headers":headers_obj,"body":resp_body,"exit_code":r.exit_code,"error":""}
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
    version := () => curl_version_text()
    features := () => curl_features_text()
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