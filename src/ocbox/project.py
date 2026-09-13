"""Per-project identity and XDG-ish directories used to scope sandbox state."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path


def project_slug(cwd: Path) -> str:
    """A per-directory identifier safe to embed in podman image/volume/container
    names.

    The slug is reused verbatim in an image repository name
    (`ocbox/project-<slug>`) and in volume/container names, and podman is strict
    about both: image repository names must be lowercase, and volume/container
    names must match `[a-zA-Z0-9][a-zA-Z0-9_.-]*`. So the human-readable prefix
    is lowercased and any character outside `[a-z0-9]` collapsed to `-` (a very
    common case: a project directory called `MyApp` or `mes projets`). The
    sha256 digest still guarantees uniqueness per resolved path even when two
    different names normalise to the same prefix.
    """
    resolved = cwd.resolve()
    digest = hashlib.sha256(str(resolved).encode()).hexdigest()[:12]
    prefix = re.sub(r"[^a-z0-9]+", "-", resolved.name.lower()).strip("-")
    return f"{prefix}-{digest}" if prefix else digest


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
    """The base directory - computed, never created.

    The `/tmp` fallback used to be created here, which meant merely *asking*
    for a path had a side effect. Creation belongs to `runtime_dir()`, whose
    `_mkdir_private()` already creates every missing ancestor at 0700 - so the
    fallback still ends up private, just at the point something actually
    writes there.
    """
    raw = os.environ.get("XDG_RUNTIME_DIR")
    if raw:
        return Path(raw)
    return Path(f"/tmp/ocbox-{os.getuid()}")


def _xdg_state_home() -> Path:
    raw = os.environ.get("XDG_STATE_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".local" / "state"


def runtime_dir_path(slug: str) -> Path:
    """Where a project's per-run files live - computed, never created.

    The reading side needs this: `ocbox list`/`attach` and the start-up check
    ask about *other* projects' slugs, and `runtime_dir()` would create a
    directory for each one just to look for a `connect.json` inside it -
    scattering empty 0700 directories through $XDG_RUNTIME_DIR for every
    sandbox ocbox has ever seen. Whoever owns the run calls `runtime_dir()`.
    """
    return _xdg_runtime_dir() / "ocbox" / slug


def runtime_dir(slug: str) -> Path:
    """`runtime_dir_path()`, created 0700 - for the run that owns it."""
    path = runtime_dir_path(slug)
    _mkdir_private(path)
    # Re-assert 0700 even when the directory already existed: a compromised
    # sandbox (same uid under --userns=keep-id) can chmod its bind-mounted
    # /run/ocbox, and a directory left at e.g. 0500 would defeat the teardown
    # cleanup that clears this run's sockets and secrets.
    os.chmod(path, 0o700)
    return path


def state_dir(slug: str) -> Path:
    path = _xdg_state_home() / "ocbox" / slug
    path.mkdir(parents=True, exist_ok=True)
    return path
