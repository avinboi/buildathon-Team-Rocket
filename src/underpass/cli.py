"""Command-line entry point: `underpass <command>`."""

import argparse
import sys

from underpass import __version__

COMMANDS = {
    "record": "Open a browser, log in and use the site; Underpass records its hidden API traffic.",
    "analyze": "Turn recorded traffic into endpoint templates and detect how the site authenticates.",
    "generate": "Use Claude to turn endpoints into named, described tools (reads and actions).",
    "serve": "Run an MCP server that exposes a site's tools to your agent.",
    "call": "Call one of a site's tools from the terminal.",
    "list": "List the tools generated for a site.",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="underpass", description="Turn any website into tools for AI agents.")
    parser.add_argument("--version", action="version", version=f"underpass {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in COMMANDS.items():
        sub.add_parser(name, help=help_text, description=help_text)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"`underpass {args.command}` is not implemented yet.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
