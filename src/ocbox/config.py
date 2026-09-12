"""Loads ocbox's optional conf.py configuration files."""

from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

from ocbox.image import DEFAULT_BASE_OS, DISTROS

GLOBAL_CONFIG_PATH = Path.home() / ".config" / "ocbox" / "conf.py"
PROJECT_CONFIG_NAME = "ocbox.conf.py"

# Where the LLM is used to be set here. It now comes from
# provider.local.options.baseURL in opencode-config/opencode.jsonc - the one
# place that address is written - so these are rejected rather than silently
# ignored, which would leave someone editing a value that does nothing.
MOVED_TO_OPENCODE_JSONC = ("LLM_HOST", "LLM_PORT")

# Every setting ocbox reads from a conf.py. Used to warn about an ALL-CAPS name
# that is neither one of these nor a moved key - a typo like MEMORY_LIMITS would
# otherwise be ignored in silence, leaving someone editing a value that does
# nothing.
KNOWN_SETTINGS = frozenset(
    {
        "BASE_OS",
        "BASE_IMAGE",
        "CONTAINER_WEB_PORT",
        "HOST_WEB_PORT",
        "EXTRA_APT_DEFAULT",
        "EXTRA_UV_DEFAULT",
        "MEMORY_LIMIT",
        "PIDS_LIMIT",
    }
)

# ALL-CAPS names that legitimately show up in a conf.py without being a
# setting - so the unknown-setting warning below doesn't fire on them.
# TYPE_CHECKING is the common case: `from typing import TYPE_CHECKING` is a
# standard way to guard type-only imports, and would otherwise be flagged as
# an unrecognised setting on every conf.py that uses it.
NOT_A_SETTING = frozenset({"TYPE_CHECKING"})


def _string_list(value: object, name: str, path: Path | None) -> list[str]:
    """Coerces a list/tuple of package names, rejecting a bare string.

    `list("git")` silently yields `['g', 'i', 't']`, so a `conf.py` that writes
    EXTRA_APT_DEFAULT = "git" (instead of ["git"]) would install three bogus
    packages. Catch that here rather than at image-build time.
    """
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ConfigError(
            f"{path or 'conf.py'} sets {name} to {value!r}; it must be a list of "
            f'package-name strings, e.g. {name} = ["git"].'
        )
    return [str(item) for item in value]


class ConfigError(Exception):
    """Raised when a conf.py named explicitly is missing, or a conf.py is invalid."""


@dataclass
class Config:
    base_os: str = DEFAULT_BASE_OS
    base_image: str = "ocbox/base:latest"
    container_web_port: int = 4096
    host_web_port: int | None = None
    extra_apt_default: list[str] = field(default_factory=list)
    extra_uv_default: list[str] = field(default_factory=list)
    memory_limit: str | None = None
    pids_limit: int | None = None


def _load_module_from_path(path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(f"ocbox_conf_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ConfigError(f"Could not load config module from {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # broad on purpose - surfaced to the user as a ConfigError
        raise ConfigError(f"Error executing {path}: {exc}") from exc
    return module


def _apply_overrides(
    cfg: Config, module: types.ModuleType, path: Path | None = None
) -> Config:
    moved = [name for name in MOVED_TO_OPENCODE_JSONC if hasattr(module, name)]
    if moved:
        raise ConfigError(
            f"{path or 'conf.py'} sets {' and '.join(moved)}, which ocbox no longer "
            "reads: the LLM's address now comes from provider.local.options.baseURL "
            "in opencode-config/opencode.jsonc. Remove them from this file."
        )
    unknown = sorted(
        name
        for name in vars(module)
        if name.isupper()
        and not name.startswith("_")
        and name not in KNOWN_SETTINGS
        and name not in MOVED_TO_OPENCODE_JSONC
        and name not in NOT_A_SETTING
    )
    if unknown:
        print(
            f"ocbox: warning: {path or 'conf.py'} sets unrecognised setting(s) "
            f"{', '.join(unknown)} - ignored (did you mean one of "
            f"{', '.join(sorted(KNOWN_SETTINGS))}?)",
            file=sys.stderr,
        )
    if hasattr(module, "BASE_OS"):
        base_os = str(module.BASE_OS)
        if base_os not in DISTROS:
            raise ConfigError(
                f"BASE_OS {base_os!r} is not supported; choose one of: "
                f"{', '.join(sorted(DISTROS))}"
            )
        cfg.base_os = base_os
    if hasattr(module, "BASE_IMAGE"):
        cfg.base_image = str(module.BASE_IMAGE)
    if hasattr(module, "CONTAINER_WEB_PORT"):
        cfg.container_web_port = int(module.CONTAINER_WEB_PORT)
    if hasattr(module, "HOST_WEB_PORT"):
        cfg.host_web_port = module.HOST_WEB_PORT
    if hasattr(module, "EXTRA_APT_DEFAULT"):
        cfg.extra_apt_default = _string_list(module.EXTRA_APT_DEFAULT, "EXTRA_APT_DEFAULT", path)
    if hasattr(module, "EXTRA_UV_DEFAULT"):
        cfg.extra_uv_default = _string_list(module.EXTRA_UV_DEFAULT, "EXTRA_UV_DEFAULT", path)
    if hasattr(module, "MEMORY_LIMIT"):
        cfg.memory_limit = module.MEMORY_LIMIT
    if hasattr(module, "PIDS_LIMIT"):
        cfg.pids_limit = module.PIDS_LIMIT
    return cfg


def load_config(
    explicit_path: Path | None = None,
    *,
    project_dir: Path | None = None,
    global_path: Path = GLOBAL_CONFIG_PATH,
) -> Config:
    """Loads conf.py if there is one, then an optional project-local ocbox.conf.py.

    Every setting has a default, so neither file is required. A path given
    explicitly (--config) must exist, though: naming a file that isn't there is
    a mistake worth reporting rather than quietly running on defaults.
    """
    if explicit_path is not None and not explicit_path.exists():
        raise ConfigError(f"No config found at {explicit_path}.")

    cfg = Config()
    base_path = explicit_path or global_path
    if base_path.exists():
        cfg = _apply_overrides(cfg, _load_module_from_path(base_path), base_path)

    if project_dir is not None:
        project_conf = project_dir / PROJECT_CONFIG_NAME
        if project_conf.exists():
            cfg = _apply_overrides(cfg, _load_module_from_path(project_conf), project_conf)

    return cfg
