"""Record a website's hidden API traffic.

Phase 1 (headed): the user logs in and uses the site. Every API request is captured: reads AND actions
(POST/PUT/PATCH/DELETE with their bodies), GraphQL, and classic HTML form posts.
Phase 2 (headless, optional): Underpass re-opens the site with the saved login and explores every
same-site page it can reach, capturing more read traffic. Script URLs are saved so `analyze` can scan
the site's own JavaScript for endpoints nobody clicked.
"""

import json
import re
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
LOGINISH = re.compile(r"login|signin|sign-in|auth|session|token|otp|verify|callback|oauth|sso", re.I)
SESSION_COOKIE = re.compile(r"sess|auth|token|sid|jwt|login|user", re.I)
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
        self.auth_seen = False  # a logged-in API call or a successful login request was observed

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
        if 200 <= resp.status < 300 and (
            any(k.lower() == "authorization" for k in req.headers)
            or (method in WRITE_METHODS and LOGINISH.search(urlparse(url).path))
        ):
            self.auth_seen = True


def _launch(p, headless: bool, log=print):
    """Launch Chromium; on first use, download it automatically."""
    try:
        return p.chromium.launch(headless=headless)
    except Exception as e:
        if "Executable doesn't exist" not in str(e) and "playwright install" not in str(e):
            raise
        import subprocess
        import sys

        log("First run: downloading the browser Underpass uses (one time, ~150 MB)...")
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        return p.chromium.launch(headless=headless)


def _session_cookies(context, domain: str) -> set[str]:
    try:
        return {c["name"] for c in context.cookies() if c["domain"].lstrip(".").endswith(domain) and SESSION_COOKIE.search(c["name"])}
    except Exception:
        return set()


def _wait_for_login(context: BrowserContext, rec: "Recorder", domain: str, log=print) -> str:
    """Return as soon as the user is logged in (or closes the window). The user only has to log in."""
    start_cookies = _session_cookies(context, domain)
    ready_since = None
    while True:
        pages = [p for p in context.pages if not p.is_closed()]
        if not pages:
            return "closed"
        page = pages[-1]
        try:
            page.wait_for_timeout(500)
        except Exception:
            continue
        on_login_page = bool(LOGINISH.search(urlparse(page.url).path)) or "login" in page.url.lower()
        new_cookie = bool(_session_cookies(context, domain) - start_cookies)
        if (rec.auth_seen or new_cookie) and not on_login_page:
            ready_since = ready_since or time.time()
            if time.time() - ready_since > 3:  # let the dashboard finish loading
                return "logged_in"
        else:
            ready_since = None


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


def _shape_key(link: str) -> str:
    u = urlparse(link)
    return (u.hostname or "") + "/".join("#" if any(c.isdigit() for c in seg) else seg for seg in (u.path or "/").split("/"))


def crawl(context: BrowserContext, start: str, domain: str, max_pages: int, log=print, parallel: int = 6) -> int:
    """Visit same-site pages breadth-first, `parallel` tabs at a time. Logout/delete links are skipped."""
    seen, queue, visited = {_shape_key(start)}, [start], 0
    while queue and visited < max_pages:
        batch = []
        while queue and len(batch) < min(parallel, max_pages - visited):
            batch.append(queue.pop(0))
        tabs = []
        for url in batch:
            tab = context.new_page()
            try:
                tab.goto(url, wait_until="commit", timeout=20_000)  # start loading; don't wait
                tabs.append((url, tab))
            except Exception as e:
                log(f"  skip {url}: {type(e).__name__}")
                tab.close()
        if not tabs:
            continue
        # all tabs load at once; give their API calls time to fire
        deadline = time.time() + 6
        for _, tab in tabs:
            try:
                tab.wait_for_load_state("networkidle", timeout=max(500, int((deadline - time.time()) * 1000)))
            except Exception:
                pass
        for url, tab in tabs:
            visited += 1
            log(f"  [{visited}/{max_pages}] {url}")
            for link in _same_site_links(tab, domain):
                key = _shape_key(link)
                if key not in seen:
                    seen.add(key)
                    queue.append(link)
            tab.close()
    return visited


def record(url: str, explore: bool = True, max_pages: int = 40, headless_login: bool = False, log=print) -> Path:
    if "://" not in url:
        url = "https://" + url
    site = store.site_name(url)
    d = store.site_dir(site)
    traffic = d / "traffic.jsonl"
    state = d / "state.json"
    domain = _base_domain(urlparse(url).hostname or "")

    with sync_playwright() as p:
        # Phase 1: the user drives.
        browser = _launch(p, headless=headless_login, log=log)
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
            log("  Just log in (and approve any sign-in prompts). Underpass takes over automatically after that.")
            log("  (If the site needs no login, close the window.)\n")
            if _wait_for_login(context, rec, domain, log) == "logged_in":
                log("Logged in. Underpass takes it from here.")
        context.storage_state(path=str(state))
        browser.close()
        log(f"Captured {rec.count} API calls during login.")

        # Phase 2: Underpass explores on its own with the saved login.
        if explore:
            log("Exploring the rest of the site on its own...")
            browser = _launch(p, headless=True, log=log)
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
