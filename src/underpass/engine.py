"""Run a generated tool against the live site, as the logged-in user.

- Builds the request from the tool spec + the agent's arguments.
- Adds the login: recorded auth headers per host, plus live cookies from the saved browser session.
- Actions (anything that changes data) are never sent unless confirm=True. Without it, the agent gets an exact
  preview of what would be sent, so it can ask the user first.
- After an action, the tool's `verify_with` read tool is called to show whether the change really happened.
- Responses are trimmed for agents: only useful fields, no HTML, no empty values, capped size.
"""

import copy
import html
import json
import re
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode, urlparse

from underpass import store

MAX_RESPONSE_CHARS = 30_000
TAG = re.compile(r"<[^>]+>")


class LoginExpired(Exception):
    pass


def _set_dotted(obj: dict, dotted: str, value):
    keys = dotted.split(".")
    for k in keys[:-1]:
        obj = obj.setdefault(k, {})
    obj[keys[-1]] = value


def _coerce(value, typ: str):
    if value is None:
        return None
    try:
        if typ == "integer":
            return int(value)
        if typ == "number":
            return float(value)
        if typ == "boolean":
            return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes")
        if typ in ("object", "array") and isinstance(value, str):
            return json.loads(value)
    except (ValueError, TypeError):
        pass
    return value


def project(data, fields: list[str]):
    """Keep only the dotted paths in `fields` (lists are walked through transparently)."""
    if not fields:
        return data
    tree: dict = {}
    for f in fields:
        node = tree
        for part in f.replace("[]", "").split("."):
            node = node.setdefault(part, {})

    def walk(value, node):
        if not node:
            return value
        if isinstance(value, list):
            return [walk(v, node) for v in value]
        if isinstance(value, dict):
            out = {k: walk(value[k], sub) for k, sub in node.items() if k in value}
            return out if out else None
        return value

    kept = walk(data, tree)
    return kept if kept not in (None, {}, []) else data  # fall back to everything if the paths didn't match


