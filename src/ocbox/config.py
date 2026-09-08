"""Loads ocbox's conf.py configuration files."""

from __future__ import annotations

import importlib.util
import types
from dataclasses import dataclass, field
from pathlib import Path

GLOBAL_CONFIG_PATH = Path.home() / ".config" / "ocbox" / "conf.py"
PROJECT_CONFIG_NAME = "ocbox.conf.py"

EXAMPLE_CONFIG = '''\
# ~/.config/ocbox/conf.py
#
# Required: where ocbox's network relay reaches your locally-running LLM server.
LLM_HOST = "127.0.0.1"
LLM_PORT = 11434

# Optional overrides (defaults shown):
# BASE_IMAGE = "ocbox/base:latest"
# CONTAINER_WEB_PORT = 4096
# HOST_WEB_PORT = None          # None picks a free ephemeral port
# EXTRA_APT_DEFAULT = []
# EXTRA_UV_DEFAULT = []
# MEMORY_LIMIT = None           # e.g. "2g"
# PIDS_LIMIT = None             # e.g. 512
'''


class ConfigError(Exception):
    """Raised when conf.py is missing or invalid."""


@dataclass
class Config:
    llm_host: str
    llm_port: int
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


def _apply_overrides(cfg: Config, module: types.ModuleType) -> Config:
    if hasattr(module, "LLM_HOST"):
        cfg.llm_host = str(module.LLM_HOST)
    if hasattr(module, "LLM_PORT"):
        cfg.llm_port = int(module.LLM_PORT)
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
    """Loads the global conf.py, then an optional project-local ocbox.conf.py override.

    Raises ConfigError if the global config is missing or doesn't define LLM_HOST/LLM_PORT.
    """
    base_path = explicit_path or global_path
    if not base_path.exists():
        raise ConfigError(
            f"No config found at {base_path}.\n"
            "Create it with at least:\n\n"
            f"{EXAMPLE_CONFIG}"
        )

    module = _load_module_from_path(base_path)
    if not hasattr(module, "LLM_HOST") or not hasattr(module, "LLM_PORT"):
        raise ConfigError(
            f"{base_path} must define LLM_HOST and LLM_PORT.\n\nExample:\n\n{EXAMPLE_CONFIG}"
        )

    cfg = Config(llm_host=str(module.LLM_HOST), llm_port=int(module.LLM_PORT))
    cfg = _apply_overrides(cfg, module)

    if project_dir is not None:
        project_conf = project_dir / PROJECT_CONFIG_NAME
        if project_conf.exists():
            cfg = _apply_overrides(cfg, _load_module_from_path(project_conf))

    return cfg
