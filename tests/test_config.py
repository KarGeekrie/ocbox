from pathlib import Path

import pytest

from ocbox.config import ConfigError, load_config


def test_missing_config_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="No config found"):
        load_config(explicit_path=tmp_path / "does-not-exist.py")


def test_missing_llm_fields_raises(tmp_path: Path) -> None:
    conf = tmp_path / "conf.py"
    conf.write_text("BASE_IMAGE = 'x'\n")
    with pytest.raises(ConfigError, match="LLM_HOST and LLM_PORT"):
        load_config(explicit_path=conf)


def test_loads_required_fields(tmp_path: Path) -> None:
    conf = tmp_path / "conf.py"
    conf.write_text("LLM_HOST = '10.0.0.5'\nLLM_PORT = 11434\n")
    cfg = load_config(explicit_path=conf)
    assert cfg.llm_host == "10.0.0.5"
    assert cfg.llm_port == 11434
    assert cfg.base_image == "ocbox/base:latest"
    assert cfg.base_os == "ubuntu"


def test_loads_optional_overrides(tmp_path: Path) -> None:
    conf = tmp_path / "conf.py"
    conf.write_text(
        "LLM_HOST = '127.0.0.1'\n"
        "LLM_PORT = 8080\n"
        "BASE_IMAGE = 'custom:latest'\n"
        "CONTAINER_WEB_PORT = 9000\n"
        "EXTRA_APT_DEFAULT = ['git']\n"
        "EXTRA_UV_DEFAULT = ['ruff']\n"
        "MEMORY_LIMIT = '4g'\n"
        "PIDS_LIMIT = 256\n"
    )
    cfg = load_config(explicit_path=conf)
    assert cfg.base_image == "custom:latest"
    assert cfg.container_web_port == 9000
    assert cfg.extra_apt_default == ["git"]
    assert cfg.extra_uv_default == ["ruff"]
    assert cfg.memory_limit == "4g"
    assert cfg.pids_limit == 256


def test_project_local_override_wins(tmp_path: Path) -> None:
    global_conf = tmp_path / "global.py"
    global_conf.write_text("LLM_HOST = '127.0.0.1'\nLLM_PORT = 1111\n")

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "ocbox.conf.py").write_text("LLM_PORT = 2222\n")

    cfg = load_config(explicit_path=global_conf, project_dir=project_dir)
    assert cfg.llm_host == "127.0.0.1"
    assert cfg.llm_port == 2222


def test_invalid_python_raises(tmp_path: Path) -> None:
    conf = tmp_path / "conf.py"
    conf.write_text("this is not valid python (((\n")
    with pytest.raises(ConfigError, match="Error executing"):
        load_config(explicit_path=conf)


def test_base_os_ubuntu_accepted(tmp_path: Path) -> None:
    conf = tmp_path / "conf.py"
    conf.write_text("LLM_HOST = '127.0.0.1'\nLLM_PORT = 1\nBASE_OS = 'ubuntu'\n")
    cfg = load_config(explicit_path=conf)
    assert cfg.base_os == "ubuntu"


def test_base_os_rocky_accepted(tmp_path: Path) -> None:
    conf = tmp_path / "conf.py"
    conf.write_text("LLM_HOST = '127.0.0.1'\nLLM_PORT = 1\nBASE_OS = 'rocky'\n")
    cfg = load_config(explicit_path=conf)
    assert cfg.base_os == "rocky"


def test_base_os_unknown_value_rejected(tmp_path: Path) -> None:
    conf = tmp_path / "conf.py"
    conf.write_text("LLM_HOST = '127.0.0.1'\nLLM_PORT = 1\nBASE_OS = 'arch'\n")
    with pytest.raises(ConfigError, match="not supported"):
        load_config(explicit_path=conf)


def test_base_os_project_override(tmp_path: Path) -> None:
    global_conf = tmp_path / "global.py"
    global_conf.write_text("LLM_HOST = '127.0.0.1'\nLLM_PORT = 1\n")

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "ocbox.conf.py").write_text("BASE_OS = 'rocky'\n")

    cfg = load_config(explicit_path=global_conf, project_dir=project_dir)
    assert cfg.base_os == "rocky"
