"""Turn recorded traffic into a map of everything a site can show and do.

Output (in the site folder):
  endpoints.json  one entry per endpoint template: method, URL template, path/query/body parameters with
                  real example values, a flattened response shape, and where it was found
                  (you used it / auto-explore / found only in the site's JavaScript)
  auth.json       per API host: the request headers that carry the login (cookies are read live from state.json)
"""

import base64
import json
import re
import time
import urllib.request
from collections import defaultdict
from urllib.parse import parse_qsl, urlparse

from underpass import store

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Headers the browser sets by itself; everything else that looks like auth/app config is kept.
BROWSER_HEADERS = {
    "user-agent", "accept", "accept-language", "accept-encoding", "connection", "content-length", "host",
    "referer", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform", "sec-fetch-dest", "sec-fetch-mode",
    "sec-fetch-site", "priority", "cookie", "content-type", "pragma", "cache-control", "upgrade-insecure-requests",
}

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
HEX_ID = re.compile(r"^[0-9a-f]{16,}$", re.I)
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _is_id(seg: str) -> bool:
    if not seg:
        return False
    if seg.isdigit() or UUID.match(seg) or HEX_ID.match(seg) or DATE.match(seg):
        return True
    # long opaque tokens like 'a8Kx92mPq0' (letters + digits, no separators)
    return len(seg) >= 10 and any(c.isdigit() for c in seg) and any(c.isalpha() for c in seg) and seg.isalnum()


def _param_name(prev: str, used: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "_", prev).strip("_") or "id"
    name = f"{base}_id" if not base.lower().endswith("id") else base
    n, i = name, 2
    while n in used:
        n, i = f"{name}{i}", i + 1
    used.add(n)
    return n


def slug_positions(urls: list[tuple[str, str, str]], min_variants: int = 3) -> dict:
    """Find path segments that are really names/slugs (e.g. /crates/serde, /crates/tokio, /crates/rand).

    (method, host, path) triples that are identical except for ONE segment, with >= min_variants different
    values there, share one endpoint template. Returns {(method, host, path): {segment_index, ...}}.
    """
    buckets: dict[tuple, set] = defaultdict(set)
    parents: set[tuple] = set()  # (method, host, segments) that have longer paths below them
    for m, h, p in set(urls):
        segs = p.split("/")
        for i in range(1, len(segs) - 1):
            parents.add((m, h, tuple(segs[: i + 1])))
        for i in range(1, len(segs)):
            if segs[i]:
                buckets[(m, h, i, tuple(segs[:i] + ["*"] + segs[i + 1:]))].add(segs[i])
    out: dict = defaultdict(set)
    for m, h, p in set(urls):
        segs = p.split("/")
        for i in range(1, len(segs)):
            if not segs[i]:
                continue
            vals = buckets[(m, h, i, tuple(segs[:i] + ["*"] + segs[i + 1:]))]
            if len(vals) < min_variants:
                continue
            # real slugs all have the same shape below them; fixed route names (/v1/crates vs /v1/summary) don't
            shapes = {(m, h, tuple(segs[:i] + [v])) in parents for v in vals}
            if len(shapes) == 1:
                out[(m, h, p)].add(i)
    return out


def template_path(path: str, slugs: set | None = None) -> tuple[str, dict[str, str]]:
    """'/programTerm/77/attandance' -> ('/programTerm/{programTerm_id}/attandance', {'programTerm_id': '77'})"""
    segs = path.split("/")
    out, params, used = [], {}, set()
    for i, s in enumerate(segs):
        if _is_id(s) or (slugs and i in slugs):
            name = _param_name(segs[i - 1] if i else "id", used)
            out.append("{" + name + "}")
            params[name] = s
        else:
            out.append(s)
    return "/".join(out), params


def _parse_body(entry: dict):
    raw = entry.get("req_body")
    if raw is None:
        return None, None
    ctype = (entry.get("req_content_type") or "").lower()
    if "json" in ctype or raw[:1] in "{[":
        try:
            return "json", json.loads(raw)
        except Exception:
            pass
    if "x-www-form-urlencoded" in ctype:
        return "form", dict(parse_qsl(raw, keep_blank_values=True))
    if "multipart" in ctype:
        return "multipart", None
    return "raw", raw[:500]


