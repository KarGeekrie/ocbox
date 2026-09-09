"""Checks GitHub for a newer ocbox release, at most once a day.

Deliberately hardcoded to this project's own repo - there's nothing to
configure - and deliberately best-effort: any failure (offline, rate-limited,
no releases yet) is swallowed, since this is a courtesy notice and must never
slow down or break an actual run.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from ocbox import __version__

LATEST_RELEASE_URL = "https://api.github.com/repos/KarGeekrie/ocbox/releases/latest"
CHECK_INTERVAL = 24 * 60 * 60
REQUEST_TIMEOUT = 2  # seconds - only spent on a cache miss, at most once a day


def _cache_file(cache_dir: Path) -> Path:
    return cache_dir / "update-check.json"


def _read_cache(cache_file: Path) -> dict | None:
    try:
        return json.loads(cache_file.read_text())
    except (OSError, ValueError):
        return None


def _fetch_latest_tag() -> str | None:
    request = urllib.request.Request(
        LATEST_RELEASE_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "ocbox"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            data = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    tag = data.get("tag_name")
    return str(tag) if tag else None


def _parse_version(raw: str) -> tuple[int, ...]:
    """Best-effort dotted-int parse ('v1.2.3' / '1.2.3.dev4+g1234abc' -> (1, 2, 3[, 4])).

    Good enough to order tagged releases against each other; anything that
    doesn't parse at all just sorts as older rather than raising.
    """
    core = raw.lstrip("v").split("+", 1)[0].split("-", 1)[0]
    parts: list[int] = []
    for chunk in core.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def check_for_update(cache_dir: Path, *, current_version: str = __version__) -> str | None:
    """Returns the latest release tag if it's newer than `current_version`, else None."""
    if os.environ.get("OCBOX_SKIP_UPDATE_CHECK"):
        return None

    cache_file = _cache_file(cache_dir)
    cached = _read_cache(cache_file)
    now = time.time()
    if cached is not None and now - cached.get("checked_at", 0) < CHECK_INTERVAL:
        latest = cached.get("latest")
    else:
        latest = _fetch_latest_tag()
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps({"checked_at": now, "latest": latest}))
        except OSError:
            pass  # the notice still works this run, just won't be cached

    if not latest or _parse_version(latest) <= _parse_version(current_version):
        return None
    return latest
