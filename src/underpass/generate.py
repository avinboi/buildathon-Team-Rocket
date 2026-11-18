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


def generate(site: str, model: str | None = None, log=print) -> dict:
    d = store.site_dir(site)
    data = store.read_json(d / "endpoints.json")
    if not data:
        raise SystemExit(f"Run `underpass analyze {site}` first.")
    eps = [e for e in data["endpoints"] if not e["sensitive"] and e["ok"] > 0]
    code_only = data.get("from_code", [])[:80]
    prompt = PROMPT.format(
        site=data["site"],
        today=time.strftime("%Y-%m-%d"),
        schema=json.dumps(Spec.model_json_schema()),
        endpoints="\n\n".join(_compact(e) for e in eps),
        code_only=(
            "(paths are relative; prefix them with the matching API base: "
            + ", ".join(sorted({_api_base(e["url"]) for e in eps}))
            + ")\n" + "\n".join(f"{c['method']} {c['path']}" for c in code_only)
        ) if code_only else "(none)",
    )
    log(f"Asking Claude to design tools for {len(eps)} endpoints (+{len(code_only)} found in code)...")
    t0 = time.time()
    raw = ask_claude(prompt, model)
    try:
        spec = Spec.model_validate(_extract_json(raw))
    except (ValidationError, ValueError) as e:
        log("First answer didn't validate, asking Claude to fix it...")
        raw = ask_claude(prompt + f"\n\nYour previous answer failed validation:\n{str(e)[:1500]}\nReturn corrected JSON only.", model)
        spec = Spec.model_validate(_extract_json(raw))
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
    result = {"site": data["site"], "summary": spec.site_summary, "generated_at": time.time(), "tools": tools}
    store.write_json(d / "tools.json", result)
    return result
