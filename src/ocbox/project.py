"""Per-project identity and XDG-ish directories used to scope sandbox state."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def project_slug(cwd: Path) -> str:
    resolved = str(cwd.resolve())
    digest = hashlib.sha256(resolved.encode()).hexdigest()[:12]
    return f"{cwd.resolve().name}-{digest}"


def _mkdir_private(path: Path) -> None:
    """Creates `path` (and any missing parents) with 0700 permissions.

    Path.mkdir(mode=...) only ever applies `mode` to the leaf directory it
    creates - any parents it has to create along the way get the default,
    umask-based permissions instead. Walking up and chmod-ing each level we
    might have just created avoids leaving a world-readable/executable
    parent (e.g. /tmp/ocbox-<uid>) sitting above a supposedly-private leaf.
    """
    to_chmod = []
    probe = path
    while not probe.exists():
        to_chmod.append(probe)
        probe = probe.parent
    path.mkdir(parents=True, exist_ok=True)
    for created in to_chmod:
        os.chmod(created, 0o700)


def _xdg_runtime_dir() -> Path:
    raw = os.environ.get("XDG_RUNTIME_DIR")
    if raw:
        return Path(raw)
    path = Path(f"/tmp/ocbox-{os.getuid()}")
    _mkdir_private(path)
    return path


def _xdg_state_home() -> Path:
    raw = os.environ.get("XDG_STATE_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".local" / "state"


def _xdg_cache_home() -> Path:
    raw = os.environ.get("XDG_CACHE_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".cache"


def cache_dir() -> Path:
    """Global (not per-project) cache dir - currently just the update-check stamp."""
    path = _xdg_cache_home() / "ocbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_dir(slug: str) -> Path:
    path = _xdg_runtime_dir() / "ocbox" / slug
    _mkdir_private(path)
    return path


def state_dir(slug: str) -> Path:
    path = _xdg_state_home() / "ocbox" / slug
    path.mkdir(parents=True, exist_ok=True)
    return path
