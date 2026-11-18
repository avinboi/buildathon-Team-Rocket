"""Ask Claude to turn a site's endpoint map into agent tools (reads AND actions).

Claude is called through Claude Code headless (`claude -p`) with ANTHROPIC_API_KEY removed from the
environment, so it runs on the user's own Claude login.
"""

import json
import os
import re
import shutil
import subprocess
import time
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from underpass import store


class Param(BaseModel):
    name: str = Field(description="snake_case argument name the agent sees")
    location: Literal["path", "query", "body"]
    key: str = Field(description="path placeholder, query key, or dotted JSON body key (e.g. 'data.title')")
    type: Literal["string", "integer", "number", "boolean", "object", "array"] = "string"
    required: bool = False
    description: str = ""
    default: str | int | float | bool | None = None


class Tool(BaseModel):
    name: str
    description: str
    kind: Literal["read", "action"]
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    url: str = Field(description="full URL template with {placeholders} for path params")
    params: list[Param] = []
    fixed_query: dict = {}
    fixed_body: dict | list | None = None
    keep_fields: list[str] = Field(default=[], description="dotted response paths worth returning; empty = all")
    verify_with: str | None = Field(default=None, description="read tool that shows whether this action worked")
    endpoint_id: str = ""
    unverified: bool = False


class Spec(BaseModel):
    site_summary: str
    tools: list[Tool]


PROMPT = """You are Underpass. You turn a website's private JSON API into tools an AI agent can use on the
user's behalf, with the user's own login. The goal is FULL coverage: the agent should be able to see and do
everything the user can see and do on this site.

Site: {site}
Today's date: {today}

Below is every endpoint observed while the user used the site and while Underpass explored it.
Each has its method, URL template, example parameter values, example request bodies and a response shape.
A second list has endpoints found only in the site's JavaScript (never called; no examples).

Write the tool list:
- One tool per useful capability. Cover every distinct thing the site lets the user see or do. Merge endpoints
  only when they are truly the same capability. Skip pure plumbing (feature flags, unread badges that duplicate
  a list tool, config, tracking).
- kind = "read" for GET (and GraphQL queries); kind = "action" for anything that changes data.
- Names: snake_case verbs, e.g. get_attendance, list_assignments, submit_assignment, mark_notification_read.
- Descriptions: plain words saying what the tool returns or does and WHEN an agent should use it. Mention key
  fields. For actions, say exactly what changes.
- Params: expose only what an agent would vary (ids it can get from another tool, dates, search text, page).
  Explain where to get each id (e.g. "course_id from list_courses"). IDs that are always the same for this user
  (their own user id, org id, current term id) become a param with that value as `default` and required=false.
  Constant query values go in fixed_query. For POST/PUT bodies, put constants in fixed_body and expose the
  varying fields as body params with dotted keys.
- keep_fields: the dotted response paths an agent actually needs (names, titles, dates, statuses, ids, scores,
  links). Use paths exactly as they appear in the response shape, without the "[]" markers
  (e.g. "data.items.title"). Leave empty when the response is already small.
- verify_with: for every action, name the read tool whose output shows the action worked.
- Include JavaScript-only endpoints as tools only when the path makes the purpose clear; set unverified=true.
- url must be the full template from the endpoint, with {{placeholders}} matching path param keys.
- endpoint_id: copy the endpoint's id.

Return ONLY a JSON object, no prose, no code fences, matching this schema:
{schema}

ENDPOINTS:
{endpoints}

JAVASCRIPT-ONLY ENDPOINTS:
{code_only}
"""


def _compact(ep: dict) -> str:
    lines = [f"id: {ep['id']}", f"  {ep['method']} {ep['url']}  (calls={ep['calls']}, ok={ep['ok']}, found_by={ep['found_by']})"]
    if ep.get("graphql"):
        lines.append(f"  graphql {ep['graphql']['kind']} {ep['graphql']['operation']}")
    if ep["path_params"]:
        lines.append(f"  path params: {json.dumps(ep['path_params'])}")
    if ep["query"]:
        lines.append(f"  query: {json.dumps(ep['query'], ensure_ascii=False)[:400]}")
    if ep["body_examples"]:
        lines.append(f"  body ({ep['body_kind']}): {json.dumps(ep['body_examples'][0], ensure_ascii=False)[:700]}")
    if ep.get("seen_on_pages"):
        lines.append(f"  seen on pages: {', '.join(ep['seen_on_pages'][:3])}")
    if ep["response_shape"]:
        lines.append("  response:")
        lines += [f"    {s}" for s in ep["response_shape"][:35]]
    return "\n".join(lines)


def _api_base(url: str) -> str:
    """'https://api.x.in/api/v1/users/7' -> 'https://api.x.in/api/v1'"""
    scheme, _, rest = url.partition("://")
    host, _, path = rest.partition("/")
    keep = []
    for seg in path.split("/"):
        if seg == "api" or re.fullmatch(r"v\d+", seg):
            keep.append(seg)
        else:
            break
    return f"{scheme}://{host}" + ("/" + "/".join(keep) if keep else "")


def ask_claude(prompt: str, model: str | None = None, timeout: int = 600) -> str:
    exe = shutil.which("claude")
    if not exe:
        raise SystemExit("Claude Code (`claude`) isn't installed or isn't on PATH.")
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}  # use the user's Claude login
    cmd = [exe, "-p", "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    proc = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", env=env,
        timeout=timeout, cwd=str(store.home()),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed: {proc.stderr.strip()[:500] or proc.stdout[:500]}")
    out = json.loads(proc.stdout)
    if out.get("is_error"):
        raise RuntimeError(f"claude -p error: {out.get('result')}")
    return out["result"]


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start: end + 1])


