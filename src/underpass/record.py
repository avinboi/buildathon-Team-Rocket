"""Record a website's hidden API traffic.

Phase 1 (headed): the user logs in and uses the site. Every API request is captured: reads AND actions
(POST/PUT/PATCH/DELETE with their bodies), GraphQL, and classic HTML form posts.
Phase 2 (headless, optional): Underpass re-opens the site with the saved login and explores every
same-site page it can reach, capturing more read traffic. Script URLs are saved so `analyze` can scan
the site's own JavaScript for endpoints nobody clicked.
"""

import json
import time
from pathlib import Path
from urllib.parse import urldefrag, urlparse

from playwright.sync_api import BrowserContext, Response, sync_playwright

from underpass import store

# Third-party telemetry: never part of a site's own API.
NOISE_HOSTS = (
    "google-analytics", "googletagmanager", "doubleclick", "facebook", "fbcdn", "hotjar", "segment.",
    "mixpanel", "sentry", "clarity.ms", "intercom", "amplitude", "posthog", "newrelic", "nr-data",
    "datadoghq", "fullstory", "hubspot", "cloudflareinsights", "recaptcha", "gstatic", "googleapis.com/identitytoolkit",
    "linkedin", "twitter", "tiktok", "bing.com", "yandex", "branch.io", "onesignal", "pusher", "moengage",
    "clevertap", "webengage", "lr-ingest", "logrocket", "bugsnag", "launchdarkly", "statsig", "growthbook",
)
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MAX_BODY = 2_000_000  # bytes of response body kept per request


def _is_noise(url: str) -> bool:
    return any(h in url for h in NOISE_HOSTS)


def _base_domain(host: str) -> str:
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


class Recorder:
    def __init__(self, out: Path, site_domain: str, phase: str):
        self.out = out
        self.site_domain = site_domain
        self.phase = phase
        self.count = 0
        self.writes = 0
        self.scripts: set[str] = set()

    def on_response(self, resp: Response) -> None:
        try:
            self._handle(resp)
        except Exception:
            pass  # a single odd response must never kill the recording

    def _handle(self, resp: Response) -> None:
        req = resp.request
        url = req.url
        if _is_noise(url) or not url.startswith("http"):
            return
        kind = req.resource_type
        host = urlparse(url).hostname or ""
        if kind == "script" and _base_domain(host) == self.site_domain:
            self.scripts.add(url)
            return
        method = req.method.upper()
        is_api = kind in ("xhr", "fetch")
        is_form_post = kind == "document" and method in WRITE_METHODS
        if not (is_api or is_form_post):
            return

        ctype = (resp.headers.get("content-type") or "").lower()
        body = None
        if "json" in ctype or "graphql" in ctype:
            try:
                raw = resp.body()
                if len(raw) <= MAX_BODY:
                    body = json.loads(raw)
            except Exception:
                body = None
        elif method == "GET":
            return  # a GET that isn't JSON (html, images, text) is not an API call we can use
        entry = {
            "t": time.time(),
            "phase": self.phase,
            "method": method,
            "url": url,
            "status": resp.status,
            "req_headers": req.headers,
            "req_body": req.post_data,
            "req_content_type": req.headers.get("content-type"),
            "resp_content_type": ctype,
            "resp_body": body,
            "page": resp.frame.url if resp.frame else None,
        }
        with self.out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")  # ascii-escaped: raw U+2028 would break splitlines()
        self.count += 1
        if method in WRITE_METHODS:
            self.writes += 1


def _wait_until_closed(context: BrowserContext) -> None:
    """Block until the user has closed every tab/window, while still processing browser events."""
    while True:
        pages = [p for p in context.pages if not p.is_closed()]
        if not pages:
            return
        try:
            pages[0].wait_for_timeout(500)
        except Exception:
            pass


def _same_site_links(page, domain: str) -> list[str]:
    try:
        hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
    except Exception:
        return []
    out = []
    for h in hrefs:
        h = urldefrag(h)[0]
        host = urlparse(h).hostname or ""
        if h.startswith("http") and _base_domain(host) == domain and not any(
            x in h.lower() for x in ("logout", "signout", "sign-out", "log-out", "delete", "remove")
        ):
            out.append(h)
    return out


def crawl(context: BrowserContext, start: str, domain: str, max_pages: int, log=print) -> int:
    """Visit same-site pages breadth-first. Links that look destructive (logout/delete) are skipped."""
    seen, queue, visited = {start}, [start], 0
    _p = urlparse(start)
    seen.add(_p.hostname + "/".join("#" if any(c.isdigit() for c in s) else s for s in (_p.path or "/").split("/")))  # landing page, so "/" is not revisited
    page = context.new_page()
    while queue and visited < max_pages:
        url = queue.pop(0)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            page.wait_for_timeout(800)  # let lazy widgets fire their requests
        except Exception as e:
            log(f"  skip {url}: {type(e).__name__}")
            continue
        visited += 1
        log(f"  [{visited}/{max_pages}] {url}")
        for link in _same_site_links(page, domain):
            path = urlparse(link).path
            # one visit per path shape is enough (e.g. /course/123 and /course/456)
            shape = "/".join("#" if any(c.isdigit() for c in seg) else seg for seg in path.split("/"))
            key = urlparse(link).hostname + shape
            if key not in seen:
                seen.add(key)
                queue.append(link)
    page.close()
    return visited


def record(url: str, explore: bool = True, max_pages: int = 25, headless_login: bool = False, log=print) -> Path:
    if "://" not in url:
        url = "https://" + url
    site = store.site_name(url)
    d = store.site_dir(site)
    traffic = d / "traffic.jsonl"
    state = d / "state.json"
    domain = _base_domain(urlparse(url).hostname or "")

    with sync_playwright() as p:
        # Phase 1: the user drives.
        browser = p.chromium.launch(headless=headless_login)
        context = browser.new_context(
            storage_state=str(state) if state.exists() else None, viewport={"width": 1366, "height": 860}
        )
        rec = Recorder(traffic, domain, "user")
        context.on("response", rec.on_response)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        if headless_login:
            page.wait_for_timeout(5000)
        else:
            log(f"\nA browser window is open on {url}.")
            log("  1. Log in if needed.")
            log("  2. Use the site normally: open pages, and do any actions you want your agent to be able to do.")
            log("  3. Close the browser window when you're done.\n")
            _wait_until_closed(context)
        context.storage_state(path=str(state))
        browser.close()
        log(f"Recorded {rec.count} API calls ({rec.writes} actions) while you used the site.")

        # Phase 2: Underpass explores on its own with the saved login.
        if explore:
            log("Exploring the rest of the site on its own...")
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=str(state), viewport={"width": 1366, "height": 860})
            auto = Recorder(traffic, domain, "explore")
            context.on("response", auto.on_response)
            pages = crawl(context, url, domain, max_pages, log)
            context.storage_state(path=str(state))
            browser.close()
            rec.scripts |= auto.scripts
            log(f"Explored {pages} pages and captured {auto.count} more API calls.")

    store.write_json(d / "scripts.json", sorted(rec.scripts))
    store.write_json(d / "site.json", {"site": site, "start_url": url, "domain": domain, "recorded_at": time.time()})
    return d