def clean(value):
    if isinstance(value, dict):
        out = {k: clean(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [c for c in (clean(v) for v in value) if c not in (None, "", [], {})]
    if isinstance(value, str):
        if "<" in value and ">" in value:
            value = html.unescape(TAG.sub(" ", value))
            value = re.sub(r"\s+", " ", value).strip()
        return value if len(value) <= 500 else value[:500] + "..."
    return value


def shrink(value, limit: int = MAX_RESPONSE_CHARS):
    """Halve the longest lists until the JSON fits, and say how much was cut."""
    text = json.dumps(value, ensure_ascii=False)
    note = None
    while len(text) > limit:
        longest, parent_key = None, None

        def find(v, path):
            nonlocal longest, parent_key
            if isinstance(v, list):
                if longest is None or len(v) > len(longest):
                    longest, parent_key = v, path
                for x in v:
                    find(x, path)
            elif isinstance(v, dict):
                for k, x in v.items():
                    find(x, f"{path}.{k}" if path else k)

        find(value, "")
        if not longest or len(longest) <= 1:
            text = text[:limit]
            break
        del longest[len(longest) // 2:]
        note = f"Long lists were shortened to fit (e.g. '{parent_key}'). Use filters/pagination params for more."
        text = json.dumps(value, ensure_ascii=False)
    return value, note


class Site:
    def __init__(self, name: str):
        self.dir = store.site_dir(name)
        spec = store.read_json(self.dir / "tools.json")
        if not spec:
            raise SystemExit(f"No tools for {name}. Run `underpass add {name}` first.")
        self.name = spec["site"]
        self.summary = spec.get("summary", "")
        self.tools = {t["name"]: t for t in spec["tools"]}
        self.auth = store.read_json(self.dir / "auth.json", {})
        self.meta = store.read_json(self.dir / "site.json", {})

    def _cookies_for(self, host: str) -> str:
        state = store.read_json(self.dir / "state.json", {}) or {}
        now = time.time()
        jar = []
        for c in state.get("cookies", []):
            dom = c["domain"].lstrip(".")
            if (host == dom or host.endswith("." + dom)) and (c.get("expires", -1) in (-1, None) or c["expires"] > now):
                jar.append(f"{c['name']}={c['value']}")
        return "; ".join(jar)

    def build_request(self, tool: dict, args: dict) -> dict:
        url = tool["url"]
        query = dict(tool.get("fixed_query") or {})
        body = copy.deepcopy(tool.get("fixed_body"))
        for p in tool.get("params", []):
            value = args.get(p["name"], p.get("default"))
            if value is None:
                if p.get("required"):
                    raise ValueError(f"Missing required argument '{p['name']}': {p.get('description', '')}")
                continue
            value = _coerce(value, p.get("type", "string"))
            if p["location"] == "path":
                url = url.replace("{" + p["key"] + "}", quote(str(value), safe=""))
            elif p["location"] == "query":
                query[p["key"]] = value
            else:
                if body is None:
                    body = {}
                if isinstance(body, dict):
                    _set_dotted(body, p["key"], value)
        missing = re.findall(r"\{([^}]+)\}", url)
        if missing:
            raise ValueError(f"Missing path value(s): {', '.join(missing)}")
        if query:
            url += ("&" if "?" in url else "?") + urlencode(
                {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in query.items()}
            )
        return {"method": tool["method"], "url": url, "body": body}

    def _send(self, req: dict):
        host = urlparse(req["url"]).hostname
        headers = dict((self.auth.get(host) or {}).get("headers", {}))
        headers["accept"] = "application/json, text/plain, */*"
        headers["user-agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
        start = self.meta.get("start_url")
        if start:
            origin = "{0.scheme}://{0.netloc}".format(urlparse(start))
            headers.setdefault("origin", origin)
            headers.setdefault("referer", origin + "/")
        cookies = self._cookies_for(host)
        if cookies:
            headers["cookie"] = cookies
        data = None
        if req["body"] is not None and req["method"] != "GET":
            data = json.dumps(req["body"]).encode()
            headers["content-type"] = "application/json"
        r = urllib.request.Request(req["url"], data=data, headers=headers, method=req["method"])
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
            if status in (401, 403):
                raise LoginExpired(
                    f"The site rejected the saved login (HTTP {status}). Run `underpass login {self.name}` to log in again."
                )
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = raw.decode("utf-8", "ignore")[:2000]
        return status, payload

    def call(self, tool_name: str, args: dict | None = None, confirm: bool = False) -> dict:
        args = dict(args or {})
        tool = self.tools.get(tool_name)
        if not tool:
            raise ValueError(f"Unknown tool '{tool_name}'. Available: {', '.join(sorted(self.tools))}")
        req = self.build_request(tool, args)

        if tool["kind"] == "action" and not confirm:
            return {
                "status": "needs_confirmation",
                "message": "This changes data on the site. Show the user this preview and ask for approval, "
                           "then call again with confirm=true.",
                "would_send": req,
                "what_it_does": tool["description"],
            }

        t0 = time.time()
        status, payload = self._send(req)
        ms = round((time.time() - t0) * 1000)
        data, note = shrink(clean(project(payload, tool.get("keep_fields", []))) if 200 <= status < 300 else payload)
        result = {"ok": 200 <= status < 300, "http_status": status, "ms": ms, "data": data}
        if note:
            result["note"] = note
        if tool.get("unverified"):
            result["warning"] = "This tool was found in the site's code and was never seen in use; check the result."

        if tool["kind"] == "action" and result["ok"] and tool.get("verify_with") in self.tools:
            try:
                check = self.call(tool["verify_with"], {})
                result["verification"] = {"tool": tool["verify_with"], "result": check.get("data")}
            except Exception as e:  # verification is best effort
                result["verification"] = {"tool": tool["verify_with"], "error": str(e)}
        return result
