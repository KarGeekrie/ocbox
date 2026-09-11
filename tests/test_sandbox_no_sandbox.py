"""Tests for --no-sandbox: sandbox.run_no_sandbox() and its helpers. No real
opencode install, no real symlinks into the actual ~/.config/opencode -
everything here is redirected into tmp_path via monkeypatched HOME/XDG vars.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ocbox import sandbox

# ---- _find_or_install_opencode ----------------------------------------


def test_find_or_install_returns_the_path_already_on_path(monkeypatch) -> None:
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/usr/local/bin/opencode")
    with patch.object(sandbox.subprocess, "run") as mock_run:
        found = sandbox._find_or_install_opencode()
    assert found == "/usr/local/bin/opencode"
    mock_run.assert_not_called()


def test_find_or_install_uses_the_well_known_fallback_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    monkeypatch.setattr(sandbox.Path, "home", lambda: tmp_path)
    fallback = tmp_path / ".opencode" / "bin" / "opencode"
    fallback.parent.mkdir(parents=True)
    fallback.write_text("#!/bin/sh\n")
    with patch.object(sandbox.subprocess, "run") as mock_run:
        found = sandbox._find_or_install_opencode()
    assert found == str(fallback)
    mock_run.assert_not_called()




def test_find_or_install_uses_an_existing_package_local_binary(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    monkeypatch.setattr(sandbox.Path, "home", lambda: tmp_path / "home")
    local = tmp_path / "repo" / ".ocbox"
    monkeypatch.setattr(sandbox.image, "repo_local_dir", lambda: local)
    (local / "bin").mkdir(parents=True)
    (local / "bin" / "opencode").write_text("#!/bin/sh\n")

    with patch.object(sandbox.subprocess, "run") as mock_run:
        assert sandbox._find_or_install_opencode() == str(local / "bin" / "opencode")
    mock_run.assert_not_called()


def _fake_installer(stdout=b"#!/bin/bash\n", produce_binary=True):
    """Stands in for curl + the official script, which writes $HOME/.opencode/bin."""

    def run(argv, **kwargs):
        if argv[0] == "curl":
            return MagicMock(stdout=stdout)
        if produce_binary:
            target = Path(kwargs["env"]["HOME"]) / ".opencode" / "bin" / "opencode"
            target.parent.mkdir(parents=True)
            target.write_text("binary")
        return MagicMock()

    return run


def test_find_or_install_installs_into_the_package_not_the_home(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(sandbox.Path, "home", lambda: home)
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    local = tmp_path / "repo" / ".ocbox"
    monkeypatch.setattr(sandbox.image, "repo_local_dir", lambda: local)

    with patch.object(sandbox.subprocess, "run", side_effect=_fake_installer()) as mock_run:
        found = sandbox._find_or_install_opencode()

    assert found == str(local / "bin" / "opencode")
    assert (local / "bin" / "opencode").read_text() == "binary"
    bash_call = mock_run.call_args_list[1]
    assert bash_call.args[0] == ["bash", "-s", "--", "--no-modify-path"]
    assert Path(bash_call.kwargs["env"]["HOME"]).is_relative_to(local)
    assert not (home / ".opencode").exists()
    assert sorted(p.name for p in local.iterdir()) == ["bin"], "throwaway install HOME left behind"


def test_find_or_install_raises_if_the_installer_produces_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sandbox.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    monkeypatch.setattr(sandbox.image, "repo_local_dir", lambda: tmp_path / "repo" / ".ocbox")
    with (
        patch.object(sandbox.subprocess, "run", side_effect=_fake_installer(produce_binary=False)),
        pytest.raises(sandbox.NoSandboxError, match="didn't produce"),
    ):
        sandbox._find_or_install_opencode()


# ---- run_no_sandbox ----------------------------------------


@pytest.fixture
def mocked_no_sandbox_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    # The assembled config dir lives under XDG_STATE_HOME; without this the
    # tests would write symlinks into the developer's real ~/.local/state.
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    repo_config = tmp_path / "opencode-config"
    (repo_config / "agents").mkdir(parents=True)
    (repo_config / "skills").mkdir(parents=True)
    (repo_config / "opencode.jsonc").write_text('{"provider": {"local": {}}}')
    (repo_config / "AGENTS.md").write_text("# Team rules\n")
    (repo_config / "environments").mkdir()
    (repo_config / "environments" / "no-sandbox.md").write_text("# Environment: your machine\n")
    (repo_config / "environments" / "sandbox.md").write_text("# Environment: sandbox\n")

    with (
        patch("ocbox.sandbox.image") as mock_image,
        patch("ocbox.sandbox._find_or_install_opencode", return_value="/usr/bin/opencode"),
        patch("ocbox.sandbox.os.execvpe") as mock_execvpe,
    ):
        mock_image.repo_config_dir.return_value = repo_config
        mock_image.repo_local_dir.return_value = tmp_path / "local"
        yield {"repo_config": repo_config, "execvpe": mock_execvpe}


def test_run_no_sandbox_execs_opencode_with_passthrough_args(mocked_no_sandbox_env) -> None:
    sandbox.run_no_sandbox(opencode_args=["run", "hello"])

    mocked_no_sandbox_env["execvpe"].assert_called_once()
    bin_path, argv, _env = mocked_no_sandbox_env["execvpe"].call_args.args
    assert bin_path == "/usr/bin/opencode"
    assert argv == ["/usr/bin/opencode", "run", "hello"]


def test_run_no_sandbox_generates_no_provider_override(mocked_no_sandbox_env) -> None:
    """Unlike the sandboxed modes, there's no relay to point at - OpenCode
    must read baseURL straight from the symlinked opencode.jsonc, so ocbox
    must not inject an OPENCODE_CONFIG override that would shadow it."""
    sandbox.run_no_sandbox()

    _, _, env = mocked_no_sandbox_env["execvpe"].call_args.args
    assert "OPENCODE_CONFIG" not in env


def test_run_no_sandbox_strips_a_stale_inherited_opencode_config_env(
    mocked_no_sandbox_env, monkeypatch
) -> None:
    monkeypatch.setenv("OPENCODE_CONFIG", "/some/stale/relay/config.json")

    sandbox.run_no_sandbox()

    _, _, env = mocked_no_sandbox_env["execvpe"].call_args.args
    assert "OPENCODE_CONFIG" not in env


def test_run_no_sandbox_points_opencode_at_an_assembled_config_dir(
    tmp_path, mocked_no_sandbox_env
) -> None:
    sandbox.run_no_sandbox()

    _, _, env = mocked_no_sandbox_env["execvpe"].call_args.args
    config_dir = Path(env["OPENCODE_CONFIG_DIR"])
    repo_config = mocked_no_sandbox_env["repo_config"]
    assert (config_dir / "agents").resolve() == (repo_config / "agents").resolve()
    assert (config_dir / "skills").resolve() == (repo_config / "skills").resolve()
    assert (config_dir / "opencode.jsonc").resolve() == (repo_config / "opencode.jsonc").resolve()


def test_run_no_sandbox_never_touches_the_users_opencode_config(
    tmp_path, mocked_no_sandbox_env
) -> None:
    """ocbox itself writes nothing under ~/.config/opencode: no symlinks, no
    config. OpenCode, when actually run, reads that directory and installs its
    plugin SDK there on its own account - see run_no_sandbox's docstring. This
    test pins what ocbox does, with OpenCode's exec mocked out."""
    users_config = tmp_path / "config" / "opencode"
    users_config.mkdir(parents=True)
    (users_config / "agents").mkdir()
    (users_config / "agents" / "theirs.md").write_text("---\ndescription: mine\n---\n")

    sandbox.run_no_sandbox()

    assert (users_config / "agents" / "theirs.md").exists()
    assert not (users_config / "agents" / "theirs.md").is_symlink()
    assert not (users_config / "opencode.jsonc").exists()
    assert not (users_config / "skills").exists()


