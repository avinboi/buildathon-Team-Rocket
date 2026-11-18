"""Command-line entry point: `underpass <command>`.

Everyday use is one command per website:   underpass add coach.mastersunion.org
The individual steps (record, analyze, generate, serve, call, list) are there for debugging and testing.
"""

import argparse
import json
import shutil
import subprocess
import sys
import time

from underpass import __version__, store


def _short(site: str) -> str:
    """MCP server name for a site: 'coach.mastersunion.org' -> 'coach'."""
    host = store.site_name(site)
    first = host.split(".")[0]
    return first if first not in ("app", "my", "portal", "dashboard", "admin") else host.split(".")[1]


def cmd_record(args) -> int:
    from underpass.record import record

    d = record(args.url, explore=not args.no_explore, max_pages=args.max_pages, headless_login=args.headless)
    print(f"Saved recording to {d}")
    return 0


def cmd_login(args) -> int:
    from underpass.record import record

    record(args.site, explore=False)
    print("Login saved. Your agent's tools for this site work again.")
    return 0


def cmd_analyze(args) -> int:
    from underpass.analyze import analyze

    print(json.dumps(analyze(args.site, scan_js=not args.no_js), indent=2))
    return 0


def cmd_generate(args) -> int:
    from underpass.generate import generate

    spec = generate(args.site, model=args.model or "sonnet")
    _print_tools(spec)
    return 0


def _print_tools(spec: dict) -> None:
    reads = [t for t in spec["tools"] if t["kind"] == "read"]
    acts = [t for t in spec["tools"] if t["kind"] == "action"]
    print(f"\n{spec['site']}: {len(spec['tools'])} tools ({len(reads)} read, {len(acts)} actions)")
    for t in reads + acts:
        args = ", ".join(p["name"] for p in t.get("params", []))
        flag = "ACTION " if t["kind"] == "action" else ""
        print(f"  {flag}{t['name']}({args})" + ("  [from code]" if t.get("unverified") else ""))
        print(f"      {t['description'][:110]}")


def cmd_list(args) -> int:
    spec = store.read_json(store.site_dir(args.site) / "tools.json")
    if not spec:
        print(f"No tools yet. Run `underpass add {args.site}`.", file=sys.stderr)
        return 1
    _print_tools(spec)
    return 0


def cmd_call(args) -> int:
    from underpass.engine import Site

    kv = {}
    for a in args.args:
        k, _, v = a.partition("=")
        kv[k] = v
    result = Site(args.site).call(args.tool, kv, confirm=args.yes)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok", True) else 1


def cmd_check(args) -> int:
    """Call every read tool that needs no input and report what works, how fast, and how small the answer is."""
    from concurrent.futures import ThreadPoolExecutor

    from underpass.engine import Site

    site = Site(args.site)
    reads = [t for t in site.tools.values() if t["kind"] == "read"]

    def run(t):
        if any(p.get("required") and p.get("default") is None for p in t.get("params", [])):
            return t, None, "needs input"
        try:
            r = site.call(t["name"], {})
            return t, r, None if r["ok"] else f"HTTP {r['http_status']}"
        except Exception as e:
            return t, None, f"{type(e).__name__}: {str(e)[:80]}"

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(run, reads))
    ok = [r for r in results if r[2] is None]
    skipped = [r for r in results if r[2] == "needs input"]
    for t, r, err in sorted(results, key=lambda x: (x[2] is not None, x[0]["name"])):
        if err is None:
            size = len(json.dumps(r["data"], ensure_ascii=False))
            print(f"  OK    {t['name']:<40} {r['ms']:>5} ms  {size:>7} chars")
        else:
            print(f"  {'SKIP' if err == 'needs input' else 'FAIL'}  {t['name']:<40} {err}")
    if args.prune:
        # Drop tools guessed from the site's code that the live site rejects as non-existent / unusable.
        dead = {t["name"] for t, r, err in results if t.get("unverified") and err and err.startswith(("HTTP 404", "HTTP 405", "HTTP 400"))}
        path = store.site_dir(args.site) / "tools.json"
        spec = store.read_json(path)
        spec["tools"] = [t for t in spec["tools"] if t["name"] not in dead]
        store.write_json(path, spec)
        print(f"\nPruned {len(dead)} code-only tools the live site doesn't support: {', '.join(sorted(dead)) or '-'}")
    tested = len(results) - len(skipped)
    lat = sorted(r[1]["ms"] for r in ok)
    print(f"\n{len(ok)}/{tested} read tools work live ({len(skipped)} need an id from another tool)."
          + (f" Median {lat[len(lat) // 2]} ms." if lat else ""))
    return 0


