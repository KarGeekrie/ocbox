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


def test_find_or_install_runs_the_official_installer_when_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sandbox.Path, "home", lambda: tmp_path)
    which_results = iter([None, "/usr/local/bin/opencode"])  # before, then after install
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: next(which_results))

    curl_result = MagicMock(stdout=b"#!/bin/bash\necho installing\n")
    with patch.object(sandbox.subprocess, "run", return_value=curl_result) as mock_run:
        found = sandbox._find_or_install_opencode()

    assert found == "/usr/local/bin/opencode"
    curl_call, bash_call = mock_run.call_args_list
    assert curl_call.args[0][:2] == ["curl", "-fsSL"]
    assert bash_call.args[0] == ["bash", "-s", "--", "--no-modify-path"]
    assert bash_call.kwargs["input"] == curl_result.stdout


def test_find_or_install_raises_if_still_missing_after_install(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sandbox.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    with (
        patch.object(sandbox.subprocess, "run", return_value=MagicMock(stdout=b"")),
        pytest.raises(sandbox.NoSandboxError, match="add its install location to PATH"),
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

    # USER_CONFIG_PATH is an absolute path off the real HOME, so without this
    # the test picks up the developer's own ~/.config/ocbox/opencode.jsonc and
    # fails - on exactly the machines where the feature is actually used.
    monkeypatch.setattr(sandbox, "USER_CONFIG_PATH", tmp_path / "absent" / "opencode.jsonc")

    with (
        patch("ocbox.sandbox.image") as mock_image,
        patch("ocbox.sandbox._find_or_install_opencode", return_value="/usr/bin/opencode"),
        patch("ocbox.sandbox.os.execvpe") as mock_execvpe,
    ):
        mock_image.repo_config_dir.return_value = repo_config
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


def test_run_no_sandbox_prefers_the_users_own_opencode_jsonc(
    tmp_path, monkeypatch, mocked_no_sandbox_env
) -> None:
    user_file = tmp_path / "user" / "opencode.jsonc"
    user_file.parent.mkdir()
    user_file.write_text('{"provider": {"local": {}}}')
    monkeypatch.setattr(sandbox, "USER_CONFIG_PATH", user_file)

    sandbox.run_no_sandbox()

    _, _, env = mocked_no_sandbox_env["execvpe"].call_args.args
    linked = Path(env["OPENCODE_CONFIG_DIR"]) / "opencode.jsonc"
    assert linked.resolve() == user_file.resolve()


def test_run_no_sandbox_assembled_dir_carries_the_team_agents_md(mocked_no_sandbox_env) -> None:
    """An AGENTS.md inside OPENCODE_CONFIG_DIR is what OpenCode sends as the
    global one - verified against a real binary by recording request bodies."""
    sandbox.run_no_sandbox()

    _, _, env = mocked_no_sandbox_env["execvpe"].call_args.args
    linked = Path(env["OPENCODE_CONFIG_DIR"]) / "AGENTS.md"
    assert linked.resolve() == (mocked_no_sandbox_env["repo_config"] / "AGENTS.md").resolve()


def test_run_no_sandbox_drops_the_agents_md_link_once_the_file_is_gone(
    mocked_no_sandbox_env,
) -> None:
    sandbox.run_no_sandbox()
    (mocked_no_sandbox_env["repo_config"] / "AGENTS.md").unlink()

    sandbox.run_no_sandbox()

    _, _, env = mocked_no_sandbox_env["execvpe"].call_args.args
    link = Path(env["OPENCODE_CONFIG_DIR"]) / "AGENTS.md"
    assert not link.is_symlink()
    assert not link.exists()
