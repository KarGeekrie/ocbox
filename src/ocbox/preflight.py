"""Verifies the host is ready to run rootless Podman sandboxes.

ocbox never installs Podman or escalates privileges itself - every check here
either passes or fails with a specific, actionable remediation message.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


class PreflightError(Exception):
    """Raised when the host isn't ready to run a rootless Podman sandbox."""


def check_podman_installed() -> str:
    path = shutil.which("podman")
    if path is None:
        raise PreflightError(
            "podman is not installed or not on PATH.\n"
            "Install it via your distro's package manager, e.g.:\n"
            "  Debian/Ubuntu: sudo apt install podman\n"
            "  Fedora:        sudo dnf install podman\n"
            "See https://podman.io/docs/installation for other distros."
        )
    try:
        result = subprocess.run(
            ["podman", "--version"], capture_output=True, text=True, check=True
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        raise PreflightError(
            f"Found podman at {path} but `podman --version` failed: {exc}"
        ) from exc
    return result.stdout.strip()


def check_rootless() -> None:
    try:
        result = subprocess.run(
            ["podman", "info", "--format", "json"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        raise PreflightError(f"`podman info` failed: {exc}") from exc

    try:
        info = json.loads(result.stdout)
        rootless = info["host"]["security"]["rootless"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PreflightError(
            f"Could not determine rootless status from `podman info`: {exc}"
        ) from exc

    if not rootless:
        raise PreflightError(
            "podman is running in rootful mode (as root or via a system service).\n"
            "ocbox requires rootless Podman: run it as your normal user, not as root, "
            "and without `sudo`."
        )


def check_subuid_subgid() -> None:
    uid = os.getuid()
    username = os.environ.get("USER") or os.environ.get("LOGNAME") or str(uid)

    def _has_range(path: Path) -> bool:
        if not path.exists():
            return False
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            name = line.split(":", 1)[0]
            if name in (username, str(uid)):
                return True
        return False

    missing = [
        name
        for name, path in (("subuid", Path("/etc/subuid")), ("subgid", Path("/etc/subgid")))
        if not _has_range(path)
    ]
    if missing:
        raise PreflightError(
            f"No {'/'.join(missing)} range configured for user '{username}'.\n"
            "Rootless Podman needs a subuid/subgid range to create user namespaces. Fix with:\n"
            f"  sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 {username}\n"
            "then log out and back in (or run `podman system migrate`)."
        )


def run_preflight() -> None:
    check_podman_installed()
    check_rootless()
    check_subuid_subgid()
