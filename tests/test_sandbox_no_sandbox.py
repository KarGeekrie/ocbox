"""Tests for --no-sandbox: sandbox.run_no_sandbox() and its helpers. No real
opencode install, no real symlinks into the actual ~/.config/opencode -
everything here is redirected into tmp_path via monkeypatched HOME/XDG vars.
"""

from __future__ import annotations

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
    assert bash_call.args[0] == ["bash"]
    assert bash_call.kwargs["input"] == curl_result.stdout


def test_find_or_install_raises_if_still_missing_after_install(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sandbox.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    with (
        patch.object(sandbox.subprocess, "run", return_value=MagicMock(stdout=b"")),
        pytest.raises(sandbox.NoSandboxError, match="add its install location to PATH"),
    ):
        sandbox._find_or_install_opencode()


# ---- _link_into_opencode_config ----------------------------------------


def test_link_creates_a_symlink_when_target_is_absent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    source = tmp_path / "opencode-config" / "agents"
    source.mkdir(parents=True)

    sandbox._link_into_opencode_config("agents", source)

    target = tmp_path / "config" / "opencode" / "agents"
    assert target.is_symlink()
    assert target.resolve() == source.resolve()


def test_link_is_idempotent_when_already_correct(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    source = tmp_path / "opencode-config" / "agents"
    source.mkdir(parents=True)
    sandbox._link_into_opencode_config("agents", source)

    sandbox._link_into_opencode_config("agents", source)  # must not raise

    target = tmp_path / "config" / "opencode" / "agents"
    assert target.resolve() == source.resolve()


def test_link_replaces_a_stale_symlink(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    old_source = tmp_path / "old-agents"
    old_source.mkdir()
    new_source = tmp_path / "opencode-config" / "agents"
    new_source.mkdir(parents=True)

    sandbox._link_into_opencode_config("agents", old_source)
    sandbox._link_into_opencode_config("agents", new_source)

    target = tmp_path / "config" / "opencode" / "agents"
    assert target.resolve() == new_source.resolve()


def test_link_refuses_to_replace_a_real_pre_existing_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    target = tmp_path / "config" / "opencode" / "agents"
    target.mkdir(parents=True)
    (target / "my-own-agent.md").write_text("not ocbox's")
    source = tmp_path / "opencode-config" / "agents"
    source.mkdir(parents=True)

    with pytest.raises(sandbox.NoSandboxError, match="isn't managed by ocbox"):
        sandbox._link_into_opencode_config("agents", source)
    assert (target / "my-own-agent.md").exists()


# ---- run_no_sandbox ----------------------------------------


@pytest.fixture
def mocked_no_sandbox_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    repo_config = tmp_path / "opencode-config"
    (repo_config / "agents").mkdir(parents=True)
    (repo_config / "skills").mkdir(parents=True)
    (repo_config / "opencode.jsonc").write_text('{"provider": {"local": {}}}')

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


def test_run_no_sandbox_links_agents_skills_and_jsonc_from_repo_config(
    tmp_path, mocked_no_sandbox_env
) -> None:
    sandbox.run_no_sandbox()

    config_home = tmp_path / "config" / "opencode"
    repo_config = mocked_no_sandbox_env["repo_config"]
    assert (config_home / "agents").resolve() == (repo_config / "agents").resolve()
    assert (config_home / "skills").resolve() == (repo_config / "skills").resolve()
    assert (config_home / "opencode.jsonc").resolve() == (repo_config / "opencode.jsonc").resolve()


def test_run_no_sandbox_honors_agents_and_skills_dir_overrides(
    tmp_path, mocked_no_sandbox_env
) -> None:
    custom_agents = tmp_path / "my-agents"
    custom_agents.mkdir()

    sandbox.run_no_sandbox(agents_dir=custom_agents)

    config_home = tmp_path / "config" / "opencode"
    assert (config_home / "agents").resolve() == custom_agents.resolve()


def test_run_no_sandbox_propagates_link_errors_as_no_sandbox_error(
    tmp_path, mocked_no_sandbox_env
) -> None:
    config_home = tmp_path / "config" / "opencode"
    (config_home / "agents").mkdir(parents=True)
    (config_home / "agents" / "mine.md").write_text("not ocbox's")

    with pytest.raises(sandbox.NoSandboxError):
        sandbox.run_no_sandbox()
