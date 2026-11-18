"""Instant tools: build a working tool for every endpoint in under a second, with no AI.

Names come from the method and path, params from the URL templates/query/body that were seen, defaults from the
real values the site used (so "my own id" params just work). Claude can polish these later (`generate`), but the
agent can use the whole site right away.
"""

import re
import time
from collections import Counter

from underpass import store
from underpass.generate import _api_base

SKIP_SEGMENTS = re.compile(r"^(api|v\d+|graphql)$", re.I)
ACTION_PREFIX = re.compile(
    r"^(create|add|update|edit|delete|remove|submit|save|send|mark|toggle|upload|claim|reject|approve|accept|cancel|"
    r"pin|unpin|like|bookmark|book|enroll|register|apply|join|leave|invite|follow|vote|rate|review|reply|comment|"
    r"post|publish|archive|restore|assign|complete|start|stop|reset|set|change)",
    re.I,
)


def _snake(s: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _words(path: str) -> list[str]:
    segs = [x for x in path.split("/") if x and not x.startswith("{") and not SKIP_SEGMENTS.match(x)]
    return [_snake(x) for x in segs][-2:] or ["root"]


def _name(method: str, path: str, returns_list: bool) -> str:
    words = _words(path)
    last = words[-1]
    if method == "GET":
        verb = "list" if returns_list else "get"
        return f"{verb}_{'_'.join(words)}"
    if ACTION_PREFIX.match(last):
        return "_".join(words[:-1] + [last]) if len(words) > 1 else last
    verb = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}.get(method, method.lower())
    return f"{verb}_{'_'.join(words)}"


def _type(v) -> str:
    return {bool: "boolean", int: "integer", float: "number", dict: "object", list: "array"}.get(type(v), "string")


def instant_tools(site: str, log=print) -> dict:
    d = store.site_dir(site)
    data = store.read_json(d / "endpoints.json")
    if not data:
        raise SystemExit(f"Run `underpass analyze {site}` first.")
    t0 = time.time()
    eps = [e for e in data["endpoints"] if not e["sensitive"] and e["ok"] > 0]
    tools, names = [], Counter()

    def unique(n):
        names[n] += 1
        return n if names[n] == 1 else f"{n}_{names[n]}"

    for e in eps:
        shape = e.get("response_shape") or []
        returns_list = any("[]" in line for line in shape[:5])
        params = []
        for k, vals in e["path_params"].items():
            mine = len(vals) == 1 and not e["action"]  # one value everywhere = "my own id"; never default an action's target
            params.append({"name": k, "location": "path", "key": k, "type": "string", "required": not mine,
                           "default": vals[0] if mine else None,
                           "description": f"seen values: {', '.join(map(str, vals[:3]))}"})
        for k, vals in e["query"].items():
            params.append({"name": _snake(k) or k, "location": "query", "key": k, "type": "string", "required": False,
                           "default": Counter(vals).most_common(1)[0][0] if vals else None, "description": ""})
        body = e["body_examples"][0] if e["body_examples"] else None
        if isinstance(body, dict):
            for k, v in body.items():
                if v == "<redacted>":
                    continue
                params.append({"name": _snake(k) or k, "location": "body", "key": k, "type": _type(v), "required": False,
                               "default": v if not isinstance(v, (dict, list)) else None,
                               "description": f"example: {str(v)[:60]}"})
        fields = sorted({re.sub(r"\[\]", "", line.split(":")[0]).split(".")[-1] for line in shape})[:12]
        kind = "action" if e["action"] else "read"
        name = unique(_name(e["method"], e["path"], returns_list))
        tools.append({
            "name": name, "kind": kind, "method": e["method"], "url": e["url"], "params": params,
            "fixed_query": {}, "fixed_body": None, "keep_fields": [], "verify_with": None,
            "endpoint_id": e["id"], "unverified": False,
            "description": (f"{'Changes data: ' if kind == 'action' else ''}{e['method']} {e['path']} on {e['host']}"
                            + (f" (seen on {', '.join(e['seen_on_pages'][:2])})" if e.get("seen_on_pages") else "")
                            + (f". Returns fields like: {', '.join(fields)}" if fields else "")),
        })

    # Endpoints found only in the site's JavaScript: attach to the API base that serves the same namespace.
    base_for = {}
    for e in eps:
        segs = [x for x in e["path"].split("/") if x and not SKIP_SEGMENTS.match(x)]
        if segs:
            base_for.setdefault(segs[0], _api_base(e["url"]))
    for c in data.get("from_code", []):
        segs = [x for x in c["path"].split("/") if x]
        base = base_for.get(segs[0]) if segs else None
        if not base:
            continue
        path, params, i = c["path"], [], 0
        while "{param}" in path:
            i += 1
            path = path.replace("{param}", f"{{id{i}}}", 1)
            params.append({"name": f"id{i}", "location": "path", "key": f"id{i}", "type": "string", "required": True,
                           "default": None, "description": "id from a related list tool"})
        for f in c.get("body_fields", []):
            params.append({"name": _snake(f) or f, "location": "body", "key": f, "type": "string", "required": False,
                           "default": None, "description": ""})
        kind = "read" if c["method"] == "GET" else "action"
        tools.append({
            "name": unique(_name(c["method"], path, False)), "kind": kind, "method": c["method"], "url": base + path,
            "params": params, "fixed_query": {}, "fixed_body": None, "keep_fields": [], "verify_with": None,
            "endpoint_id": f"code:{c['method']} {c['path']}", "unverified": True,
            "description": f"{'Changes data: ' if kind == 'action' else ''}{c['method']} {c['path']} (found in the site's code)",
        })

    # verify each action with the read tool about the same thing (create_student_note -> list_student_notes)
    reads = [t["name"] for t in tools if t["kind"] == "read"]

    def w(n):
        return {x.rstrip("s") for x in n.split("_")} - {"get", "list", "create", "update", "delete", "add", ""}

    for t in tools:
        if t["kind"] == "action":
            best = max(reads, key=lambda r: (len(w(r) & w(t["name"])), r.startswith("list_")), default=None)
            t["verify_with"] = best if best and w(best) & w(t["name"]) else None

    spec = {"site": data["site"], "summary": f"Instant tools for {data['site']} (not yet polished by Claude).",
            "generated_at": time.time(), "instant": True, "tools": tools}
    store.write_json(d / "tools.json", spec)
    store.write_json(d / "tools.instant.json", spec)
    log(f"Built {len(tools)} instant tools in {time.time() - t0:.1f}s (no AI needed).")
    return spec
