"""Command-line entry point: `underpass <command>`."""

import argparse
import sys

from underpass import __version__


def cmd_record(args) -> int:
    from underpass.record import record

    d = record(args.url, explore=not args.no_explore, max_pages=args.max_pages, headless_login=args.headless)
    print(f"Saved recording to {d}")
    return 0


def cmd_analyze(args) -> int:
    import json

    from underpass.analyze import analyze

    report = analyze(args.site, scan_js=not args.no_js)
    print(json.dumps(report, indent=2))
    return 0


def not_yet(args) -> int:
    print(f"`underpass {args.command}` is not implemented yet.", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="underpass", description="Turn any website into tools for AI agents.")
    parser.add_argument("--version", action="version", version=f"underpass {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("record", help="Open a browser, log in and use the site; Underpass records its hidden API traffic.")
    p.add_argument("url", help="Website to record, e.g. coach.mastersunion.org")
    p.add_argument("--no-explore", action="store_true", help="Skip the automatic exploration after you close the browser.")
    p.add_argument("--max-pages", type=int, default=25, help="Pages to explore automatically (default 25).")
    p.add_argument("--headless", action="store_true", help="Don't show the browser (reuses a saved login).")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("analyze", help="Map everything the site can show and do from the recording.")
    p.add_argument("site", help="Site name or URL, e.g. coach.mastersunion.org")
    p.add_argument("--no-js", action="store_true", help="Don't scan the site's JavaScript for extra endpoints.")
    p.set_defaults(func=cmd_analyze)

    for name, help_text in {
        "generate": "Use Claude to turn endpoints into named, described tools (reads and actions).",
        "serve": "Run an MCP server that exposes a site's tools to your agent.",
        "call": "Call one of a site's tools from the terminal.",
        "list": "List the tools generated for a site.",
    }.items():
        sub.add_parser(name, help=help_text).set_defaults(func=not_yet)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