SECRET_KEYS = re.compile(r"pass(word)?|otp|secret|token|captcha|credential|pin$", re.I)
SENSITIVE_PATH = re.compile(r"login|logout|signin|signout|sign-in|sign-out|password|otp|captcha|auth/|token|analytics|telemetry|/events?$", re.I)


def redact(value):
    """Blank out password/OTP/token fields so they never reach endpoints.json or Claude."""
    if isinstance(value, dict):
        return {k: ("<redacted>" if SECRET_KEYS.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def _graphql_op(entry: dict, body):
    if isinstance(body, dict) and "query" in body and isinstance(body.get("query"), str):
        name = body.get("operationName")
        if not name:
            m = re.search(r"(query|mutation)\s+(\w+)", body["query"])
            name = m.group(2) if m else "anonymous"
        kind = "mutation" if body["query"].lstrip().startswith("mutation") else "query"
        return name, kind
    return None, None


def flatten(value, prefix: str = "", out: list | None = None, limit: int = 80) -> list[str]:
    """Describe a JSON value as lines like 'data.items[].title: str = "Week 3 quiz"'."""
    if out is None:
        out = []
    if len(out) >= limit:
        return out
    if isinstance(value, dict):
        for k, v in value.items():
            flatten(v, f"{prefix}.{k}" if prefix else k, out, limit)
    elif isinstance(value, list):
        if value:
            # merge keys across a few items so optional fields show up
            if all(isinstance(v, dict) for v in value[:5]):
                merged = {}
                for v in value[:5]:
                    for k, x in v.items():
                        merged.setdefault(k, x)
                flatten(merged, f"{prefix}[]", out, limit)
            else:
                flatten(value[0], f"{prefix}[]", out, limit)
        else:
            out.append(f"{prefix}: list = []")
    else:
        sample = json.dumps(value, ensure_ascii=False)
        if len(sample) > 60:
            sample = sample[:57] + '..."'
        out.append(f"{prefix or '(root)'}: {type(value).__name__} = {sample}")
    return out


def _jwt_expiry(token: str):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        return float(exp) if exp else None
    except Exception:
        return None


def build_auth(entries: list[dict]) -> dict:
    """For each API host, the non-browser headers from its latest successful call."""
    auth = {}
    for e in sorted(entries, key=lambda e: e["t"]):
        if not (200 <= e["status"] < 300):
            continue
        host = urlparse(e["url"]).hostname
        headers = {
            k: v for k, v in (e.get("req_headers") or {}).items()
            if k.lower() not in BROWSER_HEADERS and not k.startswith(":")
        }
        info = {"headers": headers}
        bearer = next((v for k, v in headers.items() if k.lower() == "authorization"), "")
        if bearer.lower().startswith("bearer "):
            info["scheme"] = "bearer"
            exp = _jwt_expiry(bearer.split(" ", 1)[1])
            if exp:
                info["expires_at"] = exp
        else:
            info["scheme"] = "cookie" if (e.get("req_headers") or {}).get("cookie") else "headers"
        auth[host] = info
    return auth


def _fetch_scripts(urls: list[str]) -> dict[str, str]:
    from concurrent.futures import ThreadPoolExecutor

    def get(u):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            return u, urllib.request.urlopen(req, timeout=20).read(8_000_000).decode("utf-8", "ignore")
        except Exception:
            return u, ""

    with ThreadPoolExecutor(16) as pool:
        return {u: t for u, t in pool.map(get, urls) if t}


ACTION_WORDS = re.compile(
    r"create|add|update|edit|delete|remove|submit|save|send|mark|toggle|upload|claim|reject|approve|accept|"
    r"cancel|pin|unpin|like|bookmark|book|enroll|register|apply|join|leave|invite|follow|vote|rate|review|reply|"
    r"comment|post|publish|archive|restore|assign|complete|start|stop|reset|set|change",
    re.I,
)
VERB = re.compile(r"\.(get|post|put|patch|delete)\s*\(", re.I)
METHOD_KW = re.compile(r"""method\s*:\s*["'](get|post|put|patch|delete)["']""", re.I)
HELPER_AFTER = re.compile(r"\(0\s*,\s*[\w$]+\.([\w$]+)\)\s*\(|([\w$]{1,4})\s*\(\s*[\w$]\s*[,)]")
HELPER_BEFORE = re.compile(r"(?:\(0\s*,\s*[\w$]+\.([\w$]+)\)|([\w$]{1,4}))\s*\(\s*$")


def _call_site(js: str, start: int, end: int):
    """Return (verb, helper) for the HTTP call that uses the path literal at js[start:end]."""
    before = js[max(0, start - 60): start]
    after = js[end: end + 260]
    m = re.search(r"\.(get|post|put|patch|delete)\s*\(\s*$", before, re.I)
    if m:
        return m.group(1).upper(), None
    m = HELPER_BEFORE.search(before)
    if m:
        return None, m.group(1) or m.group(2)
    m = METHOD_KW.search(js[max(0, start - 200): end + 200])
    if m:
        return m.group(1).upper(), None
    m = VERB.search(after[:120])
    if m:
        return m.group(1).upper(), None
    m = HELPER_AFTER.search(after)
    if m:
        return None, m.group(1) or m.group(2)
    return None, None


def _body_fields(js: str, end: int) -> list[str]:
    """Field names sent with the request: an object literal right after the path, or FormData appends nearby."""
    after = js[end: end + 500]
    m = re.match(r"""[^,()]{0,80},\s*\{([^{}]{0,400})\}""", after)
    keys = re.findall(r"""(?:^|,)\s*["']?([A-Za-z_$][\w$]*)["']?\s*:""", m.group(1)) if m else []
    keys += re.findall(r"""\.append\(\s*["']([\w$]+)["']""", js[max(0, end - 600): end])
    return list(dict.fromkeys(keys))[:15]


def scan_scripts(script_urls: list[str], namespaces: set[str], known: dict[str, str], log=print) -> list[dict]:
    """Find API endpoints in the site's JavaScript that were never called while recording, with their method.

    The site's own HTTP helper functions are learned from calls we DID see: if '/student/notes' was a POST
    and the code calls it through helper `Ay`, then every other path passed to `Ay` is a POST too.
    `known` maps normalized observed paths (relative to the API base) to their method.
    """
    lit = re.compile(r"""["'`](/[A-Za-z][A-Za-z0-9_\-/.${}:]*?)(?:\?[^"'`]*)?["'`]""")
    scripts = _fetch_scripts(script_urls)
    sites = []  # (path, norm, verb, helper, fields, script)
    for url, js in scripts.items():
        for m in lit.finditer(js):
            path = m.group(1)
            if re.search(r"\.(js|css|png|svg|jpe?g|gif|webp|ico|woff2?|json|html|map)$", path):
                continue
            path = re.sub(r"\$\{[^}]*\}", "{param}", path).rstrip("/")
            segs = [x for x in path.split("/") if x]
            if len(segs) < 2 or segs[0] not in namespaces:
                continue
            verb, helper = _call_site(js, m.start(), m.end())
            norm = re.sub(r"\{[^}]+\}", "{}", "/" + "/".join(segs))
            sites.append((path, norm, verb, helper, _body_fields(js, m.end()), url.rsplit("/", 1)[-1][:60]))

    # Learn helper -> method from paths whose method we observed.
    votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for path, norm, verb, helper, _, _ in sites:
        if helper and norm in known:
            votes[helper][known[norm]] += 1
    helpers = {h: max(v, key=v.get) for h, v in votes.items()}

    found: dict[tuple, dict] = {}
    for path, norm, verb, helper, fields, script in sites:
        method = verb or helpers.get(helper)
        if not method and ACTION_WORDS.search(path.rsplit("/", 1)[-1] if "{" in path.rsplit("/", 1)[-1] else path):
            method = "DELETE" if re.search(r"delete|remove", path, re.I) else "POST"  # verb in the path: an action
        if not method or SENSITIVE_PATH.search(path) or re.search(r"error|log$|logs$|token", path, re.I):
            continue  # can't tell how it's called; skip rather than guess
        if known.get(norm) == method or (method, norm) in found:
            continue
        found[(method, norm)] = {"method": method, "path": path, "body_fields": fields, "script": script}
    writes = sum(f["method"] != "GET" for f in found.values())
    log(f"  scanned {len(scripts)} scripts; learned {len(helpers)} HTTP helpers "
        f"({', '.join(f'{h}={m}' for h, m in list(helpers.items())[:6])})")
    log(f"  found {len(found)} endpoints that were never called ({writes} actions)")
    return list(found.values())


def analyze(site: str, scan_js: bool = True, log=print) -> dict:
    d = store.site_dir(site)
    entries = store.read_jsonl(d / "traffic.jsonl")
    if not entries:
        raise SystemExit(f"No recording found for {site}. Run `underpass record {site}` first.")

    slugs = slug_positions([(e["method"], urlparse(e["url"]).hostname, urlparse(e["url"]).path) for e in entries])
    groups: dict[str, dict] = {}
    for e in entries:
        u = urlparse(e["url"])
        method = e["method"]
        tpl, path_params = template_path(u.path, slugs.get((method, u.hostname, u.path)))
        kind, body = _parse_body(e)
        op, op_kind = _graphql_op(e, body)
        body = redact(body)
        key = f"{method} {u.hostname}{tpl}" + (f" #{op}" if op else "")
        g = groups.setdefault(key, {
            "method": method, "host": u.hostname, "scheme": u.scheme, "path": tpl,
            "graphql": {"operation": op, "kind": op_kind} if op else None,
            "path_params": defaultdict(set), "query": defaultdict(set), "body_kind": kind, "body_examples": [],
            "calls": 0, "ok": 0, "sources": set(), "best_resp": None, "best_size": -1, "pages": set(),
        })
        g["calls"] += 1
        g["ok"] += 200 <= e["status"] < 300
        g["sources"].add(e.get("phase", "user"))
        if e.get("page"):
            g["pages"].add(urlparse(e["page"]).path)
        for k, v in path_params.items():
            g["path_params"][k].add(v)
        for k, v in parse_qsl(u.query, keep_blank_values=True):
            g["query"][k].add(v)
        if body is not None and len(g["body_examples"]) < 3 and body not in g["body_examples"]:
            g["body_examples"].append(body)
        if e.get("resp_body") is not None and 200 <= e["status"] < 300:
            size = len(json.dumps(e["resp_body"]))
            if size > g["best_size"]:
                g["best_resp"], g["best_size"] = e["resp_body"], size

    endpoints = []
    for key, g in sorted(groups.items()):
        endpoints.append({
            "id": key,
            "method": g["method"],
            "url": f"{g['scheme']}://{g['host']}{g['path']}",
            "host": g["host"],
            "path": g["path"],
            "graphql": g["graphql"],
            "action": g["method"] in WRITE_METHODS and not (g["graphql"] and g["graphql"]["kind"] == "query"),
            "path_params": {k: sorted(v)[:5] for k, v in g["path_params"].items()},
            "query": {k: sorted(v)[:5] for k, v in g["query"].items()},
            "body_kind": g["body_kind"],
            "body_examples": g["body_examples"],
            "response_shape": flatten(g["best_resp"]) if g["best_resp"] is not None else [],
            "response_bytes": max(g["best_size"], 0),
            "calls": g["calls"],
            "ok": g["ok"],
            "found_by": "you" if "user" in g["sources"] else "explore",
            # login/logout/token/telemetry calls are never turned into agent tools
            "sensitive": bool(SENSITIVE_PATH.search(g["path"])),
            "seen_on_pages": sorted(g["pages"])[:5],
        })

    # API namespaces = first path segment after any /api/vN prefix, on hosts that served JSON.
    namespaces, known = set(), {}
    for ep in endpoints:
        segs = [s for s in ep["path"].split("/") if s]
        while segs and (segs[0] == "api" or re.fullmatch(r"v\d+", segs[0])):
            segs.pop(0)
        if segs:
            namespaces.add(segs[0])
        known[re.sub(r"\{[^}]+\}", "{}", "/" + "/".join(segs))] = ep["method"]

    code_only = []
    if scan_js:
        log("Scanning the site's JavaScript for endpoints nobody clicked...")
        scripts = store.read_json(d / "scripts.json", [])
        code_only = scan_scripts(scripts, namespaces, known, log)

    auth = build_auth(entries)
    store.write_json(d / "endpoints.json", {"site": store.site_name(site), "endpoints": endpoints, "from_code": code_only})
    store.write_json(d / "auth.json", auth)

    reads = sum(not e["action"] for e in endpoints)
    report = {
        "api_calls_recorded": len(entries),
        "endpoints": len(endpoints),
        "reads": reads,
        "actions": len(endpoints) - reads,
        "found_in_code_only": len(code_only),
        "api_hosts": sorted(auth),
        "auth": {h: a["scheme"] for h, a in auth.items()},
    }
    for h, a in auth.items():
        if a.get("expires_at"):
            report.setdefault("login_expires_in_days", {})[h] = round((a["expires_at"] - time.time()) / 86400, 1)
    return report
