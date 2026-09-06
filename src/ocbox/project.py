"""Per-project identity and XDG-ish directories used to scope sandbox state."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def project_slug(cwd: Path) -> str:
    resolved = str(cwd.resolve())
    digest = hashlib.sha256(resolved.encode()).hexdigest()[:12]
    return f"{cwd.resolve().name}-{digest}"


def _xdg_runtime_dir() -> Path:
    raw = os.environ.get("XDG_RUNTIME_DIR")
    if raw:
        return Path(raw)
    return Path(f"/tmp/ocbox-{os.getuid()}")


def _xdg_state_home() -> Path:
    raw = os.environ.get("XDG_STATE_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".local" / "state"


def runtime_dir(slug: str) -> Path:
    path = _xdg_runtime_dir() / "ocbox" / slug
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def state_dir(slug: str) -> Path:
    path = _xdg_state_home() / "ocbox" / slug
    path.mkdir(parents=True, exist_ok=True)
    return path
