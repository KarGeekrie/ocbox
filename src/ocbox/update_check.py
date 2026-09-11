"""Tells the user when their ocbox checkout is behind, and enforces releases.

ocbox runs from a git checkout (see README "Setup"), so an update is a git
update, and the two kinds are treated differently on purpose. A newer `v*` tag
is a release the team decided everyone should run: ocbox refuses to start until
the checkout has it. New commits without a new tag are only mentioned. Either
way ocbox only says what to run (`update_command`) - it doesn't update itself.

The version compared is the checkout's own `git describe`, not the installed
package metadata. An editable install records its version once, at install
time, so after a pull the metadata keeps reporting the old release and a
required update would never clear.

Fetching is best-effort and at most once a day, timestamped in the gitignored
.ocbox/ so nothing lands outside the checkout. A failed fetch (offline, no SSH
agent) never blocks a run by itself - but a newer tag already fetched does,
online or not.

This replaces a check against GitHub's releases/latest endpoint, which never
fired: the project publishes tags, not GitHub Releases, so it always got a 404
and silently reported nothing.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

CHECK_INTERVAL = 24 * 60 * 60
FETCH_TIMEOUT = 10  # seconds - a daily courtesy, never worth a long wait
STATE_FILE = "update-check.json"
TAG_PATTERN = "v[0-9]*"


@dataclass(frozen=True)
class UpdateStatus:
    # A newer release tag: the run must not go ahead until the checkout has it.
    required_tag: str | None = None
    # Untagged commits on the upstream branch: worth a notice, never a block.
    commits_behind: int = 0
    upstream: str | None = None
    current_tag: str | None = None


def parse_version(raw: str) -> tuple[int, ...]:
    """Best-effort dotted-int parse ('v1.2.3' / '1.2.3.dev4+g1234abc' -> (1, 2, 3[, 4])).

    Good enough to order release tags against each other; anything that doesn't
    parse at all sorts as older rather than raising.
    """
    core = raw.lstrip("v").split("+", 1)[0].split("-", 1)[0]
    parts: list[int] = []
    for chunk in core.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _git(repo: Path, *args: str, timeout: float = 5) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # Never stop to ask for a password or a passphrase mid-run: fail instead.
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )


def _output(repo: Path, *args: str, timeout: float = 5) -> str | None:
    try:
        result = _git(repo, *args, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _is_checkout(repo: Path) -> bool:
    return _output(repo, "rev-parse", "--is-inside-work-tree") == "true"


def _record_fetch(state_dir: Path, now: float) -> None:
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / STATE_FILE).write_text(json.dumps({"fetched_at": now}))
    except OSError:
        pass  # the check still works this run; it just fetches again next time


def _fetch_if_due(repo: Path, state_dir: Path, now: float) -> None:
    try:
        last = json.loads((state_dir / STATE_FILE).read_text()).get("fetched_at", 0)
    except (OSError, ValueError, AttributeError):
        last = 0
    if now - last < CHECK_INTERVAL:
        return
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        _git(repo, "fetch", "--tags", "--quiet", timeout=FETCH_TIMEOUT)
    # Recorded even when the fetch failed, so an offline machine isn't slowed
    # down by a doomed attempt on every single run.
    _record_fetch(state_dir, now)


def _newest_tag(repo: Path) -> str | None:
    listed = _output(repo, "tag", "--list", TAG_PATTERN) or ""
    tags = [tag for tag in listed.split() if parse_version(tag)]
    return max(tags, key=parse_version, default=None)


def _upstream(repo: Path) -> str | None:
    return _output(
        repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    ) or _output(repo, "rev-parse", "--abbrev-ref", "origin/HEAD")


def check(repo: Path, state_dir: Path, *, now: float | None = None) -> UpdateStatus:
    """Where the checkout at `repo` stands against its remote. Never raises."""
    if os.environ.get("OCBOX_SKIP_UPDATE_CHECK") or not _is_checkout(repo):
        return UpdateStatus()
    _fetch_if_due(repo, state_dir, time.time() if now is None else now)

    current = _output(repo, "describe", "--tags", "--abbrev=0", "--match", TAG_PATTERN, "HEAD")
    newest = _newest_tag(repo)
    if newest and (current is None or parse_version(newest) > parse_version(current)):
        return UpdateStatus(required_tag=newest, current_tag=current)

    upstream = _upstream(repo)
    behind = _output(repo, "rev-list", "--count", f"HEAD..{upstream}") if upstream else None
    return UpdateStatus(
        commits_behind=int(behind) if behind and behind.isdigit() else 0,
        upstream=upstream,
        current_tag=current,
    )


def update_command(repo: Path) -> str:
    """The command that brings the checkout at `repo` up to date, to show the user.

    The pull is what updates: ocbox is an editable install of this checkout
    (README "Setup"), so a pip install on its own has nothing new to install.
    The pip install that follows refreshes the package metadata - version,
    entry points, dependencies - which an editable install otherwise keeps from
    the day it was first installed.
    """
    return f"git -C {repo} pull --ff-only && pip install --upgrade -e {repo}"
