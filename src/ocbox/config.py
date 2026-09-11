"""Loads ocbox's optional conf.py configuration files."""

from __future__ import annotations

import importlib.util
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
        cfg.extra_apt_default = list(module.EXTRA_APT_DEFAULT)
    if hasattr(module, "EXTRA_UV_DEFAULT"):
        cfg.extra_uv_default = list(module.EXTRA_UV_DEFAULT)
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