def cmd_serve(args) -> int:
    from underpass.server import serve

    serve(args.site)
    return 0


def register(site: str) -> str:
    """Register the site's MCP server with Claude Code (user scope, so it works in every folder)."""
    name = _short(site)
    exe = shutil.which("claude")
    if not exe:
        return f"Claude Code not found. Add this MCP server to your agent manually:\n  {sys.executable} -m underpass serve {store.site_name(site)}"
    subprocess.run([exe, "mcp", "remove", name, "--scope", "user"], capture_output=True)
    proc = subprocess.run(
        [exe, "mcp", "add", name, "--scope", "user", "--", sys.executable, "-m", "underpass", "serve", store.site_name(site)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return f"Couldn't register with Claude Code: {proc.stderr.strip()}"
    return f"Connected to Claude Code as MCP server '{name}'. Start a new Claude session to use it."


def cmd_add(args) -> int:
    from underpass.analyze import analyze
    from underpass.generate import generate
    from underpass.record import record

    t0 = time.time()
    if not args.skip_record:
        record(args.url, explore=not args.no_explore, max_pages=args.max_pages)
    site = store.site_name(args.url)
    print("\nMapping everything the site can show and do...")
    report = analyze(site)
    print(
        f"  {report['api_calls_recorded']} API calls -> {report['endpoints']} endpoints "
        f"({report['reads']} read, {report['actions']} actions), {report['found_in_code_only']} more found in the site's code"
    )
    print(f"  login: {', '.join(f'{h} ({s})' for h, s in report['auth'].items())}")
    from underpass.instant import instant_tools

    spec = instant_tools(site)
    reads = sum(t["kind"] == "read" for t in spec["tools"])
    if not args.no_register:
        print(register(site))
    print(f"\nREADY in {time.time() - t0:.0f}s: your agent can now use {len(spec['tools'])} tools "
          f"({reads} read, {len(spec['tools']) - reads} actions) on {site}.")
    if args.no_polish:
        return 0
    print("\nPolishing names and descriptions with Claude (the tools keep working meanwhile)...")
    spec = generate(site, model=args.model or "sonnet")
    _print_tools(spec)
    print(f"\nDone in {time.time() - t0:.0f}s.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="underpass", description="Turn any website into tools for AI agents.")
    parser.add_argument("--version", action="version", version=f"underpass {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add", help="Set up a website in one go: record, map, generate tools, connect to your agent.")
    p.add_argument("url", help="Website, e.g. coach.mastersunion.org")
    p.add_argument("--skip-record", action="store_true", help="Reuse the existing recording.")
    p.add_argument("--no-explore", action="store_true", help="Skip automatic exploration.")
    p.add_argument("--max-pages", type=int, default=25)
    p.add_argument("--model", help="Claude model for tool design (default: your Claude Code default).")
    p.add_argument("--no-register", action="store_true", help="Don't register with Claude Code.")
    p.add_argument("--no-polish", action="store_true", help="Skip the Claude polishing step (instant tools only).")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("login", help="Log in to a site again (when the saved login expired).")
    p.add_argument("site")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("record", help="Open a browser, log in and use the site; Underpass records its hidden API traffic.")
    p.add_argument("url", help="Website to record, e.g. coach.mastersunion.org")
    p.add_argument("--no-explore", action="store_true", help="Skip the automatic exploration after you close the browser.")
    p.add_argument("--max-pages", type=int, default=25, help="Pages to explore automatically (default 25).")
    p.add_argument("--headless", action="store_true", help="Don't show the browser (reuses a saved login).")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("analyze", help="Map everything the site can show and do from the recording.")
    p.add_argument("site")
    p.add_argument("--no-js", action="store_true", help="Don't scan the site's JavaScript for extra endpoints.")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("generate", help="Use Claude to turn the map into named, described tools.")
    p.add_argument("site")
    p.add_argument("--model")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("list", help="List the tools generated for a site.")
    p.add_argument("site")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("call", help="Call a tool from the terminal: underpass call <site> <tool> key=value ...")
    p.add_argument("site")
    p.add_argument("tool")
    p.add_argument("args", nargs="*")
    p.add_argument("--yes", action="store_true", help="Approve an action (otherwise you get a preview).")
    p.set_defaults(func=cmd_call)

    p = sub.add_parser("check", help="Test every read tool against the live site.")
    p.add_argument("site")
    p.add_argument("--prune", action="store_true", help="Remove code-only tools that the live site rejects.")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("serve", help="Run the MCP server for a site (your agent starts this).")
    p.add_argument("site")
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
