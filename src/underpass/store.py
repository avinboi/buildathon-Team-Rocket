"""Where Underpass keeps per-site data.

Everything lives under ~/.underpass/sites/<site>/ (override with UNDERPASS_HOME), outside any git repo,
because recordings contain the user's login session.
"""

import json
import os
from pathlib import Path
from urllib.parse import urlparse


def home() -> Path:
    return Path(os.environ.get("UNDERPASS_HOME", Path.home() / ".underpass"))


def site_name(url_or_name: str) -> str:
    """'https://coach.mastersunion.org/x' -> 'coach.mastersunion.org'. A bare name is returned as is."""
    if "/" not in url_or_name and "." not in url_or_name:
        return url_or_name
    if "://" not in url_or_name:
        url_or_name = "https://" + url_or_name
    host = urlparse(url_or_name).hostname or url_or_name
    return host.removeprefix("www.")


def site_dir(site: str) -> Path:
    d = home() / "sites" / site_name(site)
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
