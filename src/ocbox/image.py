"""Base image bootstrap and per-project derived image layering extra apt/uv
packages requested interactively via packages.py.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import shlex
from pathlib import Path

from ocbox.podman_client import PodmanClient


def data_dir() -> Path:
    return Path(str(importlib.resources.files("ocbox.data")))


def ensure_base_image(podman: PodmanClient, tag: str) -> None:
    """Builds the base image (Debian + uv + OpenCode + relay.py) if not already cached."""
    if podman.image_exists(tag):
        return
    containerfile = (data_dir() / "Containerfile").read_text()
    podman.build(containerfile, tag, context_dir=str(data_dir()))


def packages_fingerprint(apt_pkgs: list[str], uv_pkgs: list[str]) -> str:
    payload = "apt:" + ",".join(sorted(apt_pkgs)) + "|uv:" + ",".join(sorted(uv_pkgs))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def image_exists(podman: PodmanClient, tag: str) -> bool:
    return podman.image_exists(tag)


def build_project_image(
    podman: PodmanClient,
    base_tag: str,
    project_tag: str,
    apt_pkgs: list[str],
    uv_pkgs: list[str],
    empty_context: Path,
) -> None:
    """Layers the requested extra packages onto base_tag, tagged as project_tag.

    Runs with normal (non-isolated) networking - this is the only phase of
    ocbox's lifecycle that touches the open internet, and it never overlaps
    with the sandboxed run itself. `empty_context` must be an existing,
    otherwise-empty directory (podman build requires a build context even
    when nothing is COPYed).
    """
    lines = [f"FROM {base_tag}"]
    if apt_pkgs:
        pkg_args = " ".join(shlex.quote(p) for p in apt_pkgs)
        lines.append(
            "RUN apt-get update && apt-get install -y --no-install-recommends "
            f"{pkg_args} && rm -rf /var/lib/apt/lists/*"
        )
    if uv_pkgs:
        pkg_args = " ".join(shlex.quote(p) for p in uv_pkgs)
        lines.append(f"RUN uv pip install --system {pkg_args}")
    containerfile = "\n".join(lines) + "\n"
    podman.build(containerfile, project_tag, context_dir=str(empty_context))
