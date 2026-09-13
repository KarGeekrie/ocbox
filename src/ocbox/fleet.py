"""Cross-project operations over ocbox-managed containers: list, stop, attach,
exec. Independent of sandbox.run() - these act on containers already started
by a (possibly different) previous ocbox invocation, for any project
directory, not just the current one.

Identifies "ocbox containers" by the `ocbox.managed` label build_podman_run_argv
attaches to every container it starts (see sandbox.py) - name-prefix matching
alone would risk colliding with an unrelated container someone happened to name
`ocbox-something`. Sandboxes started by an ocbox predating this label won't
carry it, and so won't appear here until restarted; `podman ps` directly is
always the fallback for that.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ocbox import auth, project
from ocbox.podman_client import PodmanClient

MANAGED_LABEL = "ocbox.managed"
SLUG_LABEL = "ocbox.slug"
MODE_LABEL = "ocbox.mode"
WORKDIR_LABEL = "ocbox.workdir"


@dataclass
class SandboxInfo:
    container_name: str
    slug: str
    workdir: str | None
    mode: str | None
    status: str | None
    web_url: str | None


def _connect_url(slug: str) -> str | None:
    """The host web URL for a running sandbox, from the connect.json written
    once sandbox.run() knows the host port (not knowable at container-creation
    time, so it isn't a label - see sandbox.py). None for tui mode, or a
    sandbox whose run_dir predates this file."""
    port = _read_host_web_port(project.runtime_dir_path(slug))
    return auth.build_web_url(port) if port is not None else None


def _read_host_web_port(run_dir: Path) -> int | None:
    """The host web port recorded in `run_dir`'s connect.json, or None.

    The run directory is bind-mounted read-write into the sandbox, so what it
    holds is only as trustworthy as the sandbox. Anything but a real TCP port
    is refused: `"1@evil.example"` would otherwise be printed as
    `http://127.0.0.1:1@evil.example`, a link to another host.
    """
    try:
        port = json.loads((run_dir / "connect.json").read_text())["host_web_port"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        return None
    return port


def list_running(podman: PodmanClient) -> list[SandboxInfo]:
    """Every currently-running ocbox-managed container, across all projects."""
    containers = podman.list_containers(label=MANAGED_LABEL)
    infos = []
    for entry in containers:
        labels = entry.get("Labels") or {}
        slug = labels.get(SLUG_LABEL, "")
        names = entry.get("Names") or []
        infos.append(
            SandboxInfo(
                container_name=names[0] if names else "",
                slug=slug,
                workdir=labels.get(WORKDIR_LABEL),
                mode=labels.get(MODE_LABEL),
                status=entry.get("Status"),
                web_url=_connect_url(slug) if slug else None,
            )
        )
    return infos


def resolve_target(target: str) -> str:
    """A container name, bare slug, or project path (e.g. `.`) -> the
    container name ocbox would have started it under.

    Known edge case (harmless in practice): a bare slug that itself happens to
    start with "ocbox-" - only possible when the project directory's own name
    does - is indistinguishable from an already-full container name and is
    returned unprefixed. Pass the project path instead of the slug to sidestep
    it.
    """
    if target.startswith("ocbox-"):
        return target
    path = Path(target)
    if path.is_dir():
        return f"ocbox-{project.project_slug(path)}"
    return f"ocbox-{target}"


def stop_sandbox(podman: PodmanClient, target: str) -> int:
    name = resolve_target(target)
    if not podman.container_exists(name):
        print(f"ocbox: no running sandbox found for {target!r} (looked for {name})")
        return 1
    podman.stop(name)
    if podman.container_exists(name):
        print(f"ocbox: {name} did not stop cleanly")
        return 1
    print(f"ocbox: stopped {name}")
    return 0


def attach_sandbox(podman: PodmanClient, target: str) -> int:
    """Redisplays the connect banner (URL/username/password) for an already-
    running sandbox - for reconnecting to a --detach'd one whose banner
    scrolled off or went to a log file you didn't keep open. Does not open a
    shell - see exec_shell for that."""
    name = resolve_target(target)
    if not podman.container_exists(name):
        print(f"ocbox: no running sandbox found for {target!r}")
        return 1
    slug = name.removeprefix("ocbox-")
    # Path only: attaching reads a run directory someone else owns and created.
    run_dir = project.runtime_dir_path(slug)
    port = _read_host_web_port(run_dir)
    try:
        creds = auth.read_env_file(run_dir / "env")
        username = creds["OPENCODE_SERVER_USERNAME"]
        password = creds["OPENCODE_SERVER_PASSWORD"]
    except (OSError, KeyError):
        port = None
    if port is None:
        print(
            f"ocbox: {name} is running but its connection info isn't available "
            "(tui mode, or it predates this ocbox version)"
        )
        return 1
    url = auth.build_web_url(port)
    print(auth.format_connect_banner(url, username, password))
    return 0


def exec_shell(podman: PodmanClient, target: str, cmd: list[str] | None = None) -> int:
    """Opens an interactive shell (or runs `cmd`) inside a running sandbox -
    for poking around inside the container, unrelated to the OpenCode session
    itself. Inherits this process's stdio for a real TTY."""
    name = resolve_target(target)
    if not podman.container_exists(name):
        print(f"ocbox: no running sandbox found for {target!r}")
        return 1
    return podman.exec_interactive(name, cmd or ["sh"])
