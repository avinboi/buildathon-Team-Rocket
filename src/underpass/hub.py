"""The Underpass hub: ONE MCP server that lets any agent turn any website into tools, by itself.

Install once in any agent (Claude Code, Codex, Cursor, ...). The agent then has 4 tools:
  underpass_sites        which websites are already connected
  underpass_add_site     connect a new website (user logs in once; Underpass maps everything else)
  underpass_find_tools   search a site's tools (hundreds of them) and load only what's needed
  underpass_call         run a tool: reads directly; actions preview -> user approval -> run -> verify
Only 4 tool definitions sit in the agent's context, no matter how many sites or tools exist.
"""

import json
import re
import subprocess
import sys
import threading
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from underpass import store
from underpass.engine import LoginExpired, Site

server = MCPServer(
    name="underpass",
    instructions=(
        "Underpass turns any website the user can log into into tools, using the site's own hidden API "
        "(much faster and more reliable than browser automation). Workflow: underpass_sites -> (if missing) "
        "underpass_add_site -> underpass_find_tools(site, query) -> underpass_call. Actions change real data: "
        "call once without confirm to get a preview, show it to the user, and only call with confirm=true after "
        "they approve."
    ),
)


def _sites() -> list[dict]:
    out = []
    root = store.home() / "sites"
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        spec = store.read_json(d / "tools.json")
        if spec:
            tools = spec["tools"]
            out.append({"site": spec["site"], "tools": len(tools),
                        "reads": sum(t["kind"] == "read" for t in tools),
                        "actions": sum(t["kind"] == "action" for t in tools),
                        "summary": spec.get("summary", "")[:200]})
    return out


@server.tool()
def underpass_sites() -> str:
    """List websites already connected to Underpass, with how many read and action tools each has."""
    return json.dumps(_sites() or "No sites yet. Use underpass_add_site(url).", ensure_ascii=False)


@server.tool()
def underpass_add_site(
    url: Annotated[str, Field(description="Website to connect, e.g. 'app.example.com'")],
    needs_login: Annotated[bool, Field(description="false for public sites (no login window)")] = True,
) -> str:
    """Connect a new website. A browser window opens; the USER logs in (tell them to). Underpass then explores the
    site, reads its code to find every action, and builds tools automatically (~1-3 min). Returns a summary."""
    from underpass.analyze import analyze
    from underpass.instant import instant_tools
    from underpass.record import record

    logs: list[str] = []
    record(url, explore=True, max_pages=40, headless_login=not needs_login, log=logs.append)
    site = store.site_name(url)
    report = analyze(site, log=logs.append)
    spec = instant_tools(site, log=logs.append)
    # Polish names/descriptions with Claude in the background; tools work meanwhile.
    threading.Thread(
        target=lambda: subprocess.run([sys.executable, "-m", "underpass", "generate", site], capture_output=True),
        daemon=True,
    ).start()
    return json.dumps({
        "site": site, "tools": len(spec["tools"]),
        "reads": sum(t["kind"] == "read" for t in spec["tools"]),
        "actions": sum(t["kind"] == "action" for t in spec["tools"]),
        "api_calls_seen": report["api_calls_recorded"], "found_in_code": report["found_in_code_only"],
        "next": f"underpass_find_tools(site='{site}', query='...')",
    })


def _score(tool: dict, words: list[str]) -> int:
    hay = (tool["name"] + " " + tool["description"]).lower()
    return sum(3 if w in tool["name"].lower() else 1 for w in words if w in hay)


@server.tool()
def underpass_find_tools(
    site: Annotated[str, Field(description="Site from underpass_sites, e.g. 'coach.mastersunion.org'")],
    query: Annotated[str, Field(description="What you want to see or do, e.g. 'attendance', 'submit assignment'")] = "",
    kind: Annotated[str, Field(description="'read', 'action' or '' for both")] = "",
    limit: int = 15,
) -> str:
    """Search a site's tools by keywords. Returns tool names, what they do and their parameters."""
    tools = list(Site(site).tools.values())
    if kind:
        tools = [t for t in tools if t["kind"] == kind]
    words = [w for w in re.split(r"[^a-z0-9]+", query.lower()) if len(w) > 2]
    if words:
        tools = sorted((t for t in tools if _score(t, words)), key=lambda t: -_score(t, words))
    return json.dumps([
        {"tool": t["name"], "kind": t["kind"], "does": t["description"][:300],
         "params": {p["name"]: (p.get("description") or p["type"])[:120] + ("" if not p.get("required") else " (required)")
                    for p in t.get("params", [])}}
        for t in tools[:limit]
    ], ensure_ascii=False)


@server.tool()
def underpass_call(
    site: Annotated[str, Field(description="Site name")],
    tool: Annotated[str, Field(description="Tool name from underpass_find_tools")],
    args: Annotated[dict | None, Field(description="Tool parameters as an object")] = None,
    confirm: Annotated[bool, Field(description="Actions only: true after the user approved the preview")] = False,
    all_fields: Annotated[bool, Field(description="Return the full untrimmed response")] = False,
) -> str:
    """Run a site tool as the logged-in user. Reads return trimmed JSON in ~0.5s. Actions first return a preview;
    after user approval call again with confirm=true; the result includes automatic verification."""
    try:
        result = Site(site).call(tool, args or {}, confirm=confirm, all_fields=all_fields)
    except LoginExpired as e:
        result = {"ok": False, "error": str(e)}
    except Exception as e:
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return json.dumps(result, ensure_ascii=False)


def run() -> None:
    server.run("stdio")
