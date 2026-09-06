"""Interactive prompt for extra apt/uv packages to bake into the sandbox image."""

from __future__ import annotations

import sys

from ocbox.config import Config


def prompt_extra_packages(
    cfg: Config,
    *,
    non_interactive: bool,
    cli_apt: list[str] | None = None,
    cli_uv: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Returns (apt_packages, uv_packages) to layer onto the sandbox image.

    --apt/--uv flags take precedence; otherwise prompts interactively unless
    stdin isn't a TTY or --yes was passed, in which case config defaults are
    used as-is (keeps `ocbox` scriptable/CI-friendly).
    """
    if cli_apt is not None or cli_uv is not None:
        return list(cli_apt or []), list(cli_uv or [])

    if non_interactive or not sys.stdin.isatty():
        return list(cfg.extra_apt_default), list(cfg.extra_uv_default)

    apt_raw = input("Add extra apt packages? (space-separated, blank to skip): ").strip()
    uv_raw = input("Add extra Python packages via uv? (space-separated, blank to skip): ").strip()

    apt_pkgs = apt_raw.split() if apt_raw else list(cfg.extra_apt_default)
    uv_pkgs = uv_raw.split() if uv_raw else list(cfg.extra_uv_default)
    return apt_pkgs, uv_pkgs
