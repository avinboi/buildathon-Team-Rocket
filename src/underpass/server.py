"""Generic MCP server: exposes one MCP tool per generated Underpass tool for a site."""

import inspect
import json
import keyword
import re

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from underpass.engine import LoginExpired, Site

PY_TYPES = {"string": str, "integer": int, "number": float, "boolean": bool, "object": dict, "array": list}


def _ident(name: str) -> str:
    s = re.sub(r"\W+", "_", name).strip("_") or "arg"
    if s[0].isdigit() or keyword.iskeyword(s):
        s = "p_" + s
    return s


def _make_fn(site: Site, tool: dict):
    params, mapping = [], {}
    for p in sorted(tool.get("params", []), key=lambda p: not p.get("required")):
        ident = _ident(p["name"])
        if ident in mapping:
            continue
        mapping[ident] = p["name"]
        typ = PY_TYPES.get(p.get("type"), str)
        default = inspect.Parameter.empty if p.get("required") else p.get("default")
        annotation = typ if p.get("required") else (typ | None)
        params.append(inspect.Parameter(ident, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=annotation))
    is_action = tool["kind"] == "action"
    if is_action:
        params.append(inspect.Parameter("confirm", inspect.Parameter.KEYWORD_ONLY, default=False, annotation=bool))
    else:
        params.append(inspect.Parameter("all_fields", inspect.Parameter.KEYWORD_ONLY, default=False, annotation=bool))

    def fn(**kwargs):
        confirm = bool(kwargs.pop("confirm", False))
        all_fields = bool(kwargs.pop("all_fields", False))
        args = {mapping[k]: v for k, v in kwargs.items() if k in mapping and v is not None}
        try:
            result = site.call(tool["name"], args, confirm=confirm, all_fields=all_fields)
        except LoginExpired as e:
            result = {"ok": False, "error": str(e)}
        except Exception as e:
            result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return json.dumps(result, ensure_ascii=False)

    fn.__name__ = _ident(tool["name"])
    fn.__signature__ = inspect.Signature(params, return_annotation=str)
    fn.__annotations__ = {p.name: p.annotation for p in params} | {"return": str}
    return fn


def build_server(site_name: str) -> MCPServer:
    site = Site(site_name)
    server = MCPServer(
        name=f"underpass-{site.name}",
        instructions=(
            f"Tools for {site.name}, acting as the logged-in user. {site.summary} "
            "Read tools are safe. Action tools change real data: call them first without confirm to get a preview, "
            "show it to the user, and only call again with confirm=true after the user approves."
        ),
    )
    for tool in site.tools.values():
        desc = tool["description"]
        if tool["kind"] == "action":
            desc = "[ACTION: changes data; needs confirm=true after user approval] " + desc
        if tool.get("unverified"):
            desc += " (Found in the site's code; not yet seen in use.)"
        if tool["kind"] == "read":
            desc += "\n- all_fields: true returns the full untrimmed response (use if a field you need is missing)."
        for p in tool.get("params", []):
            if p.get("description"):
                desc += f"\n- {p['name']}: {p['description']}"
        server.add_tool(
            _make_fn(site, tool),
            name=tool["name"],
            description=desc,
            annotations=ToolAnnotations(
                readOnlyHint=tool["kind"] == "read",
                destructiveHint=tool["kind"] == "action" and tool["method"] == "DELETE",
                openWorldHint=True,
            ),
        )
    return server


def serve(site_name: str) -> None:
    build_server(site_name).run("stdio")
