"""ocbox - runs OpenCode in a rootless-Podman sandbox."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ocbox")
except PackageNotFoundError:  # running from a source checkout, never installed
    __version__ = "0+unknown"