def test_run_no_sandbox_assembled_dir_honors_the_dir_overrides(
    tmp_path, mocked_no_sandbox_env
) -> None:
    custom_agents = tmp_path / "my-agents"
    custom_agents.mkdir()

    sandbox.run_no_sandbox(agents_dir=custom_agents)

    _, _, env = mocked_no_sandbox_env["execvpe"].call_args.args
    assert (Path(env["OPENCODE_CONFIG_DIR"]) / "agents").resolve() == custom_agents.resolve()


def test_run_no_sandbox_ignores_a_jsonc_left_in_the_home_directory(
    tmp_path, monkeypatch, mocked_no_sandbox_env
) -> None:
    """opencode-config/opencode.jsonc is the only default. A copy under
    ~/.config/ocbox - which older versions preferred - must not shadow it."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    stray = tmp_path / "home" / ".config" / "ocbox" / "opencode.jsonc"
    stray.parent.mkdir(parents=True)
    stray.write_text('{"provider": {"local": {}}}')

    sandbox.run_no_sandbox()

    _, _, env = mocked_no_sandbox_env["execvpe"].call_args.args
    linked = Path(env["OPENCODE_CONFIG_DIR"]) / "opencode.jsonc"
    assert linked.resolve() == (mocked_no_sandbox_env["repo_config"] / "opencode.jsonc").resolve()


def test_run_no_sandbox_assembles_its_config_dir_inside_the_package(
    tmp_path, mocked_no_sandbox_env
) -> None:
    sandbox.run_no_sandbox()

    _, _, env = mocked_no_sandbox_env["execvpe"].call_args.args
    assert Path(env["OPENCODE_CONFIG_DIR"]).is_relative_to(tmp_path / "local")


def test_run_no_sandbox_agents_md_is_the_host_version_plus_team_rules(
    mocked_no_sandbox_env,
) -> None:
    """The sandbox description must never reach an agent running on the host."""
    sandbox.run_no_sandbox()

    _, _, env = mocked_no_sandbox_env["execvpe"].call_args.args
    agents_md = Path(env["OPENCODE_CONFIG_DIR"]) / "AGENTS.md"
    assert not agents_md.is_symlink()
    text = agents_md.read_text()
    assert text.index("# Environment: your machine") < text.index("# Team rules")
    assert "# Environment: sandbox" not in text


def test_run_no_sandbox_drops_agents_md_when_nothing_composes_one(
    mocked_no_sandbox_env,
) -> None:
    repo_config = mocked_no_sandbox_env["repo_config"]
    sandbox.run_no_sandbox()
    (repo_config / "AGENTS.md").unlink()
    for env_file in (repo_config / "environments").iterdir():
        env_file.unlink()

    sandbox.run_no_sandbox()

    _, _, env = mocked_no_sandbox_env["execvpe"].call_args.args
    agents_md = Path(env["OPENCODE_CONFIG_DIR"]) / "AGENTS.md"
    assert not agents_md.exists()
    assert not agents_md.is_symlink()
