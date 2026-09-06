"""Auth token generation for OpenCode's web UI (HTTP Basic Auth via
OPENCODE_SERVER_PASSWORD / OPENCODE_SERVER_USERNAME)."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

DEFAULT_USERNAME = "opencode"


def generate_token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)


def write_env_file(path: Path, token: str, username: str = DEFAULT_USERNAME) -> None:
    """Writes a podman --env-file with the web UI credentials.

    Creates the file with mode 0600 from the moment it exists - never a
    world-readable window - since this is a secret passed to the container.
    """
    lines = [
        f"OPENCODE_SERVER_USERNAME={username}",
        f"OPENCODE_SERVER_PASSWORD={token}",
        "",
    ]
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, "\n".join(lines).encode())
    finally:
        os.close(fd)


def build_web_url(host_web_port: int) -> str:
    return f"http://127.0.0.1:{host_web_port}"


def format_connect_banner(url: str, username: str, token: str) -> str:
    return (
        "\nOpenCode is ready.\n"
        f"  URL:      {url}\n"
        f"  Username: {username}\n"
        f"  Password: {token}\n"
        "  (keep this secret - do not share this terminal output)\n"
    )