def generate(site: str, model: str | None = "sonnet", log=print) -> dict:
    d = store.site_dir(site)
    data = store.read_json(d / "endpoints.json")
    if not data:
        raise SystemExit(f"Run `underpass analyze {site}` first.")
    eps = [e for e in data["endpoints"] if not e["sensitive"] and e["ok"] > 0]
    code_only = data.get("from_code", [])
    bases = ", ".join(sorted({_api_base(e["url"]) for e in eps}))

    def build_prompt(endpoints, code, focus):
        return PROMPT.format(
            site=data["site"],
            today=time.strftime("%Y-%m-%d"),
            schema=json.dumps(Spec.model_json_schema()),
            endpoints="\n\n".join(_compact(e) for e in endpoints) or "(none)",
            code_only=(
                f"(paths are relative; prefix them with the matching API base: {bases})\n" + "\n".join(
                    f"{c['method']} {c['path']}" + (f"  body fields: {', '.join(c['body_fields'])}" if c.get("body_fields") else "")
                    for c in code
                )
            ) if code else "(none)",
        ) + "\n\n" + focus

    # Two parallel requests: everything the site can SHOW, and everything it can DO.
    READ_FOCUS = ("FOCUS: this request covers READ tools only (kind='read'). Include JavaScript-only GET endpoints whose "
                  "purpose is clear from the path.")
    ACTION_FOCUS = ("FOCUS: this request covers ACTION tools only (kind='action', plus POST endpoints that only fetch data as "
                    "kind='read'). Create a tool for EVERY action endpoint listed, observed or JavaScript-only, so the agent "
                    "can do everything the user can do. Skip only internal plumbing (telemetry, error logs, view/impression "
                    "logging, token fetches). For JavaScript-only actions, infer body params from the listed body fields and "
                    "the path; set unverified=true. Every action should name a verify_with read tool (a list_x/get_x name "
                    "for the same kind of thing; it is matched to the real read tools afterwards).")

    def chunks(items, n):
        return [items[i:i + n] for i in range(0, len(items), n)] or [[]]

    # Many small requests in parallel: much faster than one huge answer.
    read_eps, act_eps = [e for e in eps if not e["action"]], [e for e in eps if e["action"]]
    read_code, act_code = [c for c in code_only if c["method"] == "GET"], [c for c in code_only if c["method"] != "GET"]
    parts = {}
    for i, group in enumerate(chunks(read_eps, 12)):
        parts[f"reads{i}"] = build_prompt(group, [], READ_FOCUS)
    for i, group in enumerate(chunks(read_code, 30)):
        if group:
            parts[f"readcode{i}"] = build_prompt([], group, READ_FOCUS)
    for i, group in enumerate(chunks(act_eps + [None] * 0, 18)):
        parts[f"actions{i}"] = build_prompt(group, act_code if i == 0 and len(act_code) <= 30 else [], ACTION_FOCUS)
    if len(act_code) > 30:
        for i, group in enumerate(chunks(act_code, 30)):
            parts[f"actcode{i}"] = build_prompt([], group, ACTION_FOCUS)
    log(f"Asking Claude to design tools for {len(eps)} endpoints (+{len(code_only)} found in code) in {len(parts)} parallel batches...")
    t0 = time.time()

    def run(prompt):
        try:
            return _run(prompt)
        except Exception as e:  # one bad batch must not sink the whole site
            log(f"  a batch failed ({type(e).__name__}); continuing")
            return Spec(site_summary="", tools=[])

    def _run(prompt):
        raw = ask_claude(prompt, model)
        try:
            return Spec.model_validate(_extract_json(raw))
        except (ValidationError, ValueError) as e:
            raw = ask_claude(prompt + f"\n\nYour previous answer failed validation:\n{str(e)[:1500]}\nReturn corrected JSON only.", model)
            return Spec.model_validate(_extract_json(raw))

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(12) as pool:
        specs = list(pool.map(run, parts.values()))
    summary = max((sp.site_summary for sp in specs), key=len, default="")
    spec = Spec(site_summary=summary, tools=[t for sp in specs for t in sp.tools])
    log(f"Claude designed {len(spec.tools)} tools in {time.time() - t0:.0f}s.")

    # Keep only tools whose endpoint really exists (or came from the JS scan), and unique names.
    known_urls = {e["url"] for e in data["endpoints"]}
    seen, tools = set(), []
    for t in spec.tools:
        if t.name in seen:
            continue
        if t.url not in known_urls and not t.unverified:
            t.unverified = True
        seen.add(t.name)
        tools.append(t.model_dump())
    # Keep instant tools for anything Claude didn't cover, so polishing never loses coverage.
    instant = store.read_json(d / "tools.instant.json", {}) or {}
    covered = {(t["method"], re.sub(r"\{[^}]+\}", "{}", t["url"])) for t in tools}
    for t in instant.get("tools", []):
        if (t["method"], re.sub(r"\{[^}]+\}", "{}", t["url"])) not in covered and t["name"] not in seen:
            seen.add(t["name"])
            tools.append(t)
    read_names = {t["name"] for t in tools if t["kind"] == "read"}
    def words(name):
        return {w.rstrip("s") for w in name.split("_")} - {"get", "list", "create", "update", "delete", "submit", "add", "my", ""}

    for t in tools:
        if t["kind"] != "action" or t.get("verify_with") in read_names:
            continue
        # match to the read tool about the same thing, e.g. create_student_note -> list_student_notes
        best = max(read_names, key=lambda r: (len(words(r) & words(t["name"])), r.startswith("list_")), default=None)
        t["verify_with"] = best if best and words(best) & words(t["name"]) else None
    result = {"site": data["site"], "summary": spec.site_summary, "generated_at": time.time(), "tools": tools}
    store.write_json(d / "tools.json", result)
    return result
