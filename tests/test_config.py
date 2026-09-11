from pathlib import Path

import pytest

from ocbox.config import ConfigError, load_config


def test_no_config_file_at_all_gives_defaults(tmp_path: Path) -> None:
    """conf.py is optional: every setting has a default."""
    cfg = load_config(global_path=tmp_path / "absent.py")
    assert cfg.base_image == "ocbox/base:latest"
    assert cfg.base_os == "ubuntu"


def test_explicitly_named_missing_config_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="No config found"):
        load_config(explicit_path=tmp_path / "does-not-exist.py")


def test_loads_optional_overrides(tmp_path: Path) -> None:
    conf = tmp_path / "conf.py"
    conf.write_text(
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
    global_conf.write_text("CONTAINER_WEB_PORT = 1111\n")
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "ocbox.conf.py").write_text("CONTAINER_WEB_PORT = 2222\n")

    cfg = load_config(explicit_path=global_conf, project_dir=project_dir)
    assert cfg.container_web_port == 2222


def test_project_override_applies_without_a_global_config(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "ocbox.conf.py").write_text("BASE_OS = 'rocky'\n")

    cfg = load_config(global_path=tmp_path / "absent.py", project_dir=project_dir)
    assert cfg.base_os == "rocky"


@pytest.mark.parametrize("line", ["LLM_HOST = '10.0.0.5'", "LLM_PORT = 11434"])
def test_llm_address_in_conf_py_is_rejected_with_where_it_moved(tmp_path: Path, line) -> None:
    """Silently ignoring these would leave someone editing a value that does nothing."""
    conf = tmp_path / "conf.py"
    conf.write_text(line + "\n")
    with pytest.raises(ConfigError, match=r"provider\.local\.options\.baseURL"):
        load_config(explicit_path=conf)


def test_llm_address_in_a_project_conf_is_rejected_too(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "ocbox.conf.py").write_text("LLM_HOST = 'x'\n")
    with pytest.raises(ConfigError, match=r"opencode\.jsonc"):
        load_config(global_path=tmp_path / "absent.py", project_dir=project_dir)


def test_invalid_python_raises(tmp_path: Path) -> None:
    conf = tmp_path / "conf.py"
    conf.write_text("this is not valid python (((\n")
    with pytest.raises(ConfigError, match="Error executing"):
        load_config(explicit_path=conf)


def test_base_os_ubuntu_accepted(tmp_path: Path) -> None:
    conf = tmp_path / "conf.py"
    conf.write_text("BASE_OS = 'ubuntu'\n")
    assert load_config(explicit_path=conf).base_os == "ubuntu"


def test_base_os_rocky_accepted(tmp_path: Path) -> None:
    conf = tmp_path / "conf.py"
    conf.write_text("BASE_OS = 'rocky'\n")
    assert load_config(explicit_path=conf).base_os == "rocky"


def test_base_os_unknown_value_rejected(tmp_path: Path) -> None:
    conf = tmp_path / "conf.py"
    conf.write_text("BASE_OS = 'arch'\n")
    with pytest.raises(ConfigError, match="not supported"):
        load_config(explicit_path=conf)


def test_extra_apt_default_as_a_bare_string_is_rejected(tmp_path: Path) -> None:
    """`list("git")` would silently become ['g','i','t'] - three bogus packages."""
    conf = tmp_path / "conf.py"
    conf.write_text("EXTRA_APT_DEFAULT = 'git'\n")
    with pytest.raises(ConfigError, match="must be a list"):
        load_config(explicit_path=conf)


def test_extra_uv_default_as_a_bare_string_is_rejected(tmp_path: Path) -> None:
    conf = tmp_path / "conf.py"
    conf.write_text("EXTRA_UV_DEFAULT = 'ruff'\n")
    with pytest.raises(ConfigError, match="must be a list"):
        load_config(explicit_path=conf)


def test_unrecognised_setting_is_ignored_with_a_warning(tmp_path: Path, capsys) -> None:
    conf = tmp_path / "conf.py"
    conf.write_text("MEMORY_LIMITS = '2g'\n")  # typo for MEMORY_LIMIT
    cfg = load_config(explicit_path=conf)
    assert cfg.memory_limit is None
    err = capsys.readouterr().err
    assert "MEMORY_LIMITS" in err
    assert "MEMORY_LIMIT" in err


def test_known_settings_do_not_warn(tmp_path: Path, capsys) -> None:
    conf = tmp_path / "conf.py"
    conf.write_text("import os\nBASE_OS = 'ubuntu'\nPIDS_LIMIT = 256\n")
    load_config(explicit_path=conf)
    assert "unrecognised" not in capsys.readouterr().err
