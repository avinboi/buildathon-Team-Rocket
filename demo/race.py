"""Timed side-by-side race: Claude Code + Playwright MCP (browser) vs Claude Code + Underpass MCP.

  uv run python demo/race.py <site> "<question>" [--only browser|underpass] [--start-url URL]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOME = Path.home() / ".underpass" / "sites"
print_lock = threading.Lock()


def log(side: str, msg: str) -> None:
    with print_lock:
        print(f"[{side}] {msg}", flush=True)


def site_host(site: str) -> str:
    s = site.split("://")[-1].split("/")[0]
    return s.removeprefix("www.")


def short_name(host: str) -> str:
    first = host.split(".")[0]
    return first if first not in ("app", "my", "portal", "dashboard", "admin") else host.split(".")[1]


def mcp_config(side: str, host: str, start_url: str | None) -> tuple[dict, str, str | None]:
    """Returns (config, server_name, warning)."""
    warn = None
    if side == "browser":
        npx = shutil.which("npx")
        if not npx:
            raise SystemExit("npx not found on PATH")
        args = ["-y", "@playwright/mcp@latest", "--headless", "--isolated", "--browser", "msedge"]
        state = HOME / host / "state.json"
        if state.exists():
            args += ["--storage-state", str(state)]
        else:
            warn = f"no state.json for {host}; browser runs logged out"
        cmd = {"command": "cmd", "args": ["/c", "npx", *args]} if os.name == "nt" else {"command": npx, "args": args}
        return {"mcpServers": {"browser": cmd}}, "browser", warn
    py = REPO / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    py = str(py) if py.exists() else sys.executable
    name = short_name(host)
    return {"mcpServers": {name: {"command": py, "args": ["-m", "underpass", "serve", host]}}}, name, warn


def run_side(side: str, host: str, question: str, start_url: str | None, out: dict) -> None:
    res = {"side": side, "tool_calls": 0, "tools": [], "answer": "", "cost_usd": None,
           "tokens": None, "seconds": None, "error": None}
    out[side] = res
    t0 = time.time()
    try:
        cfg, server, warn = mcp_config(side, host, start_url)
        if warn:
            log(side, f"warning: {warn}")
        claude = shutil.which("claude")
        if not claude:
            raise RuntimeError("claude not found on PATH")
        prompt = question
        if side == "browser":
            prompt = f"Start at {start_url}. {question}" if start_url else question
        with tempfile.TemporaryDirectory(prefix=f"race-{side}-", ignore_cleanup_errors=True) as tmp:
            cfgfile = Path(tmp) / "mcp.json"
            cfgfile.write_text(json.dumps(cfg), encoding="utf-8")
            cmd = [claude, "-p", prompt, "--mcp-config", str(cfgfile), "--strict-mcp-config",
                   "--output-format", "stream-json", "--verbose",
                   "--allowedTools", f"mcp__{server}__*", "--no-session-persistence", "--tools", ""]
            env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
            p = subprocess.Popen(cmd, cwd=tmp, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            err_buf: list[str] = []
            threading.Thread(target=lambda: err_buf.append(p.stderr.read()), daemon=True).start()
            for line in p.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") == "assistant":
                    for b in ev.get("message", {}).get("content", []):
                        if b.get("type") == "tool_use":
                            res["tool_calls"] += 1
                            name = b["name"].replace(f"mcp__{server}__", "")
                            res["tools"].append(name)
                            arg = json.dumps(b.get("input", {}), ensure_ascii=False)
                            log(side, f"{time.time() - t0:5.1f}s  #{res['tool_calls']} {name} {arg[:110]}")
                elif ev.get("type") == "result":
                    res["answer"] = ev.get("result") or ""
                    res["cost_usd"] = ev.get("total_cost_usd")
                    u = ev.get("usage") or {}
                    res["tokens"] = sum(u.get(k, 0) or 0 for k in (
                        "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
                    if ev.get("is_error"):
                        res["error"] = str(ev.get("result"))[:300]
            p.wait()
            if p.returncode != 0 and not res["answer"]:
                res["error"] = (err_buf[0] if err_buf else "")[:400] or f"exit {p.returncode}"
    except Exception as e:  # noqa: BLE001
        res["error"] = str(e)
    res["seconds"] = round(time.time() - t0, 1)
    log(side, f"done in {res['seconds']}s" + (f" ERROR: {res['error']}" if res["error"] else ""))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("site")
    ap.add_argument("question")
    ap.add_argument("--only", choices=["browser", "underpass"])
    ap.add_argument("--start-url")
    a = ap.parse_args()
    host = site_host(a.site)
    start = a.start_url
    if not start:
        try:
            start = json.loads((HOME / host / "site.json").read_text(encoding="utf-8")).get("start_url")
        except Exception:  # noqa: BLE001
            start = a.site if "://" in a.site else f"https://{host}"
    sides = [a.only] if a.only else ["browser", "underpass"]
    if "underpass" in sides and not (HOME / host / "tools.json").exists():
        print(f"warning: {HOME / host / 'tools.json'} missing; run `underpass generate {host}` first", file=sys.stderr)
    out: dict = {}
    t0 = time.time()
    threads = [threading.Thread(target=run_side, args=(s, host, a.question, start, out)) for s in sides]
    [t.start() for t in threads]
    [t.join() for t in threads]

    print("\n" + "=" * 78)
    print(f"{'':12}" + "".join(f"{s:>22}" for s in sides))
    def row(label, f):
        print(f"{label:12}" + "".join(f"{f(out[s]):>22}" for s in sides))
    row("time (s)", lambda r: r["seconds"])
    row("tool calls", lambda r: r["tool_calls"])
    row("cost (USD)", lambda r: "n/a" if r["cost_usd"] is None else f"{r['cost_usd']:.4f}")
    row("tokens", lambda r: "n/a" if r["tokens"] is None else f"{r['tokens']:,}")
    for s in sides:
        r = out[s]
        print(f"\n[{s}] answer: {(r['answer'] or '(none) ' + str(r['error'] or ''))[:300]}")
    d = Path(__file__).parent / "results"
    d.mkdir(exist_ok=True)
    f = d / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    f.write_text(json.dumps({"site": host, "question": a.question, "start_url": start,
                             "results": out}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nsaved {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
